"""Unified execution loop driver kernel (F-024).

Implements the Callback/Adapter pattern via ``ExecutionAdapter`` and
the core state transition machine ``ExecutionKernel``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import numpy as np

from core.models import OrderPlan
from core.position import Position
from core.pipeline import evaluate
from core.candle_columns import TIMESTAMP, OPEN, CLOSE, HIGH, LOW, VOLUME
from services.fill_model import gap_through_stop_price, bounded_exit_price


class ExecutionAdapter(ABC):
    """Abstract base class for execution adapters (backtest vs live)."""

    @property
    @abstractmethod
    def is_live(self) -> bool:
        """True for the live adapter, False for backtest. Plan 6 Step 6.4
        (ENG-5): the kernel used to take `is_live` as a parameter on
        `check_exits`/`evaluate_and_route`, threaded in by each call site —
        a caller could pass the wrong value for the adapter it was actually
        driving. Now the kernel asks the adapter itself, so "is this a live
        run" has exactly one source of truth (the adapter instance), not a
        boolean re-stated at every call site. This does NOT change the
        live/backtest orchestration timing (backtest still defers fills to
        `execute_pending()` on the next candle via `strategy.buy`/`sell`/
        `_pending_flip`/`_close_at_open`/`qty_to_adjust`; live still executes
        inline in `evaluate_and_route()`) — see that method's own note for
        why that timing split stays kernel-level, not adapter-level."""

    @abstractmethod
    async def execute_entry(
        self, strategy, symbol: str, direction: str, qty: float, ref_price: float,
        time_t: datetime, index_t: int, intent: str = "enter", adjust_tag: str = "",
        stop_loss: float | None = None, take_profit: float | None = None,
    ) -> bool:
        """Execute a market entry order. Returns True if entered.

        intent: "enter" for new position, "add" for DCA scale-in.
        adjust_tag: label from strategy.adjust_trade_position() for per-tag analytics.
        stop_loss/take_profit (Plan 6 Step 6.3 phase (b)): optional explicit values
        from the typed OrderPlan. Implementations that don't use them may ignore
        them (e.g. BacktestAdapter, which reads strategy.buy/sell/stop_loss via
        its own deferred execute_pending() mechanism, not this method).
        """

    @abstractmethod
    async def execute_exit(
        self, strategy, symbol: str, qty: float, exit_price: float, reason: str, time_t: datetime, index_t: int,
        high_t: float, low_t: float
    ) -> None:
        """Execute a market exit order (liquidation, stop loss, take profit, or strategy close)."""

    @abstractmethod
    async def execute_flip(
        self, strategy, symbol: str, new_direction: str, new_qty: float, ref_price: float, time_t: datetime,
        index_t: int, high_t: float, low_t: float, stop_loss: float | None = None, take_profit: float | None = None
    ) -> bool:
        """Execute atomic close-and-reverse order. Returns True if flip succeeded."""

    @abstractmethod
    async def execute_reduce(
        self, strategy, symbol: str, qty: float, exit_price: float,
        time_t: datetime, index_t: int, adjust_tag: str = "",
    ) -> None:
        """Partial position reduction (DCA scale-out). Closes ``qty`` units
        without closing the entire position. The reduced leg is recorded as
        a separate realized P&L event for per-tag analytics."""

    @abstractmethod
    async def verify_position(self, strategy, symbol: str) -> None:
        """Verify if the position is still open on exchange (live only)."""

    async def charge_funding(self, strategy, close_t: float, time_t: datetime) -> None:
        """Charge funding fee (backtest only)."""
        pass


class ExecutionKernel:
    """Unified execution kernel orchestrating exit checks, indicators and evaluations."""

    def __init__(
        self, adapter: ExecutionAdapter, exec_algo=None, entry_candle_exits: bool = False,
        intrabar_detail: bool = False, detail_candles_by_symbol: dict | None = None,
        base_timeframe_ms: int | None = None,
    ) -> None:
        self.adapter = adapter
        self.exec_algo = exec_algo
        # QNT-3 (Plan 9 Step 9.4), opt-in, default off: backtest normally skips
        # SL/TP/liquidation checks on the same candle a position was entered
        # (the entered_this_candle guard below), an optimistic bias relative to
        # live — exchange-side SL/TP orders are active immediately after the
        # entry fill there. Default False keeps the existing golden-master
        # behavior; flip only with a deliberate re-baseline + sign-off.
        self.entry_candle_exits = entry_candle_exits
        # QNT-3 residual / ENG-18 (Plan 9 Step 9.8), opt-in, default off: when
        # BOTH SL and TP wicks are hit within the same base candle, the
        # default (intrabar_detail=False) keeps the existing conservative
        # bias — SL assumed first (engine/CLAUDE.md's documented contract).
        # When True, `detail_candles_by_symbol` (1m candles per symbol, whole
        # backtest range, fetched by backtest_runner.py) is scanned within the
        # ambiguous base candle's [open, open+timeframe) window in
        # chronological order — whichever level's wick genuinely triggers
        # first at 1m granularity wins. Falls back to the SL-first default
        # when detail data isn't available for that window (gap in 1m
        # history) — never a hard failure. Live is never affected (armed_legs
        # normally resolves this via the exchange's own trigger order; this
        # is a backtest-only refinement).
        self.intrabar_detail = intrabar_detail
        self.detail_candles_by_symbol = detail_candles_by_symbol or {}
        self.base_timeframe_ms = base_timeframe_ms

    def _resolve_intrabar_winner(
        self, symbol: str, is_long: bool, sl_price: float, tp_price: float, bucket_start_ms: float,
    ) -> str | None:
        """Scan 1m detail candles within one base candle's [open, open+tf)
        window, in time order, returning "stop_loss"/"take_profit" for
        whichever level's wick genuinely triggers first — or None if detail
        data isn't available/covers this window, or neither level actually
        triggers within it (caller falls back to the SL-first default)."""
        if not self.intrabar_detail or self.base_timeframe_ms is None:
            return None
        detail = self.detail_candles_by_symbol.get(symbol)
        if detail is None or len(detail) == 0:
            return None
        bucket_end_ms = bucket_start_ms + self.base_timeframe_ms
        ts = detail[:, TIMESTAMP]
        lo = np.searchsorted(ts, bucket_start_ms, side="left")
        hi = np.searchsorted(ts, bucket_end_ms, side="left")
        window = detail[lo:hi]
        for row in window:
            d_high, d_low = row[HIGH], row[LOW]
            if is_long:
                if d_low <= sl_price:
                    return "stop_loss"
                if d_high >= tp_price:
                    return "take_profit"
            else:
                if d_high >= sl_price:
                    return "stop_loss"
                if d_low <= tp_price:
                    return "take_profit"
        return None

    async def execute_pending(self, strategy, symbol: str, candle: np.ndarray, index_t: int, time_t: datetime) -> None:
        """Simulates next-open fills for orders placed on the previous candle (backtest only)."""
        open_t = candle[OPEN]
        high_t = candle[HIGH]
        low_t = candle[LOW]

        # 1. Atomic Flip
        if strategy.position is not None and strategy._pending_flip is not None:
            flip = strategy._pending_flip
            strategy._pending_flip = None
            await self.adapter.execute_flip(
                strategy=strategy,
                symbol=symbol,
                new_direction=flip["direction"],
                new_qty=flip["qty"],
                ref_price=open_t,
                time_t=time_t,
                index_t=index_t,
                high_t=high_t,
                low_t=low_t,
                stop_loss=flip.get("stop_loss"),
                take_profit=flip.get("take_profit"),
            )
            return

        # 2. Strategy close at open
        if strategy.position is not None and strategy._close_at_open:
            strategy._close_at_open = False
            await self.adapter.execute_exit(
                strategy=strategy,
                symbol=symbol,
                qty=strategy.position.qty,
                exit_price=open_t,
                reason="strategy_exit",
                time_t=time_t,
                index_t=index_t,
                high_t=high_t,
                low_t=low_t,
            )
            return

        # 2b. DCA position adjustment (scale in/out) — A-014
        if strategy.position is not None and strategy.qty_to_adjust != 0.0:
            delta = strategy.qty_to_adjust
            tag = strategy.adjust_tag
            strategy.qty_to_adjust = 0.0
            strategy.adjust_tag = ""
            if delta > 0:
                # Scale in — add to existing position
                await self.adapter.execute_entry(
                    strategy=strategy,
                    symbol=symbol,
                    direction=strategy.position.type,
                    qty=delta,
                    ref_price=open_t,
                    time_t=time_t,
                    index_t=index_t,
                    intent="add",
                    adjust_tag=tag,
                )
            else:
                # Scale out — partial exit
                reduce_qty = min(abs(delta), strategy.position.qty)
                if reduce_qty < strategy.position.qty:
                    await self.adapter.execute_reduce(
                        strategy=strategy,
                        symbol=symbol,
                        qty=reduce_qty,
                        exit_price=open_t,
                        time_t=time_t,
                        index_t=index_t,
                        adjust_tag=tag,
                    )
                else:
                    await self.adapter.execute_exit(
                        strategy=strategy,
                        symbol=symbol,
                        qty=strategy.position.qty,
                        exit_price=open_t,
                        reason="scale_out",
                        time_t=time_t,
                        index_t=index_t,
                        high_t=high_t,
                        low_t=low_t,
                    )
            return

        # 3. Entry buy or sell
        if strategy.position is None:
            # Let strategy cancel a pending entry before it fills (backtest parity)
            if strategy.buy is not None or strategy.sell is not None:
                try:
                    if strategy.should_cancel_entry():
                        strategy.buy = None
                        strategy.sell = None
                except Exception:
                    pass

            if strategy.buy is not None:
                qty, _ = strategy.buy
                strategy.buy = None
                await self.adapter.execute_entry(
                    strategy=strategy,
                    symbol=symbol,
                    direction="long",
                    qty=qty,
                    ref_price=open_t,
                    time_t=time_t,
                    index_t=index_t,
                )
            elif strategy.sell is not None:
                qty, _ = strategy.sell
                strategy.sell = None
                await self.adapter.execute_entry(
                    strategy=strategy,
                    symbol=symbol,
                    direction="short",
                    qty=qty,
                    ref_price=open_t,
                    time_t=time_t,
                    index_t=index_t,
                )

    async def check_exits(
        self, strategy, symbol: str, candle: np.ndarray, index_t: int, time_t: datetime,
        armed_legs: dict | None = None,
    ) -> None:
        """Verify position on exchange and check SL/TP/liquidation triggers.

        armed_legs (Plan 21 A-13, live only): optional {"sl": bool, "tp": bool}
        telling this method which legs currently have a confirmed-resting
        exchange bracket order (`open_positions[symbol]["algo_ids"]`, kept
        armed every candle by A-7's naked-position re-arm detector in
        `_reconcile_exchange_state`, which runs immediately before this call).
        A leg with armed_legs[leg]=True is skipped here — the exchange's own
        MARK_PRICE-triggered conditional order will fire it, and the existing
        reconcile loop picks up the resulting close within one candle, same
        as it always has. This avoids the duplicate-execution semantics A-13
        flagged (engine wick-check vs exchange conditional racing each other,
        or booking `exit_reason="stop_loss"` for a fill that actually
        happened on the exchange at a different price). A leg with
        armed_legs[leg]=False (or missing/`None` altogether, e.g. backtest or
        the leg not being tracked) falls back to this method's own wick-check
        exactly as before — this is the "brackets missing" fallback A-7's
        detector makes explicit. Backtest never passes this (no exchange
        brackets exist there), so default `None` preserves byte-identical
        behavior — no golden master impact.
        """
        is_live = self.adapter.is_live
        if not is_live and not self.entry_candle_exits and getattr(strategy, "_entered_this_candle", False):
            return

        if strategy.position is None:
            return

        open_t = candle[OPEN]
        close_t = candle[CLOSE]
        high_t = candle[HIGH]
        low_t = candle[LOW]

        # 1. Update position unrealized P&L
        strategy.position.update_pnl(close_t)

        # Charge funding (backtest only)
        await self.adapter.charge_funding(strategy, close_t, time_t)

        # 2. Check exits
        closed = False
        exit_price = 0.0
        exit_reason = ""
        was_long = strategy.is_long

        # Liquidation (simulated in backtest only)
        # Note: exchange state reconciliation (F-001/F-004) is done by
        # _reconcile_exchange_state() before check_exits() is called, so
        # there is no separate verify_position call here for live.
        if not is_live and strategy.position.is_liquidated(high_t, low_t):
            exit_price = strategy.position.liquidation_price
            exit_reason = "liquidation"
            closed = True

        # A-13: a leg the caller confirms has a live, resting exchange bracket
        # order is skipped here — the exchange's own MARK_PRICE conditional
        # will fire it, and reconcile picks up the resulting close within one
        # candle. `armed_legs` is only ever passed from the live call site
        # (see this method's docstring); backtest's `armed_legs=None` makes
        # both flags False, so this changes nothing there.
        _sl_armed = bool(armed_legs and armed_legs.get("sl"))
        _tp_armed = bool(armed_legs and armed_legs.get("tp"))

        if not closed:
            if strategy.is_long:
                # Plan 6 Step 6.3 phase (d2): read from the persisted typed
                # active_bracket instead of the mutable stop_loss/take_profit
                # tuples. Equivalent by construction — route()/kernel's
                # exec_algo branch write active_bracket from the same values
                # at the same call sites (see d1), and active_bracket is only
                # ever None while flat, which this method already returns
                # early for (strategy.position is not None, checked above).
                _ab = strategy.active_bracket
                sl_price = _ab.stop_loss   if (_ab is not None and not _sl_armed) else None
                tp_price = _ab.take_profit if (_ab is not None and not _tp_armed) else None
                sl_hit = sl_price is not None and low_t <= sl_price
                tp_hit = tp_price is not None and high_t >= tp_price

                winner = None
                if sl_hit and tp_hit:
                    # QNT-3 residual (Plan 9 Step 9.8): both wicks hit this
                    # candle — ambiguous ordering. Default: SL first
                    # (conservative, unchanged). Opt-in: resolve via 1m detail.
                    winner = self._resolve_intrabar_winner(
                        symbol, is_long=True, sl_price=sl_price, tp_price=tp_price,
                        bucket_start_ms=candle[TIMESTAMP],
                    ) or "stop_loss"
                elif sl_hit:
                    winner = "stop_loss"
                elif tp_hit:
                    winner = "take_profit"

                if winner == "stop_loss":
                    exit_reason = "stop_loss"
                    closed = True
                    if not is_live:
                        gap_price = gap_through_stop_price(
                            is_long=True,
                            stop_price=sl_price,
                            candle_open=open_t,
                            candle_low=low_t,
                            candle_high=high_t,
                        )
                        exit_price = gap_price if gap_price is not None else sl_price
                    else:
                        exit_price = sl_price
                elif winner == "take_profit":
                    exit_price = tp_price
                    exit_reason = "take_profit"
                    closed = True
            elif strategy.is_short:
                # See the is_long branch above (Plan 6 Step 6.3 phase (d2)).
                _ab = strategy.active_bracket
                sl_price = _ab.stop_loss   if (_ab is not None and not _sl_armed) else None
                tp_price = _ab.take_profit if (_ab is not None and not _tp_armed) else None
                sl_hit = sl_price is not None and high_t >= sl_price
                tp_hit = tp_price is not None and low_t <= tp_price

                winner = None
                if sl_hit and tp_hit:
                    winner = self._resolve_intrabar_winner(
                        symbol, is_long=False, sl_price=sl_price, tp_price=tp_price,
                        bucket_start_ms=candle[TIMESTAMP],
                    ) or "stop_loss"
                elif sl_hit:
                    winner = "stop_loss"
                elif tp_hit:
                    winner = "take_profit"

                if winner == "stop_loss":
                    exit_reason = "stop_loss"
                    closed = True
                    if not is_live:
                        gap_price = gap_through_stop_price(
                            is_long=False,
                            stop_price=sl_price,
                            candle_open=open_t,
                            candle_low=low_t,
                            candle_high=high_t,
                        )
                        exit_price = gap_price if gap_price is not None else sl_price
                    else:
                        exit_price = sl_price
                elif winner == "take_profit":
                    exit_price = tp_price
                    exit_reason = "take_profit"
                    closed = True

        if closed:
            await self.adapter.execute_exit(
                strategy=strategy,
                symbol=symbol,
                qty=strategy.position.qty,
                exit_price=exit_price,
                reason=exit_reason,
                time_t=time_t,
                index_t=index_t,
                high_t=high_t,
                low_t=low_t,
            )

    async def evaluate_and_route(
        self, strategy, symbol: str, candle: np.ndarray, index_t: int, time_t: datetime
    ) -> None:
        """Runs prepare, before, evaluate, execution algorithms, routes and runs after hooks."""
        is_live = self.adapter.is_live
        strategy.index = index_t

        # Track session peak equity and drawdown
        strategy.risk_model.update_session_risk(strategy)

        # Run before() indicator checks
        strategy.before()

        current_holding = (
            strategy.position.qty * (1 if strategy.is_long else -1)
        ) if strategy.position else 0.0

        # Execute 5-model pipeline
        plan = evaluate(strategy, current_holding)

        # DCA / position adjustment (A-014) — called every candle when open
        strategy.qty_to_adjust = 0.0
        strategy.adjust_tag = ""
        if strategy.position is not None and strategy.position.is_open:
            try:
                adj = strategy.adjust_trade_position()
                if adj is not None:
                    delta, tag = adj
                    if delta != 0.0:
                        strategy.qty_to_adjust = delta
                        strategy.adjust_tag = tag
            except Exception:
                pass

        # Intercept with execution algorithm if configured (A-016)
        if self.exec_algo is not None:
            # QNT-2: closes and flips are never sliced (the algos' own contract) —
            # snapshot them before the clear below and restore afterward, otherwise
            # DefaultExecution.route()'s close/flip intent (encoded on these two
            # attributes) is erased and never re-created.
            _snapshot_close_at_open = strategy._close_at_open
            _snapshot_pending_flip = strategy._pending_flip

            # Clear what DefaultExecution.route set on strategy, because we will rewrite it with the slice
            strategy.buy = None
            strategy.sell = None
            strategy._pending_flip = None
            strategy._close_at_open = False

            # Plan 6 Step 6.3 phase (a): route() now returns a typed OrderPlan for
            # every path (exit/flip/maintain, not just enter), so "plan is not
            # None" alone no longer means "this is an entry to slice" — exec_algo
            # was only ever built/tested for slicing entries (QNT-2's contract
            # above). Non-entry plans fall through to the same elif/else branch
            # they used to hit when route() returned None for them.
            if plan is not None and plan.intent == "enter":
                plan = self.exec_algo.process_order_plan(plan)
            elif self.exec_algo.is_active:
                plan = self.exec_algo.step(strategy.price, candle[VOLUME])
            else:
                plan = None

            strategy._close_at_open = _snapshot_close_at_open
            strategy._pending_flip = _snapshot_pending_flip

            if plan is not None:
                # I-01: route continuation slices as an ADD when a same-direction
                # position is already open. The first slice opens the position via
                # strategy.buy/sell (which only fill while flat); every later slice
                # must go through the position-adjust path (qty_to_adjust), which
                # fills while a position is open. Without this, slices 2..N written
                # to strategy.buy/sell are silently dropped after slice 1 opens the
                # position, so the parent order only ever fills its first slice.
                pos_open = strategy.position is not None and strategy.position.is_open
                slice_into_open = pos_open and (
                    (plan.direction > 0 and strategy.position.type == "long")
                    or (plan.direction < 0 and strategy.position.type == "short")
                )
                if slice_into_open:
                    strategy.qty_to_adjust = plan.qty
                    strategy.adjust_tag = "exec_algo"
                elif plan.direction > 0:
                    strategy.buy = (plan.qty, plan.entry_price)
                elif plan.direction < 0:
                    strategy.sell = (plan.qty, plan.entry_price)

                if plan.stop_loss is not None:
                    strategy.stop_loss = (plan.qty, plan.stop_loss)
                if plan.take_profit is not None:
                    strategy.take_profit = (plan.qty, plan.take_profit)

                # Plan 6 Step 6.3 phase (d1): mirror the ACTUAL slice being
                # placed onto active_bracket, not the original parent plan
                # route() set it to — consistent with strategy.stop_loss/
                # take_profit above, which also get overwritten with the
                # slice's values here.
                strategy.active_bracket = plan

        # For live trading, execute immediately on this candle close
        if is_live:
            # Live DCA / position adjustment (A-014)
            if strategy.position is not None and strategy.qty_to_adjust != 0.0:
                delta = strategy.qty_to_adjust
                tag = strategy.adjust_tag
                strategy.qty_to_adjust = 0.0
                strategy.adjust_tag = ""
                if delta > 0:
                    await self.adapter.execute_entry(
                        strategy=strategy, symbol=symbol,
                        direction=strategy.position.type,
                        qty=delta, ref_price=strategy.price,
                        time_t=time_t, index_t=index_t,
                        intent="add", adjust_tag=tag,
                    )
                else:
                    reduce_qty = min(abs(delta), strategy.position.qty)
                    if reduce_qty < strategy.position.qty:
                        await self.adapter.execute_reduce(
                            strategy=strategy, symbol=symbol,
                            qty=reduce_qty, exit_price=strategy.price,
                            time_t=time_t, index_t=index_t,
                            adjust_tag=tag,
                        )
                    else:
                        await self.adapter.execute_exit(
                            strategy=strategy, symbol=symbol,
                            qty=strategy.position.qty,
                            exit_price=strategy.price,
                            reason="scale_out",
                            time_t=time_t, index_t=index_t,
                            high_t=candle[HIGH], low_t=candle[LOW],
                        )

            # plan.intent == "enter" is structurally implied by
            # `strategy.position is None` already (route()'s exit/flip/maintain
            # paths all require is_holding=True), but checked explicitly here too
            # (Plan 6 Step 6.3 phase (a)) since route() now returns a non-None
            # OrderPlan for those paths as well.
            if strategy.position is None and plan is not None and plan.intent == "enter":
                # Plan 6 Step 6.3 phase (b): pass the typed OrderPlan's SL/TP
                # explicitly instead of relying on the adapter reading
                # strategy.stop_loss/take_profit internally. Provably a
                # no-op here: plan.stop_loss/take_profit are the same values
                # already written to strategy.stop_loss/take_profit for this
                # exact event (see execute_entry's own comment).
                await self.adapter.execute_entry(
                    strategy=strategy,
                    symbol=symbol,
                    direction="long" if plan.direction > 0 else "short",
                    qty=plan.qty,
                    ref_price=strategy.price,
                    time_t=time_t,
                    index_t=index_t,
                    stop_loss=plan.stop_loss,
                    take_profit=plan.take_profit,
                )
            elif strategy.has_pending_flip:
                flip = strategy._pending_flip
                strategy._pending_flip = None
                await self.adapter.execute_flip(
                    strategy=strategy,
                    symbol=symbol,
                    new_direction=flip["direction"],
                    new_qty=flip["qty"],
                    ref_price=strategy.price,
                    time_t=time_t,
                    index_t=index_t,
                    high_t=candle[HIGH],
                    low_t=candle[LOW],
                    stop_loss=flip.get("stop_loss"),
                    take_profit=flip.get("take_profit"),
                )
            elif strategy._close_at_open:
                strategy._close_at_open = False
                await self.adapter.execute_exit(
                    strategy=strategy,
                    symbol=symbol,
                    qty=strategy.position.qty,
                    exit_price=strategy.price,
                    reason="strategy_exit",
                    time_t=time_t,
                    index_t=index_t,
                    high_t=candle[HIGH],
                    low_t=candle[LOW],
                )

        strategy.after()

        # Round stops and take profit prices direction-awarely (F-006 / F-007)
        direction_name = None
        if strategy.position is not None:
            direction_name = strategy.position.type
        elif strategy.buy is not None:
            direction_name = "long"
        elif strategy.sell is not None:
            direction_name = "short"

        if direction_name is not None:
            from decimal import ROUND_DOWN, ROUND_UP
            from utils.symbols import round_price
            # Stops round AWAY from entry (long→DOWN, short→UP) so rounding never
            # nudges the stop inward. I-11: the take-profit must round away from
            # entry the OTHER way (long→UP, short→DOWN) — using the stop's mode for
            # the TP nudged it toward entry (easier to hit), an optimistic bias.
            sl_rounding = ROUND_DOWN if direction_name == "long" else ROUND_UP
            tp_rounding = ROUND_UP if direction_name == "long" else ROUND_DOWN
            exchange_name = strategy.exchange or "Binance Futures"
            # Plan 6 Step 6.3 phase (d, F10 residual re-key, 2026-07-24):
            # active_bracket is now the DRIVING source for the rounding
            # decision (condition + value), not strategy.stop_loss/
            # take_profit — every route()/exec_algo write path sets both
            # together from the same source value, so active_bracket is
            # never None here while strategy.stop_loss/take_profit hold a
            # real (non-stale) value, and vice versa (see F10's investigation
            # notes in 0_fixes-queue.md for the full argument). The mutable
            # tuple is still kept in sync afterward — it remains a live read
            # surface for LiveAdapter.execute_entry's fallback and other
            # call sites not yet migrated; retiring it is a separate,
            # still-open piece of work, not attempted here.
            _ab = strategy.active_bracket
            if _ab is not None and _ab.stop_loss is not None:
                rounded_sl = round_price(symbol, exchange_name, _ab.stop_loss, rounding=sl_rounding)
                _ab.stop_loss = rounded_sl
                if strategy.stop_loss is not None:
                    strategy.stop_loss = (strategy.stop_loss[0], rounded_sl)
            if _ab is not None and _ab.take_profit is not None:
                rounded_tp = round_price(symbol, exchange_name, _ab.take_profit, rounding=tp_rounding)
                _ab.take_profit = rounded_tp
                if strategy.take_profit is not None:
                    strategy.take_profit = (strategy.take_profit[0], rounded_tp)
