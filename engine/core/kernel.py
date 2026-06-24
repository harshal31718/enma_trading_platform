"""Unified execution loop driver kernel (F-024).

Implements the Callback/Adapter pattern via ``ExecutionAdapter`` and
the core state transition machine ``ExecutionKernel``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import numpy as np

try:
    from engine.core.models import OrderPlan
    from engine.core.position import Position
    from engine.core.pipeline import evaluate
    from services.fill_model import gap_through_stop_price, bounded_exit_price
except ImportError:
    from core.models import OrderPlan
    from core.position import Position
    from core.pipeline import evaluate
    from services.fill_model import gap_through_stop_price, bounded_exit_price


class ExecutionAdapter(ABC):
    """Abstract base class for execution adapters (backtest vs live)."""

    @abstractmethod
    async def execute_entry(
        self, strategy, symbol: str, direction: str, qty: float, ref_price: float,
        time_t: datetime, index_t: int, intent: str = "enter", adjust_tag: str = "",
    ) -> bool:
        """Execute a market entry order. Returns True if entered.

        intent: "enter" for new position, "add" for DCA scale-in.
        adjust_tag: label from strategy.adjust_trade_position() for per-tag analytics.
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

    def __init__(self, adapter: ExecutionAdapter, exec_algo=None) -> None:
        self.adapter = adapter
        self.exec_algo = exec_algo

    async def execute_pending(self, strategy, symbol: str, candle: np.ndarray, index_t: int, time_t: datetime) -> None:
        """Simulates next-open fills for orders placed on the previous candle (backtest only)."""
        open_t = candle[1]
        high_t = candle[3]
        low_t = candle[4]

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
        self, strategy, symbol: str, candle: np.ndarray, is_live: bool, index_t: int, time_t: datetime
    ) -> None:
        """Verify position on exchange and check SL/TP/liquidation triggers."""
        if not is_live and getattr(strategy, "_entered_this_candle", False):
            return

        if strategy.position is None:
            return

        open_t = candle[1]
        close_t = candle[2]
        high_t = candle[3]
        low_t = candle[4]

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

        if not closed:
            if strategy.is_long:
                sl = strategy.stop_loss
                tp = strategy.take_profit
                if sl is not None:
                    _, sl_price = sl
                    if low_t <= sl_price:
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
                if not closed and tp is not None:
                    _, tp_price = tp
                    if high_t >= tp_price:
                        exit_price = tp_price
                        exit_reason = "take_profit"
                        closed = True
            elif strategy.is_short:
                sl = strategy.stop_loss
                tp = strategy.take_profit
                if sl is not None:
                    _, sl_price = sl
                    if high_t >= sl_price:
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
                if not closed and tp is not None:
                    _, tp_price = tp
                    if low_t <= tp_price:
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
        self, strategy, symbol: str, candle: np.ndarray, is_live: bool, index_t: int, time_t: datetime
    ) -> None:
        """Runs prepare, before, evaluate, execution algorithms, routes and runs after hooks."""
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
            # Clear what DefaultExecution.route set on strategy, because we will rewrite it with the slice
            strategy.buy = None
            strategy.sell = None
            strategy._pending_flip = None
            strategy._close_at_open = False

            if plan is not None:
                plan = self.exec_algo.process_order_plan(plan)
            elif self.exec_algo.is_active:
                plan = self.exec_algo.step(strategy.price, candle[5])
            else:
                plan = None

            if plan is not None:
                if plan.direction > 0:
                    strategy.buy = (plan.qty, plan.entry_price)
                elif plan.direction < 0:
                    strategy.sell = (plan.qty, plan.entry_price)

                if plan.stop_loss is not None:
                    strategy.stop_loss = (plan.qty, plan.stop_loss)
                if plan.take_profit is not None:
                    strategy.take_profit = (plan.qty, plan.take_profit)

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
                            high_t=candle[3], low_t=candle[4],
                        )

            if strategy.position is None and plan is not None:
                await self.adapter.execute_entry(
                    strategy=strategy,
                    symbol=symbol,
                    direction="long" if plan.direction > 0 else "short",
                    qty=plan.qty,
                    ref_price=strategy.price,
                    time_t=time_t,
                    index_t=index_t,
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
                    high_t=candle[3],
                    low_t=candle[4],
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
                    high_t=candle[3],
                    low_t=candle[4],
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
            rounding_mode = ROUND_DOWN if direction_name == "long" else ROUND_UP
            exchange_name = strategy.exchange or "Binance Futures"
            if strategy.stop_loss is not None:
                sl_qty, sl_price = strategy.stop_loss
                strategy.stop_loss = (
                    sl_qty,
                    round_price(symbol, exchange_name, sl_price, rounding=rounding_mode),
                )
            if strategy.take_profit is not None:
                tp_qty, tp_price = strategy.take_profit
                strategy.take_profit = (
                    tp_qty,
                    round_price(symbol, exchange_name, tp_price, rounding=rounding_mode),
                )
