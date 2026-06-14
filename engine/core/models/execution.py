"""Execution Models — the single owner of fill mechanics.

The Execution Model turns an intended trade into concrete fills. It sits one
layer above the Cost Model: a fill's slippage and fee come from
``s.cost_model`` (so cost stays the single owner of those rates), while the
Execution Model owns *assembling* a fill — adverse fill price, notional,
isolated margin and the entry-affordability test — and the env-specific way an
order is placed.

* ``DefaultExecution`` — the pipeline planner (``plan()``) plus the shared
  market-fill helpers (``entry_fill``/``exit_fill``). It is ``BaseStrategy``'s
  default ``execution_model`` and the safe fallback everywhere.
* ``BacktestExecution`` — the backtest env: market orders that fill at the next
  candle's open with adverse slippage. Inherits the shared helpers unchanged
  (the runner already calls them at ``open_t``), and is the instance the backtest
  runner routes its fills through.
* ``LiveExecution`` — the live env: real Binance market fills (no simulated
  slippage). Adds ``exit_fee`` — the realized exit-fee accounting the live
  manager applies on close. The full live entry/exit *orchestration* (rounding,
  min-notional, bracket placement, network) unifies with the pipeline in Phase 5.

``plan()`` keeps the Phase-0 behavior (delegate to ``go_long/go_short`` and read
the strategy's ``buy``/``stop_loss`` bracket) so existing strategies are
unchanged; it is consumed by the shared pipeline in Phase 5.
"""
from __future__ import annotations

from .base import ExecutionModel, OrderPlan, EntryFill, ExitFill, Signal, Target, RiskFrame


def _initial_margin(notional: float, leverage: float) -> float:
    """Isolated initial margin via the engine's margin model. Dual import root
    (strategies load under ``engine.``; services run with the engine dir on the
    path) — mirror the pattern used in risk.py/strategy.py."""
    try:
        from engine.core.margin import initial_margin
    except ImportError:  # pragma: no cover - top-level module root
        from core.margin import initial_margin
    return initial_margin(notional, leverage)


class DefaultExecution(ExecutionModel):

    # ── Shared market-fill mechanics (single owner; compose the Cost Model) ──

    def entry_fill(self, s, ref_price: float, qty: float, leverage: float,
                   side: str) -> EntryFill:
        """Assemble an opening market fill from a reference price.

        ``side`` is ``"buy"`` (long entry / short cover) or ``"sell"`` (short
        entry). Slippage and fee come from ``s.cost_model``; margin from the
        isolated-margin model. Byte-identical to the runner's former inline
        ``fill_price = adverse_fill(...); notional = qty*fill_price;
        req_margin = initial_margin(notional, lev); fee = cost_model.fee(...)``.
        """
        fill_price = s.cost_model.adverse_fill(s, ref_price, side)
        notional = qty * fill_price
        return EntryFill(
            fill_price=fill_price,
            notional=notional,
            req_margin=_initial_margin(notional, leverage),
            fee=s.cost_model.fee(s, notional),
        )

    def exit_fill(self, s, ref_price: float, qty: float, side: str) -> ExitFill:
        """Assemble a closing market fill. ``side`` is the fill direction of the
        *exit* (long exit ⇒ ``"sell"``, short exit ⇒ ``"buy"``). Byte-identical
        to the runner's former ``exit_fill = adverse_fill(...);
        fee = cost_model.fee(qty*exit_fill)``."""
        fill_price = s.cost_model.adverse_fill(s, ref_price, side)
        return ExitFill(fill_price=fill_price, fee=s.cost_model.fee(s, qty * fill_price))

    # ── Pipeline planner (consumed in Phase 5) ───────────────────────────────

    def plan(self, s, sig: Signal, target: Target, rf: RiskFrame) -> OrderPlan | None:
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
        sl = s.stop_loss[1] if s.stop_loss else None
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
    """Backtest env: market orders fill at the next candle's open with adverse
    slippage. The shared ``entry_fill``/``exit_fill`` already model this exactly
    (the runner invokes them at ``open_t``), so no override is needed."""


class LiveExecution(DefaultExecution):
    """Live env: real Binance market fills (no simulated slippage)."""

    def exit_fee(self, s, qty: float, exit_price: float) -> float:
        """Realized taker fee the live manager deducts on close
        (``qty * exit_price * fee_rate``). Routed through the Cost Model so the
        fee rate has one owner; byte-identical to the former inline calc."""
        return s.cost_model.fee(s, qty * exit_price)
