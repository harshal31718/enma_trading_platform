from __future__ import annotations
import asyncio
import contextlib
import json
import logging
import os
import random
from datetime import datetime, timezone
from decimal import ROUND_DOWN, ROUND_UP
from enum import Enum

import numpy as np
import websockets

from core.position import Position
from core.money import add_money
from core.market_data_feed import MarketDataFeed
from core.node_notifier import NodeNotifier
from core.session_registry import SessionRegistry
from core.reconciler import Reconciler
from core.exchange import Exchange, BinanceFuturesTestnet
from core.order_router import (
    OrderRouter,
    fmt_num as _fmt_num,
    make_client_id as _make_client_id,
    binance_error_detail as _binance_error_detail,
    extract_fill_price as _extract_fill_price,
    query_real_fill_price as _query_real_fill_price,
    uuid4_hex8,
)
from core.models import (
    DefaultPortfolioModel, InverseVolatilityPortfolio, compute_realized_volatility,
    LiveExecution, OrderPlan,
    CooldownPeriod, StoplossGuard, MaxDrawdownProtection, LowProfitPairsProtection,
    ProtectionManager,
    SessionRiskGovernor,
    GovernorVerdict,
)
from core.params import param_coerce, param_default, param_validate
from core.pipeline import evaluate
from services.trade_recorder import record_trade, build_trade_record
from services.event_log import append_event, reset_session_seq, fetch_events, fold_events
from services.user_data_stream import UserDataStreamManager
from services.pairlist import pairlist_from_config
from utils.symbols import round_price, clamp_and_round_qty, clamp_leverage, is_symbol_invalid
from core.kernel import ExecutionAdapter, ExecutionKernel

logger = logging.getLogger(__name__)

# How many historical candles to load for indicator warmup
WARMUP_CANDLES = 200

# A-7 (Plan 21.4): consecutive naked-position SL re-arm failures before the
# reconcile loop gives up and force-closes the position for safety, rather
# than letting it run unprotected indefinitely.
_NAKED_POSITION_MAX_REARM_ATTEMPTS = 3

# A-14 (Plan 21.7): entries are MARKET at next-tick after candle close with no
# max-deviation check between the closed-candle ref_price and the real fill.
# Every fill's slippage is now logged (data is already booked — real fill vs
# ref); this threshold only controls whether it escalates to a `warning` +
# session-log notification instead of a routine `info` line. Low urgency on
# testnet (this is what informational logging is for); required reading
# before any mainnet conversation per the audit.
_SLIPPAGE_ALERT_THRESHOLD_PCT = 0.01  # 1%

# Maps strategy tf param values to Binance interval strings (case-sensitive: "1M" = monthly)
_TF_TO_BINANCE = {
    "1h": "1h",
    "4h": "4h",
    "daily": "1d",
    "weekly": "1w",
    "monthly": "1M",
}

# Plan 21 A-12 (DECISIONS.md #24): live indicator/signal candles are sourced
# from Binance mainnet's public kline WebSocket, not testnet's own feed —
# warmup candles (TimescaleDB/REST) and HTF candles (_fetch_htf_candles) were
# already mainnet-sourced, so testnet's live ticks were the one remaining
# splice point where the price series could step discontinuously on an
# illiquid testnet symbol. Order EXECUTION is untouched — every signed
# Binance call routes through the session's resolved `Exchange` instance
# (Plan 6 Step 6.2, `core/exchange.py`), which is BinanceFuturesTestnet()
# today; only the read-only kline stream this constant builds URLs from
# moves independently of that. No auth needed (public
# market data), same as the client's own `binanceWS.js` connection.
# Mirrors that file's routing: kline streams go to /market/ws/ (only @depth*
# streams use /public/ws/, not relevant here).
_MAINNET_WS_BASE = "wss://fstream.binance.com/market/ws"


def _kline_ws_url(symbol: str, timeframe: str) -> str:
    """Mainnet public kline stream URL for the live signal/indicator feed
    (A-12). `symbol` is the trading pair (any case), `timeframe` a Binance
    interval string (e.g. "1h") — same stream-name format testnet used."""
    return f"{_MAINNET_WS_BASE}/{symbol.lower()}@kline_{timeframe}"

TRADING_STATES = ("active", "reducing", "halted")


from utils.rate_limiter import OrderRateLimiter


def _classify_exchange_sync_exit_reason(
    exit_price: float, sl_price: float | None, tp_price: float | None, tolerance_pct: float = 0.005,
) -> str:
    """Plan 22 Step 22.3: `_reconcile_exchange_state`'s Case 2 books every
    exchange-side close as the generic `exit_reason="exchange_sync"` — it
    can't ask Binance's raw trade history "was this the SL or the TP", so
    the notification/UI contract deliberately keeps that generic label
    (unchanged by this function). But `StoplossGuard`/`MaxDrawdown` need to
    know whether a close was actually a protective stop to work at all, and
    since A-13 exchange brackets are now the SOLE trigger while armed, Case 2
    is the path most real stoploss closes go through — feeding it "exchange_
    sync" unconditionally would make those protections nearly blind.

    Best-effort classification for internal protections bookkeeping ONLY
    (never for the outward notification): a STOP_MARKET/TAKE_PROFIT_MARKET
    order fills very close to its trigger price (mark-price-triggered,
    immediate MARKET fill) — if the actual/estimated exit price lands within
    `tolerance_pct` of the strategy's tracked stop or target, classify it as
    that. Otherwise falls back to the generic "exchange_sync" (e.g. a manual
    close on the exchange, or session-stop force-close reconciled here).
    """
    if sl_price is not None and sl_price > 0 and abs(exit_price - sl_price) <= tolerance_pct * sl_price:
        return "stop_loss"
    if tp_price is not None and tp_price > 0 and abs(exit_price - tp_price) <= tolerance_pct * tp_price:
        return "take_profit"
    return "exchange_sync"


def _get_min_candles_required(strategy) -> int:
    """
    Finds the largest numeric param on the strategy and applies a 2x buffer
    to ensure all indicator lookback windows (including derived ones like
    atr_sma = atr_period * 2) have enough candles.
    Falls back to 100 if no params exist.
    """
    params_schema = getattr(strategy.__class__, "PARAMS", {})
    numeric_values = [
        getattr(strategy, key, meta.get("default", 0))
        for key, meta in params_schema.items()
        if meta.get("type") in ("int", "float")
    ]
    largest = max((v for v in numeric_values if isinstance(v, (int, float)) and v > 0), default=50)
    return int(largest) * 3  # 3x buffer: covers derived indicators (e.g. atr_sma = atr_period * 2)

def _safe_float(val, default):
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _extract_fill_client_id(order_data: dict) -> str:
    """A-2 fix (Plan 21.1): pull the client/algo id off an ORDER_TRADE_UPDATE
    `o` payload safely.

    Binance's real payload has no `"clientOrderId"` key — the field is `"c"`.
    The previous code read `.get("clientOrderId", "")` (always `""`) and fell
    back to `.get("i", "")`, Binance's numeric `orderId` (an int in the JSON).
    Calling `.startswith(...)` on that int raised `AttributeError` on every
    FILLED/PARTIALLY_FILLED frame, which killed `_on_fill` before its
    reconcile call ever ran — the event-driven fill path (F-020) was dead
    code. Always returns a `str`, coercing the int-orderId fallback so the
    caller's `.startswith()` check can never crash.
    """
    return str(order_data.get("c") or order_data.get("i") or "")


def _account_update_needs_reconcile(pos_data: dict, has_local_position: bool) -> bool:
    """A-8 fix (Plan 21.2): decide whether an ACCOUNT_UPDATE position delta
    (one entry of the `a.P[]` array) disagrees with the engine's local view
    enough to warrant an immediate reconcile, instead of waiting for the
    next candle-close poll.

    Binance emits ACCOUNT_UPDATE with a position delta for EVERY position
    change — plain orders, conditional/algo TP-SL fills, liquidations,
    manual closes — regardless of whether ORDER_TRADE_UPDATE fires for algo
    orders the way `_on_fill`'s `tpsl_` client-id match depends on. This is
    the event-type-agnostic fallback that closes the ~60s staleness window.

    Only the OPEN<->FLAT boundary is treated as reconcile-worthy here — a
    quantity-only change on an already-agreed-open position is left to the
    next candle-close reconcile (which also refreshes unrealized PnL/mark
    price), keeping this callback cheap and focused on the actual staleness
    bug rather than firing on every position-size tick.
    """
    exchange_amt = _safe_float(pos_data.get("pa"), 0.0)
    has_exchange_position = exchange_amt != 0
    return has_exchange_position != has_local_position


async def _fetch_available_balance(api_key: str, api_secret: str) -> float | None:
    """Plan 22 Step 22.1 (B-11 engine backstop): query the real Binance
    Testnet available balance once, so `start_session` can defend against a
    configured `capital` that exceeds what the wallet actually holds — the
    entry-time notional guard only ever checked against the *configured*
    fiction, never the wallet, so a bot configured with far more capital than
    the account holds sized orders too large and only ever discovered it via
    Binance's own margin-rejection errors instead of a risk control.

    Best-effort: returns None on any failure (missing creds, network error,
    Binance error) rather than raising — this is a defensive clamp, not a
    hard gate. The server-side gate (`startSession`/`startChaos`, Node) is
    the primary UX; this is the backstop for sessions the engine started
    directly or where the server check was bypassed.
    """
    if not api_key or not api_secret:
        return None
    try:
        # Called before start_session resolves this session's own Exchange
        # (there is no session yet) — always BinanceFuturesTestnet() today,
        # same as every other call site's default (Plan 6 Step 6.2, ENG-4).
        account = await BinanceFuturesTestnet().query_account(api_key, api_secret)
        return _safe_float(account.get("availableBalance"), None)
    except Exception as e:
        logger.warning(f"[AlgoBot] capital integrity backstop: balance fetch failed — {e}")
        return None


async def _seed_pnl_from_event_log(session_id: str, symbols: list[str]) -> float:
    """Plan 5 Step 5.6 (ENG-7): sum each symbol's realized PnL by replaying
    this session's own execution event log.

    Used only when resuming a session after an engine restart. Currently-OPEN
    positions self-heal for free via `_reconcile_exchange_state`'s existing
    Case 1 (exchange is truth for what's open right now) the first time each
    symbol's candle loop runs — no new code needed there. But PnL from trades
    that already closed *before* the restart isn't on the exchange position
    endpoint at all (Binance doesn't expose a running per-bot realized-PnL
    counter), so the only place to recover it is this session's own event log.

    Best-effort per symbol: a replay failure for one symbol logs and
    contributes 0 rather than aborting the whole resume.
    """
    total = 0.0
    for symbol in symbols:
        try:
            events = await fetch_events(session_id, symbol)
            total += fold_events(events)["realizedPnl"]
        except Exception as e:
            logger.warning(f"[AlgoBot] {session_id}/{symbol}: event-log PnL replay failed — {e}")
    return total


class LiveAdapter(ExecutionAdapter):
    def __init__(self, manager: LiveBotManager, session_id: str):
        # Plan 6 Step 6.4 (ENG-5, partial): resolve the actual collaborators
        # once here instead of chaining `self.manager.<attr>` through every
        # method body — kills the "reaches into manager internals" pattern
        # for registry/notifier/reconciler-owned state. Constructor still
        # accepts `manager` (not a full injected-dependency signature) —
        # deliberate: this file has zero golden-master coverage (live-only,
        # no import overlap with the backtest path per Plan 5.3's own note),
        # and 19 existing tests construct `LiveAdapter(mgr, sid)` directly,
        # so a constructor-signature change is a materially larger, riskier
        # move left for a dedicated pass alongside the kernel's `is_live`
        # branch removal (this step's other, unattempted half).
        self.manager = manager
        self.session_id = session_id
        self._registry = manager._registry
        self._notifier = manager._notifier
        self._reconciler = manager._reconciler
        # Plan 6 Step 6.1 (ENG-1): raw order-placement plumbing (place
        # MARKET/algo orders, confirm real fill price) — stateless, so a
        # fresh instance per adapter is fine (no session state to share).
        self._order_router = OrderRouter()

    @property
    def is_live(self) -> bool:
        return True

    async def verify_position(self, strategy, symbol: str) -> None:
        # Reconciliation is now handled by _reconcile_exchange_state() called
        # unconditionally at the top of every candle loop (F-001/F-004).
        pass

    async def execute_entry(
        self, strategy, symbol: str, direction: str, qty: float, ref_price: float,
        time_t: datetime, index_t: int, intent: str = "enter", adjust_tag: str = "",
    ) -> bool:
        session = self._registry.sessions.get(self.session_id)
        if not session:
            return False
        # Plan 6 Step 6.2 (ENG-4): resolved once per call, threaded through
        # every OrderRouter call below instead of a hardcoded mode="testnet".
        exchange = session.get("exchange") or BinanceFuturesTestnet()

        # DCA scale-in (A-014): skip new-entry guards when adding to existing position
        is_dca = intent == "add" and strategy.position is not None and strategy.position.is_open

        if not is_dca:
            # TradingState check (A-002) — halt new entries when reducing or halted
            trading_state = session.get("trading_state", "active")
            if trading_state in ("halted", "reducing"):
                logger.warning(f"[AlgoBot] {symbol}: entry blocked, trading_state={trading_state}")
                await self._notifier.notify(self.session_id, {
                    "event": "log",
                    "eventData": {"type": "warning", "message": f"{symbol}: entry blocked (trading_state={trading_state})"}
                })
                strategy.buy = None
                strategy.sell = None
                return False

            # Protections check (A-001)
            protection_manager = session.get("protection_manager")
            if protection_manager is not None:
                lock = protection_manager.check_entry(symbol, direction, session.get("capital", 0))
                if lock is not None:
                    logger.warning(f"[AlgoBot] {symbol}: entry blocked by protection: {lock.reason}")
                    await self._notifier.notify(self.session_id, {
                        "event": "log",
                        "eventData": {"type": "warning", "message": f"{symbol}: entry blocked — {lock.reason}"}
                    })
                    strategy.buy = None
                    strategy.sell = None
                    return False

            # Rate limiter check (A-003)
            rate_limiter = session.get("rate_limiter")
            if rate_limiter is not None and not rate_limiter.allow():
                logger.warning(f"[AlgoBot] {symbol}: order rate limited, skipping")
                await self._notifier.notify(self.session_id, {
                    "event": "log",
                    "eventData": {"type": "warning", "message": f"{symbol}: order rate limited, skipping"}
                })
                strategy.buy = None
                strategy.sell = None
                return False

            # Session Risk Governor pre-trade check (Plan 22 Step 22.1) —
            # aggregate session drawdown, daily realized loss limit, margin
            # utilization ceiling. Session-scoped (sees ALL symbols' state),
            # unlike the per-symbol risk models above/below this gate.
            risk_governor = session.get("risk_governor")
            if risk_governor is not None:
                _equity, _used_margin = self._reconciler.compute_session_equity_and_margin(session)
                verdict = risk_governor.check_pre_trade(
                    equity=_equity, used_margin=_used_margin, now=datetime.now(timezone.utc),
                )
                if not verdict.ok:
                    logger.warning(f"[AlgoBot] {symbol}: entry blocked by risk governor — {verdict.reason}")
                    await self._notifier.notify(self.session_id, {
                        "event": "log",
                        "eventData": {
                            "type": "warning",
                            "message": f"{symbol}: entry blocked — risk governor ({verdict.check_name}): {verdict.reason}",
                        },
                    })
                    strategy.buy = None
                    strategy.sell = None
                    return False

            # Plan 12 Step 1b: max concurrent open positions (session-level,
            # live/chaos only — mirrors freqtrade's max_open_trades). Skip
            # the entry this candle rather than queue it; the strategy
            # re-evaluates next candle. Deliberately session-orchestrator-
            # level, not in the five-model pipeline (kept per-symbol-pure).
            max_open_positions = session.get("max_open_positions")
            if (
                max_open_positions is not None
                and symbol not in session["open_positions"]
                and len(session["open_positions"]) >= max_open_positions
            ):
                logger.info(
                    f"[AlgoBot] {symbol}: entry skipped — session already at max_open_positions="
                    f"{max_open_positions} ({len(session['open_positions'])} open)"
                )
                strategy.buy = None
                strategy.sell = None
                return False

        fill_price = ref_price

        # Retrieve SL/TP values from strategy (updated by evaluate pipeline or exec_algo)
        sl_raw = strategy.stop_loss[1] if strategy.stop_loss else None
        tp_raw = strategy.take_profit[1] if strategy.take_profit else None
        sl_pct = abs(fill_price - sl_raw) / fill_price if sl_raw else None

        exchange_name = "Binance Futures"
        # Plan 22 Step 22.3: capture the pre-clamp qty so the risk_check event
        # below can record the same minNotional inflation factor A-11 already
        # logs (clamp_and_round_qty itself only returns the final qty, not
        # the multiplier — recomputed here from the before/after values
        # rather than changing that function's signature).
        _pre_clamp_qty = qty
        qty = clamp_and_round_qty(symbol, exchange_name, qty, fill_price, stop_loss_pct=sl_pct)
        _qty_inflation_factor = (qty / _pre_clamp_qty) if _pre_clamp_qty > 0 else 1.0

        # I-11: stop rounds away from entry; take-profit rounds away the other way
        # (using the stop's mode for TP biased it toward entry — easier to hit).
        sl_rounding = ROUND_DOWN if direction == "long" else ROUND_UP
        tp_rounding = ROUND_UP if direction == "long" else ROUND_DOWN
        sl_price = round_price(symbol, exchange_name, sl_raw, rounding=sl_rounding) if sl_raw else None
        tp_price = round_price(symbol, exchange_name, tp_raw, rounding=tp_rounding) if tp_raw else None

        if qty <= 0:
            logger.warning(f"[AlgoBot] Quantity rounded to 0 for {symbol} (below min lot size), skipping")
            strategy.buy = None
            strategy.sell = None
            return False

        notional = qty * fill_price
        max_allowed_notional = strategy.balance * strategy.leverage * 1.05
        if notional > max_allowed_notional:
            logger.warning(
                f"[AlgoBot] {symbol}: notional ${notional:.2f} exceeds leveraged buying power "
                f"${strategy.balance * strategy.leverage:.2f} (leverage {strategy.leverage}x) after min-notional bump, skipping"
            )
            await self._notifier.notify(self.session_id, {
                "event": "log",
                "eventData": {
                    "type": "error",
                    "message": f"Skipped {symbol}: notional ${notional:.2f} exceeds leveraged buying power ${strategy.balance * strategy.leverage:.2f}"
                }
            })
            strategy.buy = None
            strategy.sell = None
            return False

        # M-5 fix (Plan 21.4): a stop-loss that lands on the wrong side of
        # the reference price used to size it is a genuinely invalid
        # bracket, not a "nice to have we can skip" — the old behavior
        # dropped it (sl_price = None) and let the entry proceed anyway,
        # naked on the SL leg, with no re-check ever placing a stop later.
        # Industry pattern (freqtrade): do not enter without a valid stop.
        # Reject the entry outright instead, and clear the strategy's own
        # stop_loss/take_profit tuples so next candle's check_exits can't
        # read a stale, already-invalid stop as instantly triggered (the
        # second half of M-5 — "clear local state on drop").
        if sl_price is not None:
            if direction == "long" and sl_price >= fill_price:
                logger.warning(
                    f"[AlgoBot] {symbol}: SL {sl_price} >= entry ref {fill_price} — "
                    f"rejecting entry, no bracket-less entries (M-5)"
                )
                strategy.buy = None
                strategy.sell = None
                strategy.stop_loss = None
                strategy.take_profit = None
                return False
            elif direction == "short" and sl_price <= fill_price:
                logger.warning(
                    f"[AlgoBot] {symbol}: SL {sl_price} <= entry ref {fill_price} — "
                    f"rejecting entry, no bracket-less entries (M-5)"
                )
                strategy.buy = None
                strategy.sell = None
                strategy.stop_loss = None
                strategy.take_profit = None
                return False
        # TP invalid is lower-stakes (missed upside target, not a naked risk
        # exposure) — still drop-and-continue, but clear the local tuple too
        # so it can't be misread as an instantly-triggered stale target.
        if tp_price is not None:
            if direction == "long" and tp_price <= fill_price:
                logger.warning(f"[AlgoBot] {symbol}: TP {tp_price} <= entry {fill_price}, dropping TP")
                tp_price = None
                strategy.take_profit = None
            elif direction == "short" and tp_price >= fill_price:
                logger.warning(f"[AlgoBot] {symbol}: TP {tp_price} >= entry {fill_price}, dropping TP")
                tp_price = None
                strategy.take_profit = None

        # Plan 22 Step 22.2: portfolio open-risk budget + liquidation-buffer
        # veto. Placed here (not in the earlier pre-trade gate block) because
        # both need the finalized sl_price/qty this candle actually produced
        # — after clamp_and_round_qty and M-5's SL validity check, not the
        # pre-clamp values. Applies to DCA adds too (unconditional, like M-5
        # above) since a scale-in also changes committed risk/notional.
        risk_governor = session.get("risk_governor")
        if risk_governor is not None and sl_price is not None:
            _open_risk_breakdown = self._reconciler.compute_open_risk_breakdown(session)
            _candidate_risk = abs(fill_price - sl_price) * qty
            _equity_pr, _ = self._reconciler.compute_session_equity_and_margin(session)
            _pr_verdict = risk_governor.check_portfolio_risk(
                open_risk=sum(_open_risk_breakdown.values()) + _candidate_risk,
                equity=_equity_pr,
            )
            if not _pr_verdict.ok:
                _contributors = ", ".join(
                    f"{s}(${r:.2f})" for s, r in _open_risk_breakdown.items()
                ) or "none"
                logger.warning(
                    f"[AlgoBot] {symbol}: entry blocked by risk governor — {_pr_verdict.reason}; "
                    f"existing contributors: {_contributors}; candidate {symbol}(${_candidate_risk:.2f})"
                )
                await self._notifier.notify(self.session_id, {
                    "event": "log",
                    "eventData": {
                        "type": "warning",
                        "message": (
                            f"{symbol}: entry blocked — portfolio open-risk budget "
                            f"({_pr_verdict.reason}); contributors: {_contributors}"
                        ),
                    },
                })
                strategy.buy = None
                strategy.sell = None
                strategy.stop_loss = None
                strategy.take_profit = None
                return False

            # Liquidation-buffer guard (audit finding: respects_liq_buffer()
            # existed but had zero pipeline call sites — decorative). Computes
            # the actual liq price for the log itself rather than trusting
            # only the bool, per this step's acceptance criterion.
            try:
                from core.margin import liquidation_price as _liq_price_fn, initial_margin as _im_fn
                _liq_margin = _im_fn(qty * fill_price, strategy.leverage)
                _liq_price = _liq_price_fn(direction, qty, fill_price, _liq_margin)
                _liq_respected = strategy.risk_model.respects_liq_buffer(
                    strategy, fill_price, sl_price, qty, strategy.leverage, direction,
                )
            except Exception as _liq_e:
                logger.warning(
                    f"[AlgoBot] {symbol}: liquidation-buffer check failed to compute, "
                    f"allowing entry — {_liq_e}"
                )
                _liq_respected = True
                _liq_price = None

            if not _liq_respected:
                logger.warning(
                    f"[AlgoBot] {symbol}: entry blocked — stop {sl_price} sits inside the "
                    f"liquidation buffer (computed liq price ${_liq_price:.4f}, direction={direction}, "
                    f"leverage={strategy.leverage}x)"
                )
                await self._notifier.notify(self.session_id, {
                    "event": "log",
                    "eventData": {
                        "type": "warning",
                        "message": (
                            f"{symbol}: entry blocked — stop too close to liquidation "
                            f"(computed liq≈${_liq_price:.4f})"
                        ),
                    },
                })
                strategy.buy = None
                strategy.sell = None
                strategy.stop_loss = None
                strategy.take_profit = None
                return False

        # Plan 22 Step 22.4: account-wide VaR/CVaR budget — opt-in (only
        # fetched/evaluated when the governor actually has var_limit_pct or
        # cvar_limit_pct configured, to avoid an extra Binance/TimescaleDB
        # round trip on every entry for sessions that never opted in). Same
        # `compute_var_cvar` the Zone 1 dashboard calls (`services/
        # portfolio_risk.py`), 10s/60s cached — see that module's docstring.
        # Fails OPEN on a fetch/compute exception (external network call,
        # same precedent as the liq-buffer check above); fails CLOSED only
        # on the governor's own equity<=0 case (see `check_var`'s docstring).
        if risk_governor is not None and (
            risk_governor.var_limit_pct is not None or risk_governor.cvar_limit_pct is not None
        ):
            try:
                from services.portfolio_risk import compute_var_cvar as _compute_var_cvar
                _var_amount, _cvar_amount = await _compute_var_cvar(
                    session.get("api_key", ""), session.get("api_secret", ""),
                    mode=session["exchange"].mode if session.get("exchange") else "testnet",
                )
                _equity_var, _ = self._reconciler.compute_session_equity_and_margin(session)
                _var_verdict = risk_governor.check_var(
                    var_amount=_var_amount, cvar_amount=_cvar_amount, equity=_equity_var,
                )
            except Exception as _var_e:
                logger.warning(
                    f"[AlgoBot] {symbol}: VaR/CVaR check failed to compute, allowing entry — {_var_e}"
                )
                _var_verdict = GovernorVerdict(ok=True)

            if not _var_verdict.ok:
                logger.warning(f"[AlgoBot] {symbol}: entry blocked by risk governor — {_var_verdict.reason}")
                await self._notifier.notify(self.session_id, {
                    "event": "log",
                    "eventData": {
                        "type": "warning",
                        "message": f"{symbol}: entry blocked — risk governor ({_var_verdict.check_name}): {_var_verdict.reason}",
                    },
                })
                strategy.buy = None
                strategy.sell = None
                strategy.stop_loss = None
                strategy.take_profit = None
                return False

        # Plan 22 Step 22.5: correlation-adjusted concentration cap — opt-in
        # (only fetched/evaluated when the governor has correlation_cap.rho
        # configured), same gating pattern as the VaR/CVaR block above. Fails
        # OPEN on a fetch/compute exception (external TimescaleDB call, same
        # precedent as the liq-buffer/VaR checks); fails CLOSED only on the
        # governor's own equity<=0 case.
        if risk_governor is not None and risk_governor.correlation_rho is not None:
            try:
                _open_notionals: dict[str, float] = {}
                for _sym, _strat in session.get("strategy_instances", {}).items():
                    if _sym == symbol:
                        continue
                    _pos = _strat.position
                    if _pos is not None and _pos.is_open:
                        _open_notionals[_sym] = abs(_pos.entry_price * _pos.qty)
                from services.portfolio_risk import fetch_correlation_matrix as _fetch_corr
                _corr_matrix = await _fetch_corr(list(_open_notionals.keys()) + [symbol])
                _equity_corr, _ = self._reconciler.compute_session_equity_and_margin(session)
                _corr_verdict = risk_governor.check_correlation_concentration(
                    candidate_symbol=symbol,
                    candidate_notional=qty * fill_price,
                    open_notionals=_open_notionals,
                    correlation_matrix=_corr_matrix,
                    equity=_equity_corr,
                )
            except Exception as _corr_e:
                logger.warning(
                    f"[AlgoBot] {symbol}: correlation concentration check failed to compute, "
                    f"allowing entry — {_corr_e}"
                )
                _corr_verdict = GovernorVerdict(ok=True)

            if not _corr_verdict.ok:
                logger.warning(f"[AlgoBot] {symbol}: entry blocked by risk governor — {_corr_verdict.reason}")
                await self._notifier.notify(self.session_id, {
                    "event": "log",
                    "eventData": {
                        "type": "warning",
                        "message": f"{symbol}: entry blocked — risk governor ({_corr_verdict.check_name}): {_corr_verdict.reason}",
                    },
                })
                strategy.buy = None
                strategy.sell = None
                strategy.stop_loss = None
                strategy.take_profit = None
                return False

        binance_side = "BUY" if direction == "long" else "SELL"
        sem = self._registry.order_semaphores.get(self.session_id)

        # ── F-019: Track placed algo order IDs for OUO peer-cancel ──
        _placed_algo_ids: dict[str, str | None] = {"sl": None, "tp": None}

        # DCA scale-in: skip SL/TP placement and use existing brackets
        if is_dca:
            try:
                _api_key = session.get("api_key", "")
                _api_secret = session.get("api_secret", "")
                if not _api_key or not _api_secret:
                    raise RuntimeError("Binance Testnet API credentials not configured")

                async with (sem if sem else contextlib.nullcontext()):
                    # Plan 5 Step 5.3 (ENG-10): deterministic id for future
                    # idempotent-retry support, matching the entry/exit
                    # paths' convention.
                    result = await self._order_router.place_market_order(
                        _api_key, _api_secret, symbol, binance_side, qty,
                        _make_client_id(self.session_id, symbol),
                        exchange=exchange,
                    )
                    fill_price = float(result.get("avgPrice", ref_price))
                    logger.info(
                        f"[AlgoBot] DCA add {direction}: {symbol} +{qty} @ {fill_price} "
                        f"orderId={result.get('orderId')}"
                    )

                strategy.position.add_qty(qty, fill_price)
                pos_info = session["open_positions"].get(symbol, {})
                old_qty = float(pos_info.get("qty", 0))
                new_qty = old_qty + qty
                new_price = (old_qty * float(pos_info.get("price", 0)) + qty * fill_price) / new_qty if old_qty > 0 else fill_price
                pos_info["qty"] = str(new_qty)
                pos_info["price"] = str(new_price)
                session["open_positions"][symbol] = pos_info

                try:
                    strategy.on_increased_position((qty, fill_price))
                except Exception as e:
                    logger.error(f"on_increased_position error: {e}")

                dca_seq = await append_event(
                    session_id=self.session_id,
                    symbol=symbol,
                    event_type="fill",
                    payload={"side": "add", "direction": direction, "qty": qty, "price": fill_price},
                    client_order_id=str(result.get("orderId")) if result.get("orderId") else None,
                )

                await self._notifier.notify(self.session_id, {
                    "pnl": str(round(session["pnl"], 2)),
                    "openPositions": list(session["open_positions"].keys()),
                    "status": "running",
                    "event": "position:adjust",
                    "eventData": {
                        "symbol": symbol,
                        "qty": str(new_qty),
                        "price": str(new_price),
                        "adjustQty": str(qty),
                        "adjustTag": adjust_tag,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                    "seq": dca_seq,
                })
                return True
            except Exception as e:
                logger.error(f"[AlgoBot] DCA add failed for {symbol}: {e}")
                return False

        try:
            # F-003: Place orders directly on Binance instead of routing
            # through the engine→Node→engine→Binance hop chain.
            _api_key = session.get("api_key", "")
            _api_secret = session.get("api_secret", "")
            if not _api_key or not _api_secret:
                raise RuntimeError("Binance Testnet API credentials not configured")

            order_id = None
            entry_client_order_id = _make_client_id(self.session_id, symbol)
            async with (sem if sem else contextlib.nullcontext()):
                # Step 1: Place the entry MARKET order.
                #
                # Plan 5 Step 5.3 (ENG-10): the entry order carries a
                # deterministic newClientOrderId so that if the placement
                # call itself times out or raises (ambiguous — the order
                # may have actually reached Binance), we query by that id
                # before concluding the entry failed. Without this, a
                # timed-out-but-actually-filled entry would report failure,
                # the strategy would retry next candle, and a second real
                # position could be opened — the exact duplication ENG-10
                # exists to prevent (mirrors 5.2's close-path re-query).
                try:
                    entry_result = await self._order_router.place_market_order(
                        _api_key, _api_secret, symbol, binance_side, qty, entry_client_order_id,
                        exchange=exchange,
                    )
                except Exception as entry_e:
                    logger.warning(
                        f"[AlgoBot] {symbol}: entry order call raised ({_binance_error_detail(entry_e)}) — "
                        f"querying by clientOrderId={entry_client_order_id} before concluding it failed"
                    )
                    _real_fill = await _query_real_fill_price(
                        _api_key, _api_secret, symbol, entry_client_order_id, exchange=exchange,
                    )
                    if _real_fill is None:
                        raise
                    logger.warning(
                        f"[AlgoBot] {symbol}: entry order actually filled despite the raised exception "
                        f"@ {_real_fill} — proceeding as a successful entry, NOT retrying (would double-enter)"
                    )
                    entry_result = {"avgPrice": str(_real_fill)}
                order_id = entry_result.get("orderId")
                # F7 hardening: the old `if entry_result.get("avgPrice"):` check
                # treated any non-empty string as a real fill, including the
                # literal "0.00000000" Binance returns when a market order's
                # RESULT response lands before avgPrice settles (or the order
                # genuinely filled for zero — e.g. EXPIRED on a low-liquidity
                # symbol). `float("0.00000000")` == 0.0 is falsy-looking but the
                # *string* is truthy, so this silently kept fill_price == ref_price
                # (a pre-trade candle-close estimate) and opened a local Position
                # anyway — a phantom/mispriced position never confirmed against a
                # real Binance fill. Mirrors the ENG-2 contract already applied to
                # every close path (confirm_fill + re-query, never a silent
                # estimate fallback) but which the entry path never got.
                _confirmed_fill = await self._order_router.confirm_fill(
                    entry_result, _api_key, _api_secret, symbol, entry_client_order_id,
                    exchange=exchange,
                )
                if _confirmed_fill is None:
                    logger.error(
                        f"[AlgoBot] {symbol}: entry order {order_id} returned no confirmed "
                        f"fill price (avgPrice={entry_result.get('avgPrice')!r}, "
                        f"status={entry_result.get('status')!r}) — treating as a failed entry, "
                        f"NOT opening a local position on an unconfirmed fill"
                    )
                    await self._notifier.notify(self.session_id, {
                        "event": "log",
                        "eventData": {
                            "type": "error",
                            "message": f"{symbol}: entry unconfirmed — no fill price from Binance, position not opened",
                        },
                    })
                    strategy.buy = None
                    strategy.sell = None
                    return False
                fill_price = _confirmed_fill
                logger.info(
                    f"[AlgoBot] Testnet {direction} entry filled: {symbol} qty={qty} "
                    f"@ {fill_price} orderId={order_id} "
                    f"clientOrderId={entry_client_order_id}"
                )

                # A-14 fix (Plan 21.7): log slippage between the closed-candle
                # ref_price used to size/route the entry and the real fill —
                # previously never measured at all. ref_price > 0 always holds
                # here (a candle close price); guarded anyway to never let
                # logging raise into the entry path.
                if ref_price and ref_price > 0:
                    _slippage_pct = abs(fill_price - ref_price) / ref_price
                    if _slippage_pct >= _SLIPPAGE_ALERT_THRESHOLD_PCT:
                        logger.warning(
                            f"[AlgoBot] {symbol}: entry slippage {_slippage_pct * 100:.2f}% "
                            f"(ref={ref_price}, fill={fill_price}) exceeds "
                            f"{_SLIPPAGE_ALERT_THRESHOLD_PCT * 100:.0f}% alert threshold"
                        )
                        await self._notifier.notify(self.session_id, {
                            "event": "log",
                            "eventData": {
                                "type": "warning",
                                "message": (
                                    f"{symbol}: entry slippage {_slippage_pct * 100:.2f}% "
                                    f"(ref ${ref_price} -> fill ${fill_price})"
                                ),
                            },
                        })
                    else:
                        logger.info(
                            f"[AlgoBot] {symbol}: entry slippage {_slippage_pct * 100:.3f}% "
                            f"(ref={ref_price}, fill={fill_price})"
                        )

                # Step 2: Best-effort SL/TP placement (orders placed directly,
                # no separate hop).  Failure here does not revert the entry.
                close_side = "SELL" if binance_side == "BUY" else "BUY"
                tpsl_prefix = f"tpsl_{uuid4_hex8()}_"

                if sl_price is not None:
                    try:
                        sl_result = await self._order_router.place_algo_order(
                            _api_key, _api_secret, symbol, close_side, "STOP_MARKET",
                            sl_price, f"{tpsl_prefix}sl", exchange=exchange,
                        )
                        logger.info(f"[AlgoBot] SL placed for {symbol}: algoId={sl_result.get('algoId')}")
                        # Track algo order ID for OUO peer-cancel (F-019)
                        _placed_algo_ids["sl"] = sl_result.get("algoId")
                    except Exception as sl_e:
                        logger.warning(f"[AlgoBot] SL placement failed for {symbol}: {_binance_error_detail(sl_e)}")
                        # ── F-018: Emergency market exit ────────────────────
                        # Entry filled but SL placement failed → position is
                        # naked. Force-close at market immediately.
                        #
                        # A-6 fix (Plan 21.4): this used to (1) always book
                        # the trade at exit_price=fill_price (the ENTRY
                        # price, fabricating exactly -fee as PnL, regardless
                        # of what the emergency close actually filled at —
                        # violated Plan 5.2's real-fills-not-fabricated-
                        # closes invariant, which execute_exit already
                        # honors) and (2) on a FAILED emergency close, still
                        # recorded the position as closed and returned —
                        # leaving Binance holding a real, naked position
                        # while the engine believed it was flat, with no
                        # retry and no loud alert. Now: retry the emergency
                        # close up to 3x with backoff; on eventual success,
                        # book the REAL fill price (same _extract_fill_price
                        # -> _query_real_fill_price ladder as execute_exit);
                        # on total failure, record NOTHING (mirrors 5.2's
                        # execute_exit contract) and leave strategy.position
                        # untouched (still None here) — the very next
                        # per-symbol reconcile pass's Case 1 will discover
                        # the real Binance position and restore full local
                        # state properly (leverage, algo_ids from whatever's
                        # actually open), which is more correct than
                        # hand-assembling a rough Position object in this
                        # failure branch. A-7 extends reconcile to also
                        # re-arm a missing stop on a restored naked position.
                        _emergency_client_id = _make_client_id(self.session_id, symbol, "_emrg")
                        _close_side = "SELL" if binance_side == "BUY" else "BUY"
                        _emergency_result = None
                        _emergency_last_error: Exception | None = None
                        _EMERGENCY_CLOSE_ATTEMPTS = 3
                        for _attempt in range(1, _EMERGENCY_CLOSE_ATTEMPTS + 1):
                            try:
                                _emergency_result = await self._order_router.place_market_order(
                                    _api_key, _api_secret, symbol, _close_side, qty,
                                    _emergency_client_id, reduce_only=True, exchange=exchange,
                                )
                                logger.warning(
                                    f"[AlgoBot] {symbol}: emergency MARKET close sent "
                                    f"(SL placement failed) — attempt {_attempt}/{_EMERGENCY_CLOSE_ATTEMPTS}"
                                )
                                break
                            except Exception as _close_e:
                                _emergency_last_error = _close_e
                                logger.error(
                                    f"[AlgoBot] {symbol}: emergency MARKET close attempt "
                                    f"{_attempt}/{_EMERGENCY_CLOSE_ATTEMPTS} FAILED: "
                                    f"{_binance_error_detail(_close_e)}"
                                )
                                if _attempt < _EMERGENCY_CLOSE_ATTEMPTS:
                                    await asyncio.sleep(_attempt * 1.0)

                        # A-4 fix (Plan 21.3): defensive bracket cleanup. In
                        # today's placement order (SL attempted before TP)
                        # nothing should actually be resting here — this SL
                        # failure fires before TP is ever attempted below —
                        # but cancel-all is cheap and correct even if that
                        # ordering ever changes, so call it unconditionally
                        # rather than assuming the ordering invariant holds.
                        await self._reconciler.cancel_symbol_algo_orders(session, symbol, _placed_algo_ids)

                        if _emergency_result is None:
                            # All attempts failed. Do NOT fabricate a close —
                            # leave strategy.position as-is (still None at
                            # this point in execute_entry) and alert loudly.
                            # Binance is holding a real, naked position; the
                            # next reconcile pass is responsible for finding
                            # and restoring it.
                            logger.error(
                                f"[AlgoBot] {symbol}: CRITICAL — emergency close FAILED after "
                                f"{_EMERGENCY_CLOSE_ATTEMPTS} attempts. Position is OPEN and "
                                f"UNPROTECTED on Binance (last error: "
                                f"{_binance_error_detail(_emergency_last_error) if _emergency_last_error else 'unknown'}). "
                                f"Reconciliation will restore it next candle."
                            )
                            await self._notifier.notify(self.session_id, {
                                "event": "log",
                                "eventData": {
                                    "type": "error",
                                    "message": (
                                        f"{symbol}: CRITICAL — SL placement failed AND the emergency "
                                        f"close failed {_EMERGENCY_CLOSE_ATTEMPTS}x. Position is OPEN "
                                        f"and UNPROTECTED on Binance. Will self-heal via reconciliation "
                                        f"next candle, but check this symbol now."
                                    ),
                                },
                            })
                            strategy.buy = None
                            strategy.sell = None
                            return False

                        # Emergency close succeeded (possibly after retrying)
                        # — book the REAL fill price, not the entry price.
                        _real_exit_price = await self._order_router.confirm_fill(
                            _emergency_result, _api_key, _api_secret, symbol, _emergency_client_id,
                            exchange=exchange,
                        )
                        if _real_exit_price is None:
                            logger.error(
                                f"[AlgoBot] {symbol}: emergency close accepted but no real fill "
                                f"price found — booking with the entry-price estimate ${fill_price} "
                                f"as a last resort, flagged for reconciliation"
                            )
                            _real_exit_price = fill_price

                        # Record the trade locally with emergency_exit reason
                        _pos_e = Position(direction, qty, fill_price)
                        _fee_e = strategy.execution_model.exit_fee(strategy, _pos_e.qty, _real_exit_price)
                        _pos_e.close(_real_exit_price)
                        _rpnl_e = _pos_e.pnl - _fee_e
                        strategy.balance = add_money(strategy.balance, _rpnl_e)
                        session["pnl"] = add_money(session["pnl"], _rpnl_e)
                        if session.get("risk_governor") is not None:
                            session["risk_governor"].record_realized_pnl(_rpnl_e, datetime.now(timezone.utc))
                        # Plan 22 Step 22.3: protections (A-001) need every real
                        # close, not just the strategy-driven execute_exit path —
                        # otherwise StoplossGuard/CooldownPeriod/MaxDrawdown never
                        # see an emergency-exit stoploss at all.
                        _protection_manager_e = session.get("protection_manager")
                        if _protection_manager_e is not None:
                            _protection_manager_e.record_trade_close(
                                pair=symbol, side=direction, exit_reason="emergency_exit",
                                profit=_rpnl_e, close_timestamp=datetime.now(timezone.utc).timestamp(),
                            )
                        _tr = build_trade_record(
                            source="bot",
                            executed_by=session.get("strategy_name", "unknown"),
                            symbol=symbol,
                            side=direction,
                            qty=str(qty),
                            entry_price=str(fill_price),
                            exit_price=str(_real_exit_price),
                            sl_order_price=str(sl_price),
                            tp_order_price=None,
                            margin=str(_pos_e.margin) if _pos_e.margin else None,
                            liquidation_price=str(_pos_e.liquidation_price) if _pos_e.liquidation_price else None,
                            leverage=_pos_e.leverage if _pos_e.leverage else None,
                            net_pnl=str(round(_rpnl_e, 2)),
                            pnl_pct=str(round(_pos_e.pnl_pct, 2)) if _pos_e.pnl_pct else None,
                            fee=str(round(_fee_e, 2)) if _fee_e else None,
                            exit_reason="emergency_exit",
                            user_id=session.get("user_id", ""),
                            session_id=self.session_id,
                            strategy_name=session.get("strategy_name"),
                            entry_time=datetime.now(timezone.utc),
                            exit_time=datetime.now(timezone.utc),
                        )
                        await record_trade(_tr)
                        await append_event(
                            session_id=self.session_id, symbol=symbol, event_type="fill",
                            payload={"side": "entry", "direction": direction, "qty": qty, "price": fill_price},
                        )
                        _emergency_seq = await append_event(
                            session_id=self.session_id, symbol=symbol, event_type="fill",
                            payload={"side": "exit", "qty": qty, "price": _real_exit_price, "realizedPnl": _rpnl_e, "reason": "emergency_exit"},
                        )
                        await self._notifier.notify(self.session_id, {
                            "pnl": str(round(session["pnl"], 2)),
                            "openPositions": list(session["open_positions"].keys()),
                            "status": "running",
                            "seq": _emergency_seq,
                            "event": "position:close",
                            "eventData": {
                                "symbol": symbol,
                                "pnl": str(round(_rpnl_e, 2)),
                                "exitPrice": str(_real_exit_price),
                                "exitReason": "emergency_exit",
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            },
                        })
                        logger.warning(f"[AlgoBot] {symbol}: emergency exit complete — PnL={_rpnl_e:.2f}")
                        strategy.buy = None
                        strategy.sell = None
                        return False

                if tp_price is not None:
                    try:
                        tp_result = await self._order_router.place_algo_order(
                            _api_key, _api_secret, symbol, close_side, "TAKE_PROFIT_MARKET",
                            tp_price, f"{tpsl_prefix}tp", exchange=exchange,
                        )
                        logger.info(f"[AlgoBot] TP placed for {symbol}: algoId={tp_result.get('algoId')}")
                        _placed_algo_ids["tp"] = tp_result.get("algoId")
                    except Exception as tp_e:
                        _tp_detail = _binance_error_detail(tp_e)
                        logger.warning(f"[AlgoBot] TP placement failed for {symbol}: {_tp_detail}")
                        await self._notifier.notify(self.session_id, {
                            "event": "log",
                            "eventData": {"type": "warning", "message": f"{symbol}: TP skipped — {_tp_detail}"},
                        })

        except Exception as e:
            _order_detail = _binance_error_detail(e)
            logger.error(f"[AlgoBot] Testnet order failed for {symbol}: {_order_detail}")
            await self._notifier.notify(self.session_id, {
                "event": "log",
                "eventData": {"type": "error", "message": f"Order failed {symbol}: {_order_detail}"}
            })
            strategy.buy = None
            strategy.sell = None
            return False

        strategy.position = Position(direction, qty, fill_price)
        if direction == "long":
            strategy.buy = None
        else:
            strategy.sell = None

        pos_info = {
            "symbol": symbol,
            "side": direction,
            "qty": str(qty),
            "price": str(fill_price),
            "leverage": strategy.leverage,
            "algo_ids": _placed_algo_ids,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        session["open_positions"][symbol] = pos_info

        seq = await append_event(
            session_id=self.session_id,
            symbol=symbol,
            event_type="fill",
            payload={"side": "entry", "direction": direction, "qty": qty, "price": fill_price},
            client_order_id=str(order_id) if order_id else None,
        )

        # Plan 22 Step 22.3: risk snapshot on every entry — resolved limits,
        # computed sizing, and any minNotional resize (B-9's inflation
        # factor, same computation A-11 already logs engine-side, recorded
        # here as a queryable event too rather than log-only).
        await append_event(
            session_id=self.session_id,
            symbol=symbol,
            event_type="risk_check",
            payload={
                "resolved_limits": {
                    "risk_pct": getattr(strategy, "risk_pct", None),
                    "rrr": getattr(strategy, "rrr", None),
                    "max_session_dd": getattr(strategy, "max_session_dd", None),
                    "max_portfolio_risk": getattr(strategy, "max_portfolio_risk", None),
                    "liq_buffer_pct": getattr(strategy, "liq_buffer_pct", None),
                    "leverage": strategy.leverage,
                },
                "computed": {
                    "direction": direction,
                    "pre_clamp_qty": _pre_clamp_qty,
                    "final_qty": qty,
                    "qty_inflation_factor": round(_qty_inflation_factor, 4),
                    "entry_price": fill_price,
                    "sl_price": sl_price,
                    "tp_price": tp_price,
                    "notional": notional,
                },
            },
            client_order_id=str(order_id) if order_id else None,
        )
        # Distinct from A-11's always-on engine log (any inflation >0.1%) —
        # this is a session-visible warning specifically at the 1.1x
        # threshold this step's acceptance criterion names, so a user
        # actually sees it in the UI, not just the engine log.
        if _qty_inflation_factor > 1.1:
            await self._notifier.notify(self.session_id, {
                "event": "log",
                "eventData": {
                    "type": "warning",
                    "message": (
                        f"{symbol}: realized risk is {_qty_inflation_factor:.2f}x the intended size "
                        f"(minNotional bump {_pre_clamp_qty:.8f} -> {qty:.8f}) — exceeds the 1.1x watch threshold"
                    ),
                },
            })

        await self._notifier.notify(self.session_id, {
            "pnl": str(round(session["pnl"], 2)),
            "openPositions": list(session["open_positions"].keys()),
            "status": "running",
            "event": "position:open",
            "eventData": pos_info,
            "seq": seq,
        })

        logger.info(f"[AlgoBot] Testnet {direction} filled: {symbol} qty={qty} @ {fill_price}")
        return True

    async def execute_reduce(
        self, strategy, symbol: str, qty: float, exit_price: float,
        time_t: datetime, index_t: int, adjust_tag: str = "",
    ) -> None:
        session = self._registry.sessions.get(self.session_id)
        if not session or strategy.position is None or not strategy.position.is_open:
            return
        if qty <= 0 or qty >= strategy.position.qty:
            return
        exchange = session.get("exchange") or BinanceFuturesTestnet()

        # Plan 5 Step 5.3 / Plan 20 (ENG-10): floor the reduce qty to the
        # symbol's stepSize before sending it to Binance. Unlike every other
        # order-placement path in this file, execute_reduce previously sent
        # the raw strategy-computed delta straight through `_fmt_num()`,
        # which knows nothing about stepSize — a live rejection risk
        # (-4023/-1111) the moment a strategy's adjust_trade_position()
        # returns a non-step-aligned quantity. reduce_only=True skips the
        # minNotional bump (Binance doesn't check notional on reduceOnly
        # orders — error -4164's own message says so).
        qty = clamp_and_round_qty(symbol, "Binance Futures", qty, exit_price, reduce_only=True)
        if qty <= 0 or qty >= strategy.position.qty:
            logger.warning(
                f"[AlgoBot] {symbol}: DCA reduce qty clamped to {qty} (stepSize floor), "
                f"no longer a valid partial reduce against position.qty={strategy.position.qty} — skipping"
            )
            return

        reduce_side = "SELL" if strategy.position.type == "long" else "BUY"
        # Plan 5 Step 5.3 (ENG-10) tail (F2): deterministic newClientOrderId,
        # matching the entry/exit/DCA-add paths' convention. No retry-on-
        # ambiguous-failure wrapper here (unlike execute_entry) — lowest
        # priority since this remains dead code today (no strategy overrides
        # adjust_trade_position() to trigger a scale-out); the id alone is
        # enough for a future reconciliation pass to find the order by client
        # id instead of guessing.
        reduce_client_order_id = _make_client_id(self.session_id, symbol)
        try:
            _api_key = session.get("api_key", "")
            _api_secret = session.get("api_secret", "")

            sem = self._registry.order_semaphores.get(self.session_id)
            async with (sem if sem else contextlib.nullcontext()):
                result = await self._order_router.place_market_order(
                    _api_key, _api_secret, symbol, reduce_side, qty,
                    reduce_client_order_id, reduce_only=True, exchange=exchange,
                )
                fill_price = float(result.get("avgPrice", exit_price))
                logger.info(
                    f"[AlgoBot] DCA reduce {strategy.position.type}: {symbol} -{qty} @ {fill_price} "
                    f"orderId={result.get('orderId')} clientOrderId={reduce_client_order_id}"
                )

            realized_pnl = strategy.position.reduce_qty(qty, fill_price)
            fee = strategy.execution_model.exit_fee(strategy, qty, fill_price)
            realized_pnl -= fee

            pos_info = session["open_positions"].get(symbol, {})
            new_qty = strategy.position.qty
            pos_info["qty"] = str(new_qty)
            session["open_positions"][symbol] = pos_info

            _tr = build_trade_record(
                source="bot",
                executed_by=session.get("strategy_name", "unknown"),
                symbol=symbol,
                side=strategy.position.type,
                qty=str(qty),
                entry_price=str(pos_info.get("price", "0")),
                exit_price=str(fill_price),
                sl_order_price=None,
                tp_order_price=None,
                margin=None,
                liquidation_price=None,
                leverage=strategy.leverage,
                net_pnl=str(round(realized_pnl, 2)),
                pnl_pct=None,
                fee=str(round(fee, 2)) if fee else None,
                exit_reason="scale_out",
                user_id=session.get("user_id", ""),
                session_id=self.session_id,
                strategy_name=session.get("strategy_name"),
                entry_time=datetime.now(timezone.utc),
                exit_time=datetime.now(timezone.utc),
                entry_tag=adjust_tag or "",
                exit_tag="",
            )
            await record_trade(_tr)

            try:
                strategy.on_reduced_position((qty, fill_price))
            except Exception as e:
                logger.error(f"on_reduced_position error: {e}")

            await self._notifier.notify(self.session_id, {
                "pnl": str(round(session["pnl"], 2)),
                "openPositions": list(session["open_positions"].keys()),
                "status": "running",
                "event": "position:adjust",
                "eventData": {
                    "symbol": symbol,
                    "qty": str(new_qty),
                    "reduceQty": str(qty),
                    "exitPrice": str(fill_price),
                    "adjustTag": adjust_tag,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            })
        except Exception as e:
            logger.error(f"[AlgoBot] DCA reduce failed for {symbol}: {e}")

    async def execute_exit(
        self, strategy, symbol: str, qty: float, exit_price: float, reason: str, time_t: datetime, index_t: int,
        high_t: float, low_t: float
    ) -> None:
        session = self._registry.sessions.get(self.session_id)
        if not session or strategy.position is None:
            return
        exchange = session.get("exchange") or BinanceFuturesTestnet()

        pos = strategy.position
        sl_price = strategy.stop_loss[1] if strategy.stop_loss else None
        tp_price = strategy.take_profit[1] if strategy.take_profit else None
        entry_time_str = session["open_positions"].get(symbol, {}).get("timestamp")
        entry_time = datetime.fromisoformat(entry_time_str.replace("Z", "+00:00")) if entry_time_str else datetime.now(timezone.utc)
        executed_by = session.get("strategy_name", "unknown")
        exit_time = datetime.now(timezone.utc)

        # Rate limiter check (A-003)
        rate_limiter = session.get("rate_limiter")
        if rate_limiter is not None and not rate_limiter.allow():
            logger.warning(f"[AlgoBot] {symbol}: exit rate limited, proceeding anyway")

        # F-003: Close position directly on Binance instead of routing
        # through Node.  Determines position side and sends a reduceOnly
        # MARKET order.
        #
        # Plan 5 Step 5.2 (ENG-2): the exchange is the source of truth for
        # whether this position actually closed and at what price.
        # - On any failure placing/confirming the close, we `return` before
        #   touching local position/PnL state — the position stays open and
        #   reconciliation is responsible for it, instead of silently
        #   fabricating a close event.
        # - On success, `exit_price` is overwritten with the REAL avgPrice
        #   from the fill (falling back to a direct order query if the
        #   immediate response didn't carry it) instead of the SL/TP
        #   trigger price / last candle close this function was called with.
        sem = self._registry.order_semaphores.get(self.session_id)
        client_order_id = _make_client_id(self.session_id, symbol)
        try:
            _api_key = session.get("api_key", "")
            _api_secret = session.get("api_secret", "")
            if not _api_key or not _api_secret:
                raise RuntimeError("Binance Testnet API credentials not configured")

            close_side = "SELL" if strategy.is_long else "BUY"
            async with (sem if sem else contextlib.nullcontext()):
                order_result = await self._order_router.place_market_order(
                    _api_key, _api_secret, symbol, close_side, abs(pos.qty),
                    client_order_id, reduce_only=True, exchange=exchange,
                )
            real_fill_price = await self._order_router.confirm_fill(
                order_result, _api_key, _api_secret, symbol, client_order_id,
                exchange=exchange,
            )
            if real_fill_price is None:
                # The order was accepted (no exception above) but no fill price
                # is discoverable — extremely unlikely for a MARKET order, but
                # fail loud rather than silently trusting the trigger estimate.
                logger.error(
                    f"[AlgoBot] {symbol}: close order {order_result.get('orderId')} accepted but no fill "
                    f"price found — booking with the trigger-price estimate ${exit_price}, flagged for reconciliation"
                )
            else:
                exit_price = real_fill_price
            logger.info(f"[AlgoBot] Testnet close-position filled for {symbol} reason={reason} @ {exit_price}")
        except Exception as e:
            logger.error(
                f"[AlgoBot] Testnet close-position FAILED for {symbol}: {e} — "
                f"position stays open locally, NOT booking a fabricated close"
            )
            await append_event(
                session_id=self.session_id, symbol=symbol, event_type="close_failed",
                payload={"reason": reason, "error": str(e)},
                client_order_id=client_order_id,
            )
            await self._notifier.notify(self.session_id, {
                "status": "running",
                "event": "close_failed",
                "eventData": {
                    "symbol": symbol,
                    "reason": reason,
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            })
            return

        fee = strategy.execution_model.exit_fee(strategy, pos.qty, exit_price)
        pos.close(exit_price)
        realized_pnl = pos.pnl - fee
        strategy.balance = add_money(strategy.balance, realized_pnl)
        session["pnl"] = add_money(session["pnl"], realized_pnl)
        if session.get("risk_governor") is not None:
            session["risk_governor"].record_realized_pnl(realized_pnl, datetime.now(timezone.utc))

        # Record trade close in protections (A-001)
        protection_manager = session.get("protection_manager")
        if protection_manager is not None:
            protection_manager.record_trade_close(
                pair=symbol,
                side=pos.type,
                exit_reason=reason,
                profit=realized_pnl,
                close_timestamp=exit_time.timestamp(),
            )

        event_data = {
            "symbol": symbol,
            "pnl": str(round(realized_pnl, 2)),
            "exitPrice": str(exit_price),
            "exitReason": reason,
            "timestamp": exit_time.isoformat(),
        }

        trade_record = build_trade_record(
            source="bot",
            executed_by=executed_by,
            symbol=symbol,
            side=pos.type,
            qty=str(pos.qty),
            entry_price=str(pos.entry_price),
            exit_price=str(exit_price),
            sl_order_price=str(sl_price) if sl_price is not None else None,
            tp_order_price=str(tp_price) if tp_price is not None else None,
            margin=str(pos.margin) if pos.margin else None,
            liquidation_price=str(pos.liquidation_price) if pos.liquidation_price else None,
            leverage=pos.leverage if pos.leverage else None,
            net_pnl=str(round(realized_pnl, 2)),
            pnl_pct=str(round(pos.pnl_pct, 2)) if pos.pnl_pct else None,
            fee=str(round(fee, 2)) if fee else None,
            exit_reason=reason,
            user_id=session.get("user_id", ""),
            session_id=self.session_id,
            strategy_name=session.get("strategy_name"),
            entry_time=entry_time,
            exit_time=exit_time,
            entry_tag=strategy.entry_tag or "",
            exit_tag=strategy.exit_tag or "",
        )

        # A-4 fix (Plan 21.3): capture the tracked SL/TP algo ids before
        # dropping local position tracking, then cancel them — a
        # closePosition:"true" bracket left resting after this close would
        # market-close whatever position exists on this symbol later.
        _closed_algo_ids = (session["open_positions"].get(symbol) or {}).get("algo_ids")

        strategy.position = None
        strategy.stop_loss = None
        strategy.take_profit = None
        strategy._pending_flip = None
        session["open_positions"].pop(symbol, None)
        await self._reconciler.cancel_symbol_algo_orders(session, symbol, _closed_algo_ids)

        # Persist the trade record BEFORE notifying Node so the server's
        # per-symbol aggregation (computeSymbolStats) sees this closed trade.
        await record_trade(trade_record)

        exit_seq = await append_event(
            session_id=self.session_id, symbol=symbol, event_type="fill",
            payload={"side": "exit", "qty": pos.qty, "price": exit_price, "realizedPnl": realized_pnl, "reason": reason},
            client_order_id=client_order_id,
        )

        await self._notifier.notify(self.session_id, {
            "pnl": str(round(session["pnl"], 2)),
            "openPositions": list(session["open_positions"].keys()),
            "status": "running",
            "event": "position:close",
            "eventData": event_data,
            "seq": exit_seq,
        })

        logger.info(f"[AlgoBot] Position closed: {symbol} pnl={realized_pnl:.2f} reason={reason}")

    async def execute_flip(
        self, strategy, symbol: str, new_direction: str, new_qty: float, ref_price: float, time_t: datetime,
        index_t: int, high_t: float, low_t: float, stop_loss: float | None = None, take_profit: float | None = None
    ) -> bool:
        # Plan 5 Step 5.3 (ENG-10) tail (F2): execute_flip carries no
        # newClientOrderId of its own — verified sufficient (test_
        # execute_flip_idempotency.py) because it delegates the entire order
        # lifecycle to the two legs below, each already idempotent on its
        # own terms:
        #   - execute_exit: no-ops if strategy.position is already None (a
        #     retried flip after the exit leg already landed re-checks live
        #     state, not a client id, and simply skips re-closing); on a
        #     failure placing the close, it returns before mutating state and
        #     leaves the position open — this function then bails via the
        #     `strategy.position is not None` guard below, so a failed exit
        #     never reaches the entry leg.
        #   - execute_entry: generates its own fresh newClientOrderId per
        #     call and has its own query-by-id-before-retrying guard for an
        #     ambiguous (timeout-but-maybe-filled) failure.
        # A composed flip can therefore never double-close or double-enter;
        # the only observable failure modes are "stayed in the old position"
        # (exit failed) or "ended up flat" (exit ok, entry genuinely failed)
        # — both are safe, inert states for reconciliation to find.
        await self.execute_exit(
            strategy=strategy,
            symbol=symbol,
            qty=strategy.position.qty,
            exit_price=ref_price,
            reason="flip",
            time_t=time_t,
            index_t=index_t,
            high_t=high_t,
            low_t=low_t,
        )
        if strategy.position is not None:
            return False

        if new_qty <= 0:
            return False

        strategy.stop_loss = (new_qty, stop_loss) if stop_loss is not None else None
        strategy.take_profit = (new_qty, take_profit) if take_profit is not None else None

        success = await self.execute_entry(
            strategy=strategy,
            symbol=symbol,
            direction=new_direction,
            qty=new_qty,
            ref_price=ref_price,
            time_t=time_t,
            index_t=index_t,
        )
        return success


class LiveBotManager:
    def __init__(self):
        self._registry = SessionRegistry()
        self._market_data = MarketDataFeed()
        self._notifier = NodeNotifier()
        self._reconciler = Reconciler(self._registry, self._notifier, self)

    # Thin delegating properties (Plan 6 Step 6.1, ENG-1): session lifecycle
    # state now lives in `SessionRegistry`, but every existing call site
    # (this file's own methods, `LiveAdapter.manager.sessions`/
    # `.manager._order_semaphores`, and tests that poke `mgr.sessions[...]`
    # directly) keeps working unchanged — same dict objects, just owned by
    # the registry instead of `LiveBotManager` itself.
    @property
    def sessions(self) -> dict[str, dict]:
        return self._registry.sessions

    @property
    def _stop_signals(self) -> dict[str, asyncio.Event]:
        return self._registry.stop_signals

    @property
    def _tasks(self) -> dict[str, list[asyncio.Task]]:
        return self._registry.tasks

    @property
    def _order_semaphores(self) -> dict[str, asyncio.Semaphore]:
        return self._registry.order_semaphores

    @property
    def _symbol_state_locks(self) -> dict[tuple[str, str], asyncio.Lock]:
        return self._registry.symbol_state_locks

    def _get_symbol_lock(self, session_id: str, symbol: str) -> asyncio.Lock:
        return self._registry.get_symbol_lock(session_id, symbol)

    async def start_session(self, session_config: dict) -> None:
        """Start a new live bot session. session_config from Node."""
        session_id = session_config["session_id"]
        strategy_name = session_config["strategy_name"]
        symbols = session_config.get("symbols", [])
        timeframe = session_config["timeframe"]
        params = session_config.get("params", {})
        risk_params = session_config.get("risk_params", {}) or {}
        # `risk_params` as sent by Node is shaped `{symbol: {...}, ...,
        # "default": {...}}` (one `resolveStrategyRiskParams()` call per
        # symbol, see `server/src/controllers/algo.controller.js`) — NOT a
        # flat dict. Session-level (not per-symbol) config — the governor's
        # knobs, `allocation` — lives inside the "default" slice, the same
        # place `_setup_strategy_instance`'s `_risk = _risk_all.get(symbol)
        # or _risk_all.get("default")` already reads per-symbol risk from.
        # Found while wiring 22.7's Node cascade through: every governor_cfg
        # fallback below (`risk_params.get("max_session_dd")` etc.) had been
        # reading the wrong dict level since 22.1 and always fell through to
        # None, silently making every Zone-2-configured governor knob a
        # no-op in favor of the hardcoded default.
        default_risk_params = risk_params.get("default") or {}
        user_id = session_config.get("user_id", "")
        api_key = session_config.get("api_key", "")
        api_secret = session_config.get("api_secret", "")

        # Resolve pairlist pipeline if symbols not explicitly provided (A-004)
        pairlist_config = risk_params.get("pairlist")
        if not symbols and pairlist_config:
            pairlist_pipeline = pairlist_from_config(pairlist_config)
            symbols = pairlist_pipeline.run(exchange="Binance Futures")
            logger.info(
                f"[AlgoBot] Session {session_id}: pairlist generated {len(symbols)} symbols "
                f"({pairlist_pipeline})"
            )

        if not symbols:
            logger.error(f"[AlgoBot] Session {session_id}: no symbols provided and pairlist yielded none")
            await self._notifier.notify(session_id, {
                "event": "log",
                "eventData": {"type": "error", "message": "No symbols available for session"},
            })
            return

        # Plan 22 Step 22.1 (B-11 engine backstop): defensive capital-vs-wallet
        # clamp, independent of whatever the server-side gate did or didn't
        # catch. Best-effort — a failed balance fetch never blocks session
        # start (see `_fetch_available_balance`'s own docstring); this is the
        # backstop, not the primary UX (that's Node's startSession/startChaos).
        configured_capital = float(session_config["capital"])
        capital_to_use = configured_capital
        available_balance = await _fetch_available_balance(api_key, api_secret)
        if available_balance is not None and configured_capital > available_balance > 0:
            capital_to_use = available_balance
            logger.warning(
                f"[AlgoBot] Session {session_id}: configured capital ${configured_capital:.2f} "
                f"exceeds available balance ${available_balance:.2f} — clamping to the real "
                f"balance (server-side capital gate should have caught this; this is the backstop)"
            )
            await self._notifier.notify(session_id, {
                "event": "log",
                "eventData": {
                    "type": "warning",
                    "message": (
                        f"Configured capital ${configured_capital:.2f} exceeds available "
                        f"balance ${available_balance:.2f} — clamped to ${available_balance:.2f}"
                    ),
                },
            })

        # Cross-symbol capital split owned by the Portfolio Model (Phase 3).
        # Default is an equal split (byte-identical to the former
        # capital/len(symbols)); a custom PortfolioModel can re-weight here.
        # Plan 22 Step 22.6: opt-in inverse-volatility variant, config-gated
        # via risk_params["allocation"] == "inverse_vol" (default "equal").
        # Fetches recent close-price history via the shared
        # `services/portfolio_risk.fetch_close_prices` (60s-cached, same
        # service 22.4/22.5 already use) — a live session start is a
        # one-time cost, not a hot per-candle path, so the extra round trip
        # is acceptable. Falls back to equal split on any fetch failure
        # (InverseVolatilityPortfolio itself also degrades to equal-weight
        # when fewer than 2 symbols have a usable vol estimate).
        if default_risk_params.get("allocation") == "inverse_vol":
            try:
                from services.portfolio_risk import fetch_close_prices as _fetch_close_prices
                _price_histories = await _fetch_close_prices(symbols)
                _vols = compute_realized_volatility(_price_histories)
                allocation = InverseVolatilityPortfolio().allocate(
                    capital_to_use, symbols, volatilities=_vols,
                )
                logger.info(f"[AlgoBot] Session {session_id}: inverse_vol allocation: {allocation}")
            except Exception as _alloc_e:
                logger.warning(
                    f"[AlgoBot] Session {session_id}: inverse_vol allocation failed, "
                    f"falling back to equal split — {_alloc_e}"
                )
                allocation = DefaultPortfolioModel().allocate(capital_to_use, symbols)
        else:
            allocation = DefaultPortfolioModel().allocate(
                capital_to_use, symbols
            )
        leverage = int(session_config.get("leverage", 1))
        fee_rate = float(session_config.get("fee_rate", 0.0005))

        # Plan 6 Step 6.2 (ENG-4): resolve this session's Exchange ONCE here
        # instead of every call site hardcoding mode="testnet" — every order/
        # reconcile/user-data-stream call for this session routes through
        # this instance. Always BinanceFuturesTestnet() today: nothing in
        # session_config selects mainnet yet (BinanceFuturesMainnet is
        # constructible per Step 6.2's own scope, but enabling it is a
        # separate, deliberate product gate, not this step's call).
        session_exchange = BinanceFuturesTestnet()

        # Dynamic import of strategy class
        import importlib
        module = importlib.import_module(f"strategies.{strategy_name}")
        strategy_class = getattr(module, strategy_name)

        stop_event = asyncio.Event()
        self._stop_signals[session_id] = stop_event
        self._tasks[session_id] = []
        # Allow at most 2 concurrent Binance order calls per session
        self._order_semaphores[session_id] = asyncio.Semaphore(2)

        # Per-session user data stream with the user's own credentials
        uds = UserDataStreamManager(api_key=api_key, api_secret=api_secret, exchange=session_exchange)
        try:
            await uds.start()
            logger.info(f"[AlgoBot] Session {session_id}: user data stream started")
        except Exception as _uds_e:
            logger.warning(f"[AlgoBot] Session {session_id}: user data stream failed to start: {_uds_e}")

        # Setup protections stack (A-001) from risk_params config
        protection_manager = ProtectionManager()
        prot_cfg = risk_params.get("protections", {}) or {}
        cooldown_cfg = prot_cfg.get("cooldown_period", {})
        if cooldown_cfg.get("enabled", True):
            protection_manager.add(CooldownPeriod(cooldown_cfg))
        stoploss_cfg = prot_cfg.get("stoploss_guard", {})
        if stoploss_cfg.get("enabled", True):
            protection_manager.add(StoplossGuard(stoploss_cfg))
        # Plan 22 Step 22.3: opt-in (default False), unlike the two above —
        # both are new and MaxDrawdown specifically overlaps in spirit with
        # the Session Risk Governor's own aggregate-drawdown check (22.1;
        # see MaxDrawdownProtection's docstring for how they differ). Default
        # off avoids surprising an existing session/user with a second,
        # differently-tuned drawdown lockout they never opted into.
        max_dd_cfg = prot_cfg.get("max_drawdown", {})
        if max_dd_cfg.get("enabled", False):
            protection_manager.add(MaxDrawdownProtection(max_dd_cfg))
        low_profit_cfg = prot_cfg.get("low_profit_pairs", {})
        if low_profit_cfg.get("enabled", False):
            protection_manager.add(LowProfitPairsProtection(low_profit_cfg))

        # Order rate limiter (A-003): default 10 req/s per session
        rate_limit_cfg = risk_params.get("rate_limiting", {}) or {}
        rate_limiter = OrderRateLimiter(
            max_rate=int(rate_limit_cfg.get("max_rate", 10)),
            window_seconds=int(rate_limit_cfg.get("window_seconds", 1)),
        )

        # Session Risk Governor (Plan 22 Step 22.1): reuse the existing
        # top-level `max_session_dd` knob (already resolved through the Zone 2
        # cascade server-side, same as the per-symbol strategy clamp above at
        # line ~1555) as the governor's default; a `risk_params.governor`
        # sub-object can override it plus set the governor-only keys
        # (max_daily_loss_pct, max_margin_utilization, breach_action,
        # auto_flatten_on_halt). Full Zone 2 UI/schema wiring is 22.7's scope.
        # Plan 22 Step 22.2: `max_portfolio_risk` is reused the same way —
        # it's the SAME field name `core/models/portfolio.py` already resolves
        # per-symbol (config compat, per the plan's own wording), just also
        # handed to the governor here for the true cross-symbol check.
        governor_cfg = dict(default_risk_params.get("governor", {}) or {})
        if "max_session_dd" not in governor_cfg and default_risk_params.get("max_session_dd") is not None:
            governor_cfg["max_session_dd"] = default_risk_params.get("max_session_dd")
        if "max_portfolio_risk" not in governor_cfg and default_risk_params.get("max_portfolio_risk") is not None:
            governor_cfg["max_portfolio_risk"] = default_risk_params.get("max_portfolio_risk")
        # Plan 22 Step 22.4: varLimitPct/cvarLimitPct — same reuse pattern as
        # max_session_dd/max_portfolio_risk above.
        if "var_limit_pct" not in governor_cfg and default_risk_params.get("var_limit_pct") is not None:
            governor_cfg["var_limit_pct"] = default_risk_params.get("var_limit_pct")
        if "cvar_limit_pct" not in governor_cfg and default_risk_params.get("cvar_limit_pct") is not None:
            governor_cfg["cvar_limit_pct"] = default_risk_params.get("cvar_limit_pct")
        # Plan 22 Step 22.5: correlation_cap — same reuse pattern; the whole
        # sub-dict ({"rho": ..., "max_cluster_exposure_pct": ...}) is passed
        # through as-is, not flattened, since the governor reads it as a dict.
        if "correlation_cap" not in governor_cfg and default_risk_params.get("correlation_cap") is not None:
            governor_cfg["correlation_cap"] = default_risk_params.get("correlation_cap")
        # Plan 22 Step 22.7: the remaining governor-only keys, sent by Zone 2's
        # UI as top-level fields in `resolveStrategyRiskParams()`'s output —
        # same reuse pattern as every field above.
        for _flat_key in ("max_daily_loss_pct", "max_margin_utilization", "breach_action", "auto_flatten_on_halt"):
            if _flat_key not in governor_cfg and default_risk_params.get(_flat_key) is not None:
                governor_cfg[_flat_key] = default_risk_params.get(_flat_key)
        risk_governor = SessionRiskGovernor(governor_cfg)

        self.sessions[session_id] = {
            "session_id": session_id,
            "user_id": user_id,
            "api_key": api_key,
            "api_secret": api_secret,
            "exchange": session_exchange,
            "uds": uds,
            "strategy_name": strategy_name,
            "symbols": symbols,
            "timeframe": timeframe,
            "params": params,
            "capital": capital_to_use,
            "leverage": leverage,
            "risk_params": risk_params,
            "status": "running",
            "pnl": 0.0,
            "trading_state": "active",  # A-002: active/reducing/halted
            "protection_manager": protection_manager,  # A-001
            "rate_limiter": rate_limiter,  # A-003
            "risk_governor": risk_governor,  # Plan 22 Step 22.1
            # Plan 12 Step 1b: session-level cap on concurrent open symbols
            # (live/chaos multi-symbol only). None = unlimited (default,
            # byte-identical to pre-Plan-12 behavior).
            "max_open_positions": (
                int(session_config["max_open_positions"])
                if session_config.get("max_open_positions") not in (None, "")
                else None
            ),
            "open_positions": {},  # symbol -> dict with position info
            "strategy_instances": {},  # symbol -> strategy instance
        }

        # Plan 5 Step 5.6 (ENG-7): resume seeds pnl from this session's own
        # event log instead of starting at 0.0 — see `_seed_pnl_from_event_log`.
        # Currently-open positions need no equivalent seeding here: each
        # symbol's first candle loop iteration restores them from the exchange
        # via the existing `_reconcile_exchange_state` Case 1.
        if session_config.get("resume"):
            recovered_pnl = await _seed_pnl_from_event_log(session_id, symbols)
            self.sessions[session_id]["pnl"] = recovered_pnl
            logger.info(
                f"[AlgoBot] Session {session_id}: resumed — seeded pnl=${recovered_pnl:.2f} "
                f"from event log; open positions self-heal via exchange reconcile on first candle"
            )

        # Spawn one task per symbol
        for symbol in symbols:
            task = asyncio.create_task(
                self._run_symbol_loop(
                    session_id, strategy_class, symbol, params,
                    timeframe, allocation[symbol], leverage, fee_rate,
                    risk_params,
                )
            )
            self._tasks[session_id].append(task)

        # Notify Node that session is now running
        await self._notifier.notify(session_id, {
            "pnl": "0",
            "openPositions": [],
            "status": "running",
        })

        logger.info(f"[AlgoBot] Session {session_id} started with {len(symbols)} symbols")

    async def stop_session(self, session_id: str) -> None:
        """Stop a running session. Called from the FastAPI route via BackgroundTasks."""
        session = self.sessions.get(session_id)
        if not session:
            return

        logger.info(f"[AlgoBot] Stopping session {session_id}")
        session["status"] = "stopping"

        # Signal all loops to stop
        stop_event = self._stop_signals.get(session_id)
        if stop_event:
            stop_event.set()

        # Cancel all tasks
        tasks = self._tasks.get(session_id, [])
        for task in tasks:
            task.cancel()

        # Wait for tasks to finish (with timeout)
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=30.0
            )
        except asyncio.TimeoutError:
            logger.warning(f"[AlgoBot] Session {session_id} task cancellation timed out")

        # Close ALL session symbols on Binance — not just the ones the engine
        # thinks are open. This handles cases where Binance has a real position
        # but the engine's in-memory open_positions is stale (e.g. after a restart
        # or a missed SL/TP fill). Close requests for symbols with no open
        # position are safe — Node's close-position handler returns a no-op.
        # Closes run with bounded concurrency (8 in flight) so a large Chaos
        # session (100+ symbols) can actually finish inside the timeout — a
        # fully serial loop (2 signed Binance calls per symbol) cannot. Wrapped
        # in a 120-second timeout so the stop can never hang indefinitely.
        all_symbols = session.get("symbols", [])
        unconfirmed_on_stop = []
        if all_symbols:
            close_semaphore = asyncio.Semaphore(8)

            async def _close_one(symbol):
                async with close_semaphore:
                    pos_info = session.get("open_positions", {}).get(symbol)
                    try:
                        confirmed = await self._close_position_on_stop(session_id, symbol, pos_info, session)
                        if not confirmed:
                            unconfirmed_on_stop.append(symbol)
                    except Exception as e:
                        logger.error(f"[AlgoBot] Error closing position {symbol}: {e}")
                        unconfirmed_on_stop.append(symbol)

            try:
                await asyncio.wait_for(
                    asyncio.gather(*(_close_one(s) for s in all_symbols)),
                    timeout=120.0,
                )
            except asyncio.TimeoutError:
                # Do NOT clear open_positions here — any symbol still present
                # may genuinely still be open on Binance. Reporting it as
                # closed when it isn't is what orphans real positions; the
                # periodic full-account reconciliation sweep is the backstop
                # for whatever this timeout leaves unconfirmed.
                logger.error(
                    f"[AlgoBot] Position close loop timed out for session {session_id} — "
                    f"{len(session.get('open_positions', {}))} symbol(s) still tracked as open"
                )

        if unconfirmed_on_stop:
            logger.error(
                f"[AlgoBot] Session {session_id}: {len(unconfirmed_on_stop)} symbol(s) "
                f"failed to confirm-close on stop, may still be open on Binance: {unconfirmed_on_stop}"
            )

        # Mark session as stopped — always reached even after timeout. Report
        # whatever open_positions actually still holds, never a blanket [] —
        # a wrong-but-confident empty list is worse than an honest non-empty one.
        session["status"] = "stopped"
        remaining_pnl = str(round(session["pnl"], 2))
        remaining_open = list(session.get("open_positions", {}).keys())

        await self._notifier.notify(session_id, {
            "pnl": remaining_pnl,
            "openPositions": remaining_open,
            "status": "stopped",
            "event": "stopped",
        })

        # Stop per-session user data stream
        _uds = session.get("uds")
        if _uds:
            try:
                await _uds.stop()
            except Exception as _e:
                logger.warning(f"[AlgoBot] Session {session_id}: UDS stop error: {_e}")

        # Cleanup
        self.sessions.pop(session_id, None)
        self._stop_signals.pop(session_id, None)
        self._tasks.pop(session_id, None)
        self._order_semaphores.pop(session_id, None)
        for _key in [k for k in self._symbol_state_locks if k[0] == session_id]:
            self._symbol_state_locks.pop(_key, None)
        reset_session_seq(session_id)

        logger.info(f"[AlgoBot] Session {session_id} stopped")

    async def get_session_status(self, session_id: str) -> dict:
        session = self.sessions.get(session_id)
        if not session:
            return {"status": "not_found"}
        open_pos = list(session.get("open_positions", {}).keys())
        return {
            "status": session["status"],
            "pnl": str(round(session["pnl"], 2)),
            "openPositions": open_pos,
            "trading_state": session.get("trading_state", "active"),
        }

    async def set_trading_state(self, session_id: str, new_state: str) -> dict:
        """Set the trading state for a session (A-002)."""
        session = self.sessions.get(session_id)
        if not session:
            return {"success": False, "error": "Session not found"}
        if new_state not in TRADING_STATES:
            return {"success": False, "error": f"Invalid trading_state '{new_state}'. Must be one of: {', '.join(TRADING_STATES)}"}
        old_state = session.get("trading_state", "active")
        session["trading_state"] = new_state
        logger.info(f"[AlgoBot] Session {session_id}: trading_state {old_state} -> {new_state}")
        await self._notifier.notify(session_id, {
            "event": "log",
            "eventData": {"type": "info", "message": f"Trading state changed: {old_state} -> {new_state}"}
        })
        return {"success": True, "data": {"trading_state": new_state}}

    # ── Private helpers ──────────────────────────────────────────────────────

    async def _run_symbol_loop(
        self, session_id: str, strategy_class, symbol: str,
        params: dict, timeframe: str, capital: float, leverage: int,
        fee_rate: float = 0.0005, risk_params: dict | None = None,
    ) -> None:
        """Main loop for one symbol. Connects to Binance kline WebSocket and fires
        strategy logic on every closed candle. Runs until stop signal is set."""
        consecutive_errors = 0

        strategy = strategy_class()
        strategy.symbol = symbol
        strategy.timeframe = timeframe
        strategy.balance = capital
        strategy.leverage = leverage
        strategy.is_papertrading = False
        strategy.is_livetrading = True
        strategy.is_backtesting = False
        strategy.exchange = "Binance Futures"
        strategy.exchange_type = "futures"
        strategy.fee_rate = fee_rate

        # Set user params on instance (F-015/F-016: reject out-of-range and unknown params)
        _strategy_params = getattr(strategy_class, "PARAMS", {})
        for key in params:
            if key not in _strategy_params:
                raise ValueError(
                    f"Unknown parameter '{key}'. "
                    f"Valid parameters for {strategy_class.__name__}: {list(_strategy_params.keys())}"
                )
        for key, meta in _strategy_params.items():
            raw_val = params.get(key, param_default(meta))
            try:
                typed_val = param_coerce(meta, raw_val)
            except (TypeError, ValueError):
                typed_val = raw_val
            param_validate(meta, typed_val)
            setattr(strategy, key, typed_val)

        # Inject risk model params (mirrors backtest_runner step 6b). Live
        # trading executes against real fills, so slippage_pct is left at the
        # BaseStrategy default — it only models simulated market-fill slippage.
        # Each per-symbol strategy gets its own slice of the session capital.
        _risk_all = risk_params or {}
        _risk = _risk_all.get(symbol) or _risk_all.get("default") or _risk_all
        
        # Enforce global risk hard-limits as a defensive floor (F-014)
        strategy.risk_pct          = min(_safe_float(_risk.get("risk_pct"),       strategy.risk_pct), 0.20)
        strategy.rrr               = _safe_float(_risk.get("rrr"),            strategy.rrr)
        strategy.liq_buffer_pct    = _safe_float(_risk.get("liq_buffer_pct"), strategy.liq_buffer_pct)
        strategy.max_session_dd    = min(_safe_float(_risk.get("max_session_dd"), strategy.max_session_dd), 0.90)
        strategy.portfolio_model.min_edge_mult = _safe_float(_risk.get("min_edge_mult"), 0.0)
        strategy.max_portfolio_risk       = _safe_float(_risk.get("max_portfolio_risk"), 0.06)
        
        strategy.volatility_multiplier = _safe_float(_risk.get("volatility_multiplier"), 1.0)
        strategy.max_exposure_notional = _safe_float(_risk.get("max_exposure_notional"), float('inf'))
        
        custom_atr_mult = _risk.get("custom_atr_mult")
        if custom_atr_mult is not None:
            strategy.custom_atr_mult = _safe_float(custom_atr_mult, None)
        else:
            strategy.custom_atr_mult = None
        strategy.available_capital = float(capital)
        strategy.peak_equity       = float(capital)

        # Execution Model for the live env (real Binance market fills). Owns the
        # realized exit-fee accounting; composes the strategy's Cost Model.
        strategy.execution_model = LiveExecution()

        # Store strategy instance for stats access
        session = self.sessions.get(session_id)
        if session:
            session["strategy_instances"][symbol] = strategy

        # Clamp leverage defensively to absolute schema limit (125) (F-014)
        leverage = min(max(leverage, 1), 125)

        # Clamp requested leverage to what Binance actually allows for this symbol.
        # Uses the signed /fapi/v1/leverageBracket endpoint if credentials are
        # available via env (the live path always has them set in server/.env).
        api_key = session.get("api_key", "") if session else ""
        api_secret = session.get("api_secret", "") if session else ""
        effective_leverage = await clamp_leverage(
            leverage, "Binance Futures", symbol,
            api_key=api_key, api_secret=api_secret,
            mode=session["exchange"].mode if session and session.get("exchange") else "testnet",
        )

        # The leverageBracket probe above may have just confirmed this symbol is
        # rejected outright by demo-fapi (testnet exchangeInfo lists more symbols
        # than the testnet matching engine actually supports — see utils/symbols.py
        # _invalid_symbols). Abort now rather than opening a WS connection and
        # repeatedly hammering a doomed order every candle close.
        if is_symbol_invalid("Binance Futures", symbol):
            logger.warning(f"[AlgoBot] {symbol}: confirmed not tradable on this environment, skipping")
            await self._notifier.notify(session_id, {
                "event": "log",
                "eventData": {"type": "error", "message": f"{symbol}: not tradable on this environment — skipping"}
            })
            return

        if effective_leverage != leverage:
            logger.info(
                f"[AlgoBot] {symbol}: leverage clamped {leverage}→{effective_leverage} "
                f"(symbol max exceeded)"
            )
            await self._notifier.notify(session_id, {
                "event": "log",
                "eventData": {
                    "type": "info",
                    "message": f"{symbol}: leverage clamped {leverage}x→{effective_leverage}x (symbol max)"
                }
            })
        leverage = effective_leverage
        strategy.leverage = effective_leverage

        # Set leverage on Binance Testnet before entering
        try:
            await self._notifier.call_internal(
                session_id, f"/internal/algo/sessions/{session_id}/set-leverage",
                {"symbol": symbol, "leverage": leverage}
            )
            logger.info(f"[AlgoBot] Set leverage {leverage}x for {symbol}")
        except Exception as e:
            logger.warning(f"[AlgoBot] Failed to set leverage for {symbol}: {e}")

        # Plan 13: generic informative/multi-timeframe contract. Distinct from
        # the BestSupertrend-specific `tf`/`_htf_candles` duck-typing below —
        # this is `BaseStrategy.informative_timeframes` + `self.htf(tf)`, opt-in
        # via a declared list (default [] is a no-op for every existing
        # strategy). Fetched BEFORE the warmup replay below so `prepare()`
        # already sees real HTF data during warmup, not just on the first live
        # candle. Reuses `_fetch_htf_candles` (mainnet REST, same source as the
        # BestSupertrend HTF fetch — Plan 21 A-12 parity).
        strategy._htf_raw = {}
        for _inf_tf in getattr(strategy, "informative_timeframes", []) or []:
            if _inf_tf == timeframe:
                continue
            try:
                strategy._htf_raw[_inf_tf] = await self._market_data.fetch_htf_candles(symbol, _inf_tf, 500)
                logger.info(
                    f"[AlgoBot] {symbol}: informative timeframe {_inf_tf!r} candles loaded: "
                    f"{len(strategy._htf_raw[_inf_tf])}"
                )
            except Exception as e:
                logger.error(f"[AlgoBot] {symbol}: informative timeframe {_inf_tf!r} fetch failed — {e}")
                strategy._htf_raw[_inf_tf] = np.empty((0, 6), dtype=np.float64)

        # Fetch initial warmup candles from TimescaleDB
        try:
            candles = await self._market_data.fetch_warmup_candles(symbol, timeframe, WARMUP_CANDLES)
            if candles is None or len(candles) < 20:
                logger.warning(f"[AlgoBot] Not enough warmup candles for {symbol}, fetching from Binance REST")
                candles = await self._market_data.fetch_candles_from_rest(symbol, timeframe, WARMUP_CANDLES)
            strategy.candles = candles
            # Warmup: replay last 3 historical candles to prime indicator state only.
            # No orders are placed — warmup is read-only so all symbols can initialise
            # in parallel without flooding the testnet or hitting the Node timeout.
            if candles is not None and len(candles) >= 3:
                logger.info(f"[AlgoBot] {symbol}: Warming up indicator state on last 3 historical candles")
                for t in range(len(candles) - 3, len(candles)):
                    strategy.candles = candles[:t+1]
                    strategy.index = t
                    try:
                        # Two-phase contract: prepare() batch-computes indicators
                        # over the current window, before() then indexes at i.
                        strategy.prepare(strategy.candles)
                        strategy.before()
                        strategy.after()
                    except Exception as e:
                        logger.error(f"[AlgoBot] Warmup error on {symbol} at index {t}: {e}")
                # Reset strategy.candles to the full set
                strategy.candles = candles
        except Exception as e:
            logger.error(f"[AlgoBot] Failed to load warmup candles for {symbol}: {e}")
            strategy.candles = np.empty((0, 6), dtype=np.float64)

        # Fetch HTF candles if strategy uses a higher timeframe (e.g. BestSupertrend tf param)
        # Plan 24 finding S-3: a failed fetch previously only logged a debug-level
        # warning, then prepare() silently fell back to resampling the live
        # rolling candle window — which can NEVER form enough completed HTF
        # buckets for tf="weekly"/"monthly" (12 weekly buckets alone needs
        # ~2,016 hourly candles, far past any live rolling-window cap). The
        # strategy then produces zero trades forever with no visible cause.
        # Both the fetch failure AND an on-success-but-insufficient-data case
        # are now session-visible errors (c), and a required-candle estimate
        # is logged so the gap is diagnosable instead of a silent zero-trade
        # strategy (a).
        htf_tf = getattr(strategy, 'tf', None)
        if htf_tf is not None:
            htf_interval = _TF_TO_BINANCE.get(htf_tf.lower())
            if htf_interval and htf_interval != timeframe:
                _pd = getattr(strategy, "pd", None)
                _required = (_pd + 2) if isinstance(_pd, int) else None
                try:
                    htf_candles = await self._market_data.fetch_htf_candles(symbol, htf_interval, 50)
                    strategy._htf_candles = htf_candles
                    logger.info(f"[AlgoBot] {symbol}: HTF ({htf_interval}) candles loaded: {len(htf_candles)}")
                    if _required is not None and len(htf_candles) < _required:
                        _msg = (
                            f"{symbol}: only {len(htf_candles)} {htf_interval} HTF candles available, "
                            f"need {_required} (tf={htf_tf}, pd={_pd}) — this strategy will not trade "
                            f"until enough history exists"
                        )
                        logger.error(f"[AlgoBot] {_msg}")
                        await self._notifier.notify(session_id, {
                            "event": "log",
                            "eventData": {"type": "error", "message": _msg},
                        })
                except Exception as e:
                    _msg = f"{symbol}: HTF ({htf_interval}) candle fetch failed — {e}. Falling back to live-window resampling, which may never accumulate enough buckets for tf={htf_tf!r}."
                    logger.error(f"[AlgoBot] {_msg}")
                    await self._notifier.notify(session_id, {
                        "event": "log",
                        "eventData": {"type": "error", "message": _msg},
                    })

        # Register user data stream callback for event-driven fill detection
        # (F-020).  Triggers immediate reconciliation when an order fills
        # between candles — no need to wait for the next kline close.
        _uds = session.get("uds") if session else None
        _fill_cb_registered = False
        _account_cb_registered = False
        if _uds and _uds._running:
            async def _on_fill(order_data: dict) -> None:
                symbol_s = order_data.get("s", "")
                if symbol_s != symbol:
                    return
                status = order_data.get("X", "")
                client_algo_id = _extract_fill_client_id(order_data)
                logger.info(
                    f"[AlgoBot] {symbol}: user-data fill event — "
                    f"status={status} clientAlgoId={client_algo_id}"
                )

                # Plan 5 Step 5.4 (ENG-3): serialize against the per-candle
                # loop's reconcile/check_exits/evaluate_and_route block below —
                # both mutate strategy.position / session state and a fill
                # landing mid-candle-loop is a real double-close/double-count race.
                async with self._get_symbol_lock(session_id, symbol):
                    # ── F-019: OUO peer-cancel on partial/full fill ──────
                    # If a tracked algo order (tpsl_ prefix) is FILLED or
                    # PARTIALLY_FILLED, cancel the peer leg to prevent
                    # over-close on a reduced position.
                    #
                    # A-2 fix: the whole OUO block is now wrapped in its own
                    # try/except so ANY failure here (a bad client_algo_id
                    # shape, a cancel-call exception, a malformed session
                    # dict) can never prevent the reconcile call below from
                    # running. Previously an uncaught exception in this block
                    # (e.g. .startswith() on an int) killed the callback
                    # before reconcile ever executed — the event-driven fill
                    # path is only useful if reconcile is unconditional.
                    try:
                        if status in ("FILLED", "PARTIALLY_FILLED") and client_algo_id.startswith("tpsl_"):
                            _pos_info = session.get("open_positions", {}).get(symbol)
                            if _pos_info and "algo_ids" in _pos_info:
                                _aids = _pos_info["algo_ids"]
                                _peer_id = _aids.get("tp") if "sl" in client_algo_id else _aids.get("sl")
                                if _peer_id:
                                    _api_key = session.get("api_key", "") if session else ""
                                    _api_secret = session.get("api_secret", "") if session else ""
                                    if _api_key and _api_secret:
                                        _uds_exchange = (session.get("exchange") if session else None) or BinanceFuturesTestnet()
                                        await _uds_exchange.cancel_algo_order(
                                            _api_key, _api_secret,
                                            params={"symbol": symbol, "algoId": _peer_id},
                                        )
                                        logger.info(
                                            f"[AlgoBot] {symbol}: cancelled peer algo {_peer_id} "
                                            f"(OUO — {client_algo_id} filled)"
                                        )
                    except Exception as _cancel_e:
                        logger.warning(
                            f"[AlgoBot] {symbol}: OUO peer-cancel step failed — "
                            f"reconcile still proceeds: {_cancel_e}"
                        )

                    await self._reconcile_exchange_state(
                        session_id, strategy, symbol,
                        candle_high=None, candle_low=None,
                    )
            _uds.register_fill_callback(symbol, _on_fill)
            _fill_cb_registered = True

            # Plan 21 Step 21.2 (A-8): ACCOUNT_UPDATE-driven reconcile.
            # Binance emits ACCOUNT_UPDATE with a P[] position delta for
            # EVERY position change — plain orders, conditional/algo
            # (/fapi/v1/algoOrder) TP-SL fills, liquidations, manual closes
            # — regardless of whether ORDER_TRADE_UPDATE fires for algo
            # orders (the open F7 question _on_fill's `tpsl_` match depends
            # on). This is the event-type-agnostic fallback that closes the
            # ~60s window: if a position's open/flat state disagrees with
            # what this engine believes, reconcile immediately instead of
            # waiting for the next candle-close poll. ORDER_TRADE_UPDATE
            # handling (_on_fill) stays as richer, faster enrichment when it
            # does fire correctly; this is the backstop that doesn't depend
            # on algo-order client-id semantics at all.
            async def _on_account_update(pos_data: dict) -> None:
                pos_symbol = pos_data.get("s", "")
                if pos_symbol != symbol:
                    return
                has_local_position = strategy.position is not None and strategy.position.is_open

                if not _account_update_needs_reconcile(pos_data, has_local_position):
                    # Open/flat agree — nothing to reconcile. A quantity-only
                    # change on an already-agreed-open position is picked up
                    # by the next candle-close reconcile; this callback exists
                    # specifically to close the OPEN<->FLAT staleness window.
                    return

                lock = self._get_symbol_lock(session_id, symbol)
                if lock.locked():
                    # Debounce (21.2 spec): a reconcile is already in flight
                    # for this symbol (candle loop or _on_fill) and will
                    # observe this same fresh exchange state when it runs —
                    # queuing a second one here is a redundant Binance call,
                    # so skip rather than wait.
                    logger.info(
                        f"[AlgoBot] {symbol}: account-update reconcile skipped — "
                        f"one already in flight"
                    )
                    return

                logger.info(
                    f"[AlgoBot] {symbol}: account update reports position "
                    f"{'OPEN' if _safe_float(pos_data.get('pa'), 0.0) != 0 else 'FLAT'} but local view says "
                    f"{'OPEN' if has_local_position else 'FLAT'} — reconciling now"
                )
                async with lock:
                    await self._reconcile_exchange_state(
                        session_id, strategy, symbol,
                        candle_high=None, candle_low=None,
                    )

            _uds.register_account_callback(symbol, _on_account_update)
            _account_cb_registered = True

        stop_event = self._stop_signals.get(session_id)
        # A-12: mainnet public kline stream feeds the signal/indicator path;
        # order execution (entries, SL/TP, position management) stays on
        # testnet via the existing signed REST calls elsewhere in this file —
        # see `_kline_ws_url`'s docstring and DECISIONS.md #24.
        ws_url = _kline_ws_url(symbol, timeframe)
        # Capped exponential backoff + full jitter (mirrors UserDataStreamManager
        # ._run_ws in services/user_data_stream.py). A Chaos session can hold ~80
        # symbols, each running this same loop — a flat retry delay would have
        # every symbol reconnect in lockstep on any shared gateway blip. Jitter
        # spreads reconnect attempts out so they don't all hit Binance at once.
        reconnect_backoff = 1

        try:
            while not (stop_event and stop_event.is_set()):
                try:
                    async with websockets.connect(
                        ws_url,
                        ping_interval=20,
                        ping_timeout=20,
                        close_timeout=5,
                    ) as ws:
                        logger.info(f"[AlgoBot] {symbol}: WS connected → {ws_url}")
                        reconnect_backoff = 1  # Reset on successful connect
                        await self._notifier.notify(session_id, {
                            "event": "log",
                            "eventData": {"type": "info", "message": f"{symbol}: WS connected · waiting for {timeframe} candle closes"}
                        })

                        warmed_up = len(strategy.candles) >= _get_min_candles_required(strategy)

                        async for raw in ws:
                            if stop_event and stop_event.is_set():
                                return

                            # Parse kline message
                            try:
                                msg = json.loads(raw)
                            except Exception:
                                continue

                            kline = msg.get("k", {})
                            if not kline.get("x", False):
                                # Candle still open — skip until it closes
                                continue

                            close_price = float(kline["c"])

                            # Build candle [timestamp_ms, open, close, high, low, volume]
                            candle = np.array([
                                float(kline["t"]),  # open time ms
                                float(kline["o"]),  # open
                                close_price,        # close
                                float(kline["h"]),  # high
                                float(kline["l"]),  # low
                                float(kline["v"]),  # volume
                            ], dtype=np.float64)
                            strategy.candles = self._market_data.append_candle(strategy.candles, candle)

                            min_required = _get_min_candles_required(strategy)
                            if len(strategy.candles) < min_required:
                                warmed_up = False
                                logger.info(f"[AlgoBot] {symbol}: warming up ({len(strategy.candles)}/{min_required})")
                                continue

                            # Emit "ready" once when warmup completes
                            if not warmed_up:
                                warmed_up = True
                                await self._notifier.notify(session_id, {
                                    "event": "log",
                                    "eventData": {"type": "info", "message": f"{symbol}: Ready · {len(strategy.candles)} candles loaded"}
                                })

                            # Update HTF candles on each closed base candle (live multi-timeframe)
                            _htf_tf = getattr(strategy, 'tf', None)
                            if _htf_tf is not None and getattr(strategy, '_htf_candles', None) is not None:
                                _htf_interval = _TF_TO_BINANCE.get(_htf_tf.lower())
                                if _htf_interval and _htf_interval != timeframe:
                                    try:
                                        _new_htf = await self._market_data.fetch_htf_candles(symbol, _htf_interval, 2)
                                        if len(_new_htf) > 0:
                                            _last_ts = strategy._htf_candles[-1, 0] if len(strategy._htf_candles) > 0 else 0
                                            if _new_htf[-1, 0] > _last_ts:
                                                strategy._htf_candles = self._market_data.append_candle(strategy._htf_candles, _new_htf[-1])
                                                if len(strategy._htf_candles) > 100:
                                                    strategy._htf_candles = strategy._htf_candles[-100:]
                                    except Exception as _e:
                                        logger.warning(f"[AlgoBot] {symbol}: HTF candle update failed — {_e}")

                            # Plan 13: refresh each declared informative timeframe on every
                            # closed base candle, same pattern as the BestSupertrend-specific
                            # block above but generic over `informative_timeframes`.
                            for _inf_tf in getattr(strategy, "informative_timeframes", []) or []:
                                if _inf_tf == timeframe:
                                    continue
                                try:
                                    _new_inf = await self._market_data.fetch_htf_candles(symbol, _inf_tf, 2)
                                    if len(_new_inf) > 0:
                                        _cur = strategy._htf_raw.get(_inf_tf, np.empty((0, 6), dtype=np.float64))
                                        _last_ts = _cur[-1, 0] if len(_cur) > 0 else 0
                                        if _new_inf[-1, 0] > _last_ts:
                                            strategy._htf_raw[_inf_tf] = self._market_data.append_candle(_cur, _new_inf[-1])
                                except Exception as _e:
                                    logger.warning(f"[AlgoBot] {symbol}: informative timeframe {_inf_tf!r} update failed — {_e}")

                            try:
                                # Two-phase contract (live): re-run the one-time
                                # vectorized prepare() on the rolling ≤500-candle
                                # window each closed candle, set index to the last
                                # row, then before() is a pure index lookup —
                                # identical indicator math to the backtest path,
                                # O(≤500) per candle (~once/hr), no drift.
                                strategy.index = len(strategy.candles) - 1
                                strategy.prepare(strategy.candles)

                                # Plan 24 finding S-3(b): a strategy whose HTF
                                # value structurally never resolves (e.g. an
                                # unsatisfiable tf/timeframe combo the startup
                                # check at session-start missed — impossible
                                # to fully rule out in advance, e.g. daily-tf
                                # data-quality gaps) silently produces zero
                                # trades forever with nothing in the session
                                # log. Once the live rolling candle window
                                # hits its cap (500 — see the `candles[-500:]`
                                # trim below), it can never get any better, so
                                # fire ONE persistent warning, not a debug log.
                                if (
                                    htf_tf is not None
                                    and hasattr(strategy, "_htf_st_at")
                                    and len(strategy.candles) >= 500
                                ):
                                    _htf_warned = session.setdefault("_htf_not_ready_warned_symbols", set())
                                    if symbol not in _htf_warned:
                                        try:
                                            _htf_val = strategy._htf_st_at(strategy.index)
                                        except Exception:
                                            _htf_val = None
                                        if _htf_val is None:
                                            _htf_warned.add(symbol)
                                            _msg = (
                                                f"{symbol}: HTF supertrend still not ready after "
                                                f"{len(strategy.candles)} candles (tf={htf_tf}) — this "
                                                f"strategy cannot generate signals until enough HTF "
                                                f"history exists; check the tf/timeframe combo"
                                            )
                                            logger.warning(f"[AlgoBot] {_msg}")
                                            await self._notifier.notify(session_id, {
                                                "event": "log",
                                                "eventData": {"type": "warning", "message": _msg},
                                            })

                                # Plan 5 Step 5.4 (ENG-3): serialize against
                                # _on_fill's reconcile call above — see its
                                # comment for why this lock exists.
                                async with self._get_symbol_lock(session_id, symbol):
                                    # Phase 5: Reconcile state with exchange BEFORE any decision
                                    # Unconditionally syncs positions AND open orders every loop.
                                    # Self-heals when engine wrongly believes it is flat (F-004),
                                    # reconciles open orders (F-002), and uses exchange data
                                    # as single source of truth (F-001).
                                    await self._reconcile_exchange_state(
                                        session_id, strategy, symbol,
                                        candle_high=candle[3], candle_low=candle[4],
                                    )

                                    # Setup execution algorithm if configured (A-016 parity with backtest path)
                                    exec_algo = None
                                    exec_algo_cfg = params.get("exec_algo") if isinstance(params, dict) else None
                                    if exec_algo_cfg and isinstance(exec_algo_cfg, dict):
                                        algo_type = exec_algo_cfg.get("type")
                                        algo_params = exec_algo_cfg.get("params", {})
                                        from core.models.exec_algo import TWAPAlgorithm, VWAPAlgorithm, IcebergAlgorithm

                                        if algo_type == "twap":
                                            exec_algo = TWAPAlgorithm(strategy, symbol, algo_params)
                                        elif algo_type == "vwap":
                                            exec_algo = VWAPAlgorithm(strategy, symbol, algo_params)
                                        elif algo_type == "iceberg":
                                            exec_algo = IcebergAlgorithm(strategy, symbol, algo_params)

                                    adapter = LiveAdapter(self, session_id)
                                    kernel = ExecutionKernel(adapter, exec_algo)
                                    time_t = datetime.fromtimestamp(candle[0] / 1000, tz=timezone.utc)

                                    # Plan 21 A-13: tell check_exits which legs
                                    # already have a confirmed-resting exchange
                                    # bracket order (algo_ids, just refreshed by
                                    # the reconcile call above — A-7 re-arms a
                                    # missing SL there before this point) so it
                                    # skips its own wick-check for that leg
                                    # instead of racing the exchange conditional.
                                    _armed_algo_ids = (session.get("open_positions", {}).get(symbol) or {}).get("algo_ids") or {}
                                    _armed_legs = {
                                        "sl": bool(_armed_algo_ids.get("sl")),
                                        "tp": bool(_armed_algo_ids.get("tp")),
                                    }

                                    await kernel.check_exits(
                                        strategy=strategy,
                                        symbol=symbol,
                                        candle=candle,
                                        index_t=strategy.index,
                                        time_t=time_t,
                                        armed_legs=_armed_legs,
                                    )

                                    await kernel.evaluate_and_route(
                                        strategy=strategy,
                                        symbol=symbol,
                                        candle=candle,
                                        index_t=strategy.index,
                                        time_t=time_t,
                                    )

                                    # M-4 fix (Plan 21.4): if route()'s Path 5
                                    # just tightened strategy.stop_loss
                                    # (trailing/breakeven/Chandelier), amend
                                    # the resting exchange SL to match — see
                                    # _maybe_amend_exchange_sl's docstring.
                                    await self._maybe_amend_exchange_sl(
                                        session, session_id, strategy, symbol,
                                    )
                            except Exception as e:
                                consecutive_errors += 1
                                logger.error(
                                    f"[AlgoBot] Strategy error [{symbol}] "
                                    f"(#{consecutive_errors}): {e}"
                                )
                                if consecutive_errors >= 5:
                                    logger.error(
                                        f"[AlgoBot] {symbol} exceeded max errors, stopping."
                                    )
                                    await self._notifier.notify(session_id, {
                                        "status": "error",
                                        "errorMessage": f"Strategy loop failed on {symbol}: {e}"
                                    })
                                    return
                                continue
                            else:
                                consecutive_errors = 0

                            await self._push_stats(session_id)

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    if stop_event and stop_event.is_set():
                        return
                    delay = random.uniform(0, reconnect_backoff)
                    logger.warning(
                        f"[AlgoBot] {symbol}: WS disconnected ({e}), reconnecting in {delay:.1f}s "
                        f"(backoff={reconnect_backoff}s)"
                    )
                    await self._notifier.notify(session_id, {
                        "event": "log",
                        "eventData": {"type": "error", "message": f"{symbol}: WS disconnected — reconnecting in {delay:.1f}s"}
                    })
                    await asyncio.sleep(delay)
                    reconnect_backoff = min(reconnect_backoff * 2, 60)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[AlgoBot] Unexpected error in symbol loop [{symbol}]: {e}")
        finally:
            if _fill_cb_registered:
                try:
                    _uds.unregister_fill_callback(symbol, _on_fill)
                except Exception:
                    pass
            if _account_cb_registered:
                try:
                    _uds.unregister_account_callback(symbol, _on_account_update)
                except Exception:
                    pass

    # Thin delegating wrappers (Plan 6 Step 6.1, ENG-1): exchange-truth
    # reconciliation, algo-order cancel/amend, and governor-breach
    # application now live in `Reconciler` — kept under these same old
    # names so every existing call site (this file's own methods,
    # `LiveAdapter.manager.<name>`, and every test that drives these
    # methods directly, e.g. `mgr._reconcile_exchange_state(...)`) keeps
    # working unchanged, same pattern as the `SessionRegistry` facade above.
    async def _cancel_symbol_algo_orders(self, session: dict, symbol: str, algo_ids: dict | None = None) -> None:
        return await self._reconciler.cancel_symbol_algo_orders(session, symbol, algo_ids)

    async def _maybe_amend_exchange_sl(self, session: dict, session_id: str, strategy, symbol: str) -> None:
        return await self._reconciler.maybe_amend_exchange_sl(session, session_id, strategy, symbol)

    async def _close_position_on_stop(self, session_id: str, symbol: str, _pos_info: dict | None, session: dict) -> bool:
        return await self._reconciler.close_position_on_stop(session_id, symbol, _pos_info, session)

    async def _reconcile_exchange_state(
        self, session_id: str, strategy, symbol: str,
        candle_high: float | None = None, candle_low: float | None = None,
    ) -> dict:
        return await self._reconciler.reconcile_exchange_state(session_id, strategy, symbol, candle_high, candle_low)

    @staticmethod
    def _compute_session_equity_and_margin(session: dict) -> tuple[float, float]:
        return Reconciler.compute_session_equity_and_margin(session)

    @staticmethod
    def _compute_open_risk_breakdown(session: dict) -> dict[str, float]:
        return Reconciler.compute_open_risk_breakdown(session)

    async def _apply_governor_breach(self, session_id: str, session: dict, verdict) -> None:
        return await self._reconciler.apply_governor_breach(session_id, session, verdict)

    async def _push_stats(self, session_id: str) -> None:
        """Push periodic stats update to Node including exchange-truth position
        details with mark-price PnL (F-023/A-013)."""
        session = self.sessions.get(session_id)
        if not session:
            return
        equity, _used_margin = self._compute_session_equity_and_margin(session)
        total_pnl = equity - session.get("capital", 0.0)

        # Session Risk Governor periodic check (Plan 22 Step 22.1) —
        # aggregate drawdown + daily loss limit. Margin ceiling is
        # pre-trade-only (Part C's table), not evaluated here.
        risk_governor = session.get("risk_governor")
        if risk_governor is not None and session.get("trading_state", "active") == "active":
            verdict = risk_governor.check_periodic(equity=equity, now=datetime.now(timezone.utc))
            if not verdict.ok:
                await self._apply_governor_breach(session_id, session, verdict)
            elif risk_governor.var_limit_pct is not None or risk_governor.cvar_limit_pct is not None:
                # Plan 22 Step 22.4: periodic VaR/CVaR check — same shared
                # `compute_var_cvar` the pre-trade gate and the Zone 1
                # dashboard use, 10s/60s cached. Best-effort: a fetch/compute
                # failure here just skips this tick's check (logged), rather
                # than tripping a breach on a transient network error — the
                # standing-limit checks above already ran and are unaffected.
                try:
                    from services.portfolio_risk import compute_var_cvar as _compute_var_cvar
                    _var_amount, _cvar_amount = await _compute_var_cvar(
                        session.get("api_key", ""), session.get("api_secret", ""),
                        mode=session["exchange"].mode if session.get("exchange") else "testnet",
                    )
                    _var_verdict = risk_governor.check_var(
                        var_amount=_var_amount, cvar_amount=_cvar_amount, equity=equity,
                    )
                    if not _var_verdict.ok:
                        await self._apply_governor_breach(session_id, session, _var_verdict)
                except Exception as _var_e:
                    logger.warning(
                        f"[AlgoBot] Session {session_id}: periodic VaR/CVaR check failed to compute, "
                        f"skipping this tick — {_var_e}"
                    )

        # Position details with exchange-truth data for the UI (F-023)
        position_details = {}
        for sym, info in session.get("open_positions", {}).items():
            strat = session.get("strategy_instances", {}).get(sym)
            pos_obj = strat.position if strat else None
            unrealized = info.get("unrealized_pnl")
            if unrealized is None and pos_obj is not None:
                unrealized = str(round(pos_obj.pnl, 2))
            position_details[sym] = {
                "side": info.get("side"),
                "qty": info.get("qty"),
                "price": info.get("price"),
                "leverage": info.get("leverage"),
                "mark_price": info.get("mark_price"),
                "unrealized_pnl": unrealized,
                "price_missing": info.get("price_missing", False) or (unrealized is None and pos_obj is not None),
            }
        await self._notifier.notify(session_id, {
            "pnl": str(round(total_pnl, 2)),
            "openPositions": list(session.get("open_positions", {}).keys()),
            "status": "running",
            "trading_state": session.get("trading_state", "active"),
            "positionDetails": position_details,
        })

async def _query_real_exit_from_user_trades(
    api_key: str, api_secret: str, symbol: str, entry_time: datetime,
    exchange: "Exchange | None" = None,
) -> tuple[float, float] | None:
    """Plan 5 Step 5.2 (ENG-2): reconstruct a close the engine didn't itself
    execute (SL/TP fired exchange-side, or state drifted) from Binance's own
    trade history instead of guessing from candle/SL/TP levels.

    Returns (avg_exit_price, net_realized_pnl) — net_realized_pnl is
    Binance's own realizedPnl minus its own commission for the matched
    fills, i.e. already the authoritative post-fee number — or None if no
    matching fills are found.

    `exchange` (Plan 6 Step 6.2, ENG-4) defaults to `BinanceFuturesTestnet()`
    — `Reconciler.reconcile_exchange_state` passes the session's own resolved
    instance; the default only matters for direct/test callers.
    """
    try:
        _exchange = exchange or BinanceFuturesTestnet()
        trades = await _exchange.query_user_trades(
            api_key, api_secret, params={"symbol": symbol, "limit": 20},
        )
    except Exception as e:
        logger.error(f"[AlgoBot] {symbol}: userTrades query failed: {e}")
        return None

    if not isinstance(trades, list) or not trades:
        return None

    entry_ms = entry_time.timestamp() * 1000
    relevant = [t for t in trades if _safe_float(t.get("time"), 0) >= entry_ms]
    if not relevant:
        # Clock skew or an entry_time we don't fully trust — best-effort fall
        # back to the most recent fills rather than finding nothing.
        relevant = trades[-3:]

    total_qty = sum(abs(_safe_float(t.get("qty"), 0)) for t in relevant)
    if total_qty <= 0:
        return None

    avg_price = sum(_safe_float(t.get("price"), 0) * abs(_safe_float(t.get("qty"), 0)) for t in relevant) / total_qty
    total_realized_pnl = sum(_safe_float(t.get("realizedPnl"), 0) for t in relevant)
    total_commission = sum(_safe_float(t.get("commission"), 0) for t in relevant)
    return avg_price, total_realized_pnl - total_commission


# Singleton instance
live_bot_manager = LiveBotManager()
