"""Plan 22 Step 22.4: shared Zone 1 VaR/CVaR service.

Single source of truth for account-wide VaR/CVaR, used by BOTH:
  - the Zone 1 dashboard endpoint (`routers/risk.py`'s `GET /live-metrics`)
  - the live Session Risk Governor (`core/models/governor.py`'s `check_var`,
    wired from `core/live_bot_manager.py`'s `execute_entry` pre-trade gate
    and `_push_stats` periodic tick)

Both call sites route through `compute_var_cvar()` below, which itself is a
thin wrapper around `utils/risk_math.py`'s `calculate_portfolio_var` (left
untouched — this module doesn't reimplement the math, only shares the one
computation path). This is what the acceptance criterion "dashboard value
and governor value provably identical (same function, one test)" checks —
see `engine/tests/test_portfolio_risk_shared_service.py`.

Design decision: account-wide, not session-scoped. A live session is an
internal orchestration concept; the actual margin/liquidation risk Binance
enforces is account-wide, shared across every session running on the same
API key (Chaos runs dozens of sessions on one key). Scoping VaR to "this
session's positions only" would produce a number that diverges from the
dashboard's (which has always been account-wide, unchanged here) and would
understate real risk when multiple sessions share a key. So the governor
asks the exact same question the dashboard shows: "what is this account's
VaR/CVaR right now" — same inputs, same function, same answer.

Caching (bounds REST/DB weight — this step's third acceptance criterion):
  - Binance account fetch (`/fapi/v2/account`) cached 10s per (api_key, mode).
    A session's periodic `_push_stats` tick and pre-trade `execute_entry`
    gate, plus the dashboard's own polling, all share this cache instead of
    each independently re-hitting Binance's account endpoint.
  - TimescaleDB close-price history cached 60s per distinct symbol set.
Both caches are process-local, in-memory, per-engine-instance — adequate at
current scale (single engine process, per `AGENTS.md`'s architecture); would
need a shared cache (Redis) if the engine is ever horizontally scaled. Noted
as a future consideration, not addressed here (no such deployment exists).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

import numpy as np

from utils.risk_math import calculate_portfolio_var, calculate_correlation_matrix
from config.timescale import get_pool

logger = logging.getLogger(__name__)

PRICE_HISTORY_TTL_SECONDS = 60.0
ACCOUNT_TTL_SECONDS = 10.0

# Process-local caches: key -> (monotonic_timestamp, value)
_price_history_cache: Dict[tuple, Tuple[float, dict]] = {}
_account_cache: Dict[tuple, Tuple[float, dict]] = {}


def _cache_get(cache: dict, key, ttl: float):
    entry = cache.get(key)
    if entry is None:
        return None
    ts, value = entry
    if (time.monotonic() - ts) >= ttl:
        return None
    return value


def clear_caches() -> None:
    """Test-only helper — process-local caches persist across calls within
    one engine process, which would otherwise leak stub data between test
    functions that patch the underlying fetchers."""
    _price_history_cache.clear()
    _account_cache.clear()


async def fetch_close_prices(symbols: List[str]) -> Dict[str, np.ndarray]:
    """Moved from `routers/risk.py` (Plan 22 Step 22.4), now 60s-cached per
    distinct symbol set so the dashboard's own polling and every live
    session's governor tick don't each independently re-query TimescaleDB."""
    if not symbols:
        return {}
    cache_key = tuple(sorted(symbols))
    cached = _cache_get(_price_history_cache, cache_key, PRICE_HISTORY_TTL_SECONDS)
    if cached is not None:
        return cached

    pool = get_pool()
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    query = """
        SELECT symbol, close FROM candles
        WHERE timeframe = '1h'
        AND symbol = ANY($1)
        AND time >= $2
        ORDER BY time ASC
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, symbols, cutoff)
        data: Dict[str, list] = {}
        for r in rows:
            sym = r["symbol"]
            val = float(r["close"])
            data.setdefault(sym, []).append(val)
        result = {k: np.array(v, dtype=float) for k, v in data.items()}
    except Exception as e:
        logger.error(f"Error fetching close prices from TimescaleDB: {e}")
        result = {}

    _price_history_cache[cache_key] = (time.monotonic(), result)
    return result


async def fetch_account_positions(api_key: str, api_secret: str, mode: str = "testnet") -> dict:
    """Whole-account Binance position snapshot, 10s-cached per (api_key,
    mode). Raises on a genuine fetch failure (no silent empty-dict fallback)
    — callers (dashboard route, governor pre-trade/periodic checks) each
    decide their own fail-open/fail-closed policy, same separation used
    throughout `live_bot_manager.py`'s other risk checks."""
    cache_key = (api_key, mode)
    cached = _cache_get(_account_cache, cache_key, ACCOUNT_TTL_SECONDS)
    if cached is not None:
        return cached

    from services.binance_testnet import send_signed_request
    account_data = await send_signed_request(
        "GET", "/fapi/v2/account", api_key, api_secret, mode=mode,
    )
    _account_cache[cache_key] = (time.monotonic(), account_data)
    return account_data


def extract_position_notionals(account_data: dict):
    """Moved verbatim from `routers/risk.py`'s inline extraction loop — one
    parser shared by both call sites so they can't silently drift on how
    Binance's `positions` array is read."""
    active_symbols: List[str] = []
    position_notionals: Dict[str, float] = {}
    exposures: Dict[str, dict] = {}
    for p in account_data.get("positions", []):
        amt = float(p.get("positionAmt", 0.0))
        if amt != 0.0:
            sym = p.get("symbol")
            entry_price = float(p.get("entryPrice", 0.0))
            notional = float(p.get("notional") or (amt * entry_price))
            side = "long" if amt > 0 else "short"
            lev = int(p.get("leverage", 1))
            active_symbols.append(sym)
            position_notionals[sym] = amt * entry_price
            exposures[sym] = {"side": side, "notional": f"{abs(notional):.2f}", "leverage": str(lev)}
    return active_symbols, position_notionals, exposures


async def compute_var_cvar(
    api_key: str,
    api_secret: str,
    mode: str = "testnet",
    confidence_level: float = 0.95,
) -> Tuple[float, float]:
    """THE shared function — both `routers/risk.py`'s dashboard endpoint and
    `SessionRiskGovernor`'s pre-trade/periodic VaR check call this, with the
    same (api_key, mode) for sessions sharing a key. Returns (var_amount,
    cvar_amount) in dollar terms, per `calculate_portfolio_var`'s contract.
    """
    account_data = await fetch_account_positions(api_key, api_secret, mode)
    active_symbols, position_notionals, _exposures = extract_position_notionals(account_data)
    price_histories = await fetch_close_prices(active_symbols)
    return calculate_portfolio_var(position_notionals, price_histories, confidence_level=confidence_level)


async def compute_full_metrics(api_key: str, api_secret: str, mode: str = "testnet") -> dict:
    """Everything `routers/risk.py`'s `/live-metrics` endpoint needs, in one
    call — extracted so the route itself becomes a thin formatter, not a
    second copy of this fetch/compute sequence."""
    account_data = await fetch_account_positions(api_key, api_secret, mode)
    wallet_balance = float(account_data.get("totalWalletBalance", 0.0))
    margin_balance = float(account_data.get("totalMarginBalance", 0.0))
    initial_margin = float(account_data.get("totalInitialMargin", 0.0))
    active_symbols, position_notionals, exposures = extract_position_notionals(account_data)

    total_notional = sum(abs(float(exp["notional"])) for exp in exposures.values())
    net_leverage = total_notional / margin_balance if margin_balance > 0 else 0.0

    price_histories = await fetch_close_prices(active_symbols)
    var95, cvar95 = calculate_portfolio_var(position_notionals, price_histories, confidence_level=0.95)
    var99, cvar99 = calculate_portfolio_var(position_notionals, price_histories, confidence_level=0.99)
    corr_matrix = calculate_correlation_matrix(price_histories)

    return {
        "wallet_balance": wallet_balance,
        "margin_balance": margin_balance,
        "initial_margin": initial_margin,
        "active_symbols": active_symbols,
        "exposures": exposures,
        "net_leverage": net_leverage,
        "var95": var95,
        "cvar95": cvar95,
        "var99": var99,
        "cvar99": cvar99,
        "correlation_matrix": corr_matrix,
    }
