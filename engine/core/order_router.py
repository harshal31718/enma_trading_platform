"""Raw Binance order-placement plumbing shared by `LiveAdapter`'s
execute_entry/execute_reduce/execute_exit/execute_flip and `Reconciler`.

Extracted from `LiveBotManager`/`LiveAdapter` (Plan 6 Step 6.1, ENG-1) as the
last of the five planned collaborator extractions. Unlike the other four,
this one is NOT a mechanical whole-method move — `execute_entry` in
particular tangles three concerns (raw order placement, risk/governor
decision logic, and `LiveAdapter`'s job as the `ExecutionKernel`'s
polymorphic adapter). Only the first concern lives here: placing a
MARKET/algo order, formatting its params, and confirming its real fill
price (never trusting a candle/trigger-price estimate — Plan 5 Step 5.2,
ENG-2). Deciding WHETHER to trade (protections, rate limiter, risk
governor, liq-buffer, M-5 SL-validity) and mutating local session/position
state stay in `LiveAdapter` — moving them here would blur exactly the seam
this extraction exists to draw. `LiveAdapter`'s job as the polymorphic
`ExecutionAdapter` (killing `is_live` branching in `core/kernel.py`) is
Step 6.4's remaining, unattempted half, not this module's.

The five free functions below (`fmt_num`/`make_client_id`/
`binance_error_detail`/`extract_fill_price`/`query_real_fill_price`/
`uuid4_hex8`) were previously module-level in `live_bot_manager.py`, used by
both `LiveAdapter` and `Reconciler` (which imports them via
`from core.live_bot_manager import ...`, unchanged — `live_bot_manager.py`
re-exports them from here so that import keeps working with zero call-site
changes).
"""
from __future__ import annotations

import logging
from uuid import uuid4

import httpx

from core.exchange import Exchange, BinanceFuturesTestnet

logger = logging.getLogger(__name__)


def fmt_num(value: float) -> str:
    """Format a numeric value for Binance API (strip trailing zeros/dot)."""
    s = f"{value:.8f}".rstrip('0').rstrip('.')
    return s if s else '0'


def uuid4_hex8() -> str:
    """Return the first 8 hex chars of a random UUID — short unique prefix."""
    return uuid4().hex[:8]


def make_client_id(session_id: str, symbol: str, suffix: str = "") -> str:
    """Build a Binance ``newClientOrderId`` guaranteed to stay under the 36-char
    exchange limit (``-4015 Client order id length should be less than 36 chars``
    otherwise). Shape: ``enma_<sess8>_<sym...>_<uuid8><suffix>``, trimming the
    symbol segment to whatever budget remains after the fixed parts.

    The symbol segment is purely cosmetic (for log/trace readability) — nothing
    parses it back out of the id; the only structural checks anywhere are
    ``.startswith("enma_")`` / ``"tpsl_"`` / ``"oco_"``, and uniqueness comes from
    the uuid8 — so trimming the symbol is safe. Found via live testnet chaos
    2026-07-19: the old ``f"enma_{session_id[:8]}_{symbol}_{uuid4_hex8()}_emrg"``
    was 37 chars for a 9-char symbol (e.g. KAITOUSDC), so the F-018 emergency
    close failed with -4015 on every symbol >= 8 chars, leaving the position
    briefly naked until the next-candle re-arm.
    """
    _LIMIT = 35  # Binance requires length < 36
    uid = uuid4_hex8()
    sess = session_id[:8]
    fixed = len("enma_") + len(sess) + 1 + len(uid) + len(suffix)
    room = _LIMIT - fixed - 1  # -1 for the "_" between the symbol and the uid
    if room > 0 and symbol:
        return f"enma_{sess}_{symbol[:room]}_{uid}{suffix}"
    return f"enma_{sess}_{uid}{suffix}"


def binance_error_detail(exc: Exception) -> str:
    """Extract Binance's own {code, msg} body from a failed signed call.

    httpx.HTTPStatusError's default str() is just "Client error '400 Bad
    Request' for url '...'" — it never surfaces the response body, which is
    the only place the actual reason (bad precision, filter failure, order
    would immediately trigger, etc.) lives. `engine/routers/trade.py`'s route
    handlers already parse `exc.response.json()` themselves; this gives the
    live-bot's fire-and-forget SL/TP/order call sites the same visibility so
    failures are diagnosable from logs instead of a generic "400 Bad Request".
    """
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            body = exc.response.json()
            code = body.get("code", exc.response.status_code)
            msg = body.get("msg", "")
            return f"{code} {msg}".strip()
        except Exception:
            return f"{exc.response.status_code} {exc.response.text[:300]}"
    return str(exc)


def extract_fill_price(order_result: dict) -> float | None:
    """Real avgPrice from a Binance order response, or None if unusable.

    Plan 5 Step 5.2 (ENG-2): the caller must NEVER fall back to a candle/
    trigger-price estimate silently — None here means "go query the order
    for its real fill," not "use the estimate and move on."
    """
    try:
        price = float(order_result.get("avgPrice", 0) or 0)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


async def query_real_fill_price(
    api_key: str, api_secret: str, symbol: str, client_order_id: str,
    exchange: Exchange | None = None,
) -> float | None:
    """Fallback when the order response itself didn't carry a usable avgPrice
    (can happen if Binance processes the fill a beat after the ACK/RESULT
    response) — queries the order directly by its client id.

    `exchange` defaults to `BinanceFuturesTestnet()` (Plan 6 Step 6.2, ENG-4)
    — every real call site threads the session's own resolved `Exchange`
    instance through; the default only matters for direct/test callers.
    """
    try:
        _exchange = exchange or BinanceFuturesTestnet()
        order = await _exchange.query_order(
            api_key, api_secret,
            params={"symbol": symbol, "origClientOrderId": client_order_id},
        )
        return extract_fill_price(order)
    except Exception as e:
        logger.error(f"[AlgoBot] {symbol}: fill-price re-query failed: {e}")
        return None


class OrderRouter:
    """Places/confirms MARKET and CONDITIONAL (SL/TP) orders on Binance
    Futures Testnet. Stateless — every method takes the session's own
    api_key/api_secret rather than holding them, matching the pattern every
    other call site in this file already uses (credentials live on the
    session dict, not on any collaborator instance).
    """

    @staticmethod
    async def place_market_order(
        api_key: str, api_secret: str, symbol: str, side: str, qty: float,
        client_order_id: str, reduce_only: bool = False,
        exchange: Exchange | None = None,
    ) -> dict:
        """POST /fapi/v1/order — MARKET order, RESULT response (synchronous
        fill confirmation in the same response where Binance provides one).

        `exchange` (Plan 6 Step 6.2, ENG-4) defaults to `BinanceFuturesTestnet()`
        — real call sites (`LiveAdapter`) pass the session's own resolved
        instance; the default only matters for direct/test callers.
        """
        _exchange = exchange or BinanceFuturesTestnet()
        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": fmt_num(qty),
            "newOrderRespType": "RESULT",
            "newClientOrderId": client_order_id,
        }
        if reduce_only:
            params["reduceOnly"] = "true"
        return await _exchange.place_order(api_key, api_secret, params)

    @staticmethod
    async def place_algo_order(
        api_key: str, api_secret: str, symbol: str, side: str, order_type: str,
        trigger_price: float, client_algo_id: str,
        exchange: Exchange | None = None,
    ) -> dict:
        """POST /fapi/v1/algoOrder — CONDITIONAL closePosition SL/TP order
        (STOP_MARKET or TAKE_PROFIT_MARKET), MARK_PRICE working type."""
        _exchange = exchange or BinanceFuturesTestnet()
        params = {
            "algoType": "CONDITIONAL",
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "triggerPrice": fmt_num(trigger_price),
            "workingType": "MARK_PRICE",
            "closePosition": "true",
            "clientAlgoId": client_algo_id,
        }
        return await _exchange.place_algo_order(api_key, api_secret, params)

    @staticmethod
    async def confirm_fill(
        order_result: dict, api_key: str, api_secret: str, symbol: str, client_order_id: str,
        exchange: Exchange | None = None,
    ) -> float | None:
        """The repeated "trust the response's avgPrice, else re-query by
        client id" ladder used by every entry/reduce/exit/emergency-close
        path — never falls back to a caller-supplied estimate itself (ENG-2);
        returns None to signal "still unconfirmed, caller decides what to do."
        """
        price = extract_fill_price(order_result)
        if price is not None:
            return price
        return await query_real_fill_price(api_key, api_secret, symbol, client_order_id, exchange=exchange)
