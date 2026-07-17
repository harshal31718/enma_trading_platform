"""Execution Models — sole writer of order state and fill mechanics.

route() is the primary contract (Narang strict boundary: strategies never write
buy/sell/stop_loss/take_profit/_pending_flip/_close_at_open directly).

Paths in route():
  1. flat  → flat:          no-op
  2. hold  → flat (close):  _close_at_open = True
  3. flat  → enter:         write buy/sell + bracket
  4. hold  → flip:          flip_position()
  5. hold  → maintain:      refresh bracket from constraints (handles trailing)

DCA scale-in/out (A-014) is handled externally by evaluate_and_route():
the strategy's adjust_trade_position() hook sets qty_to_adjust on the
strategy object, which the adapter processes as a separate order. route()
itself does not handle DCA — Path 5 covers the bracket refresh that follows.
"""
from __future__ import annotations

from .base import (
    ExecutionModel, OrderPlan, EntryFill, ExitFill,
    Signal, TargetPortfolio, Target, RiskConstraints,
)


def _initial_margin(notional: float, leverage: float) -> float:
    try:
        from engine.core.margin import initial_margin
    except ImportError:  # pragma: no cover - top-level module root
        from core.margin import initial_margin
    return initial_margin(notional, leverage)


class DefaultExecution(ExecutionModel):

    # ── Shared market-fill mechanics ─────────────────────────────────────────

    def entry_fill(self, s, ref_price: float, qty: float, leverage: float,
                   side: str) -> EntryFill:
        """Opening market fill. Slippage and fee come from s.cost_model.
        Byte-identical to the runner's former inline fill arithmetic."""
        fill_price = s.cost_model.adverse_fill(s, ref_price, side)
        notional   = qty * fill_price
        return EntryFill(
            fill_price=fill_price,
            notional=notional,
            req_margin=_initial_margin(notional, leverage),
            fee=s.cost_model.fee(s, notional),
        )

    def exit_fill(self, s, ref_price: float, qty: float, side: str) -> ExitFill:
        """Closing market fill. side is the exit direction ("sell" for long exit)."""
        fill_price = s.cost_model.adverse_fill(s, ref_price, side)
        return ExitFill(fill_price=fill_price, fee=s.cost_model.fee(s, qty * fill_price))

    # ── Primary contract: route target → order state ──────────────────────────

    def route(
        self, s, target: TargetPortfolio, current_holding: float = 0.0,
        constraints: RiskConstraints | None = None,
    ) -> OrderPlan | None:
        """Diff desired target against current_holding and write the order state.

        This is the sole place that assigns s.buy, s.sell, s.stop_loss,
        s.take_profit, s._pending_flip, or s._close_at_open. Strategies and
        models must NOT write these fields.
        """
        desired    = target.qty
        is_holding = current_holding != 0.0
        same_sign  = (desired > 0 and current_holding > 0) or (desired < 0 and current_holding < 0)

        # Path 1: flat → flat
        if desired == 0.0 and not is_holding:
            return None

        # Path 2: holding → flat (guaranteed next-open close; see BUG-03)
        if desired == 0.0 and is_holding:
            s._close_at_open = True
            return None

        # Path 5: maintain bracket (same direction, holding)
        if is_holding and same_sign:
            if constraints is not None:
                if constraints.stop_price is not None and s.stop_loss is not None:
                    s.stop_loss = s.stop_loss[0], constraints.stop_price
                if constraints.take_profit_price is not None and s.take_profit is not None:
                    s.take_profit = s.take_profit[0], constraints.take_profit_price
            return None

        sl  = constraints.stop_price        if constraints else None
        tp  = constraints.take_profit_price if constraints else None
        qty = abs(desired)
        direction = 1 if desired > 0 else -1

        # Path 4: flip (holding, opposite direction)
        if is_holding and not same_sign:
            s.flip_position(qty, stop_loss=sl, take_profit=tp)
            return None

        # Path 3: flat → enter
        if desired > 0:
            s.buy = qty, s.price
            if sl is not None:
                s.stop_loss   = qty, sl
            if tp is not None:
                s.take_profit = qty, tp
        else:
            s.sell = qty, s.price
            if sl is not None:
                s.stop_loss   = qty, sl
            if tp is not None:
                s.take_profit = qty, tp

        return OrderPlan(
            direction=direction,
            qty=qty,
            entry_price=s.price,
            stop_loss=sl,
            take_profit=tp,
            order_type=getattr(s, "order_type", "market"),
        )

    # ── Deprecated plan() shim ────────────────────────────────────────────────

    def plan(self, s, sig: Signal, target: TargetPortfolio, rf: RiskConstraints) -> OrderPlan | None:
        """Deprecated — delegates to legacy go_long/go_short for call sites that
        have not yet been updated to the route()-based pipeline. Remove in Phase 6."""
        if sig.direction > 0:
            s.go_long()
            order = s.buy
        elif sig.direction < 0:
            s.go_short()
            order = s.sell
        else:
            return None
        if order is None:
            return None
        qty, price = order
        sl = s.stop_loss[1]   if s.stop_loss   else None
        tp = s.take_profit[1] if s.take_profit else None
        return OrderPlan(
            direction=sig.direction,
            qty=qty,
            entry_price=price,
            stop_loss=sl,
            take_profit=tp,
            order_type=getattr(s, "order_type", "market"),
        )


class BacktestExecution(DefaultExecution):
    """Backtest env: fills at next candle's open with adverse slippage.

    The shared entry_fill/exit_fill already model this (runner invokes them at
    open_t). route() and plan() inherit from DefaultExecution unchanged.
    """


class LiveExecution(DefaultExecution):
    """Live env: real Binance market fills (no simulated slippage)."""

    def exit_fee(self, s, qty: float, exit_price: float) -> float:
        """Realized taker fee on close. Routed through cost_model for one owner."""
        return s.cost_model.fee(s, qty * exit_price)
