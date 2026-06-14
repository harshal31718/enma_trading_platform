"""Five-Model Quant Architecture — contracts and value objects.

Defines the canonical quant model interfaces (Alpha is the strategy itself;
Risk / Cost / Portfolio / Execution are pluggable) and the immutable value
objects passed between them in the shared decision pipeline.

This module is pure-Python (stdlib only) — it never imports numpy, TA-Lib, or
any strategy, so it can be imported and unit-tested without the engine runtime.
Each model receives the strategy instance ``s`` as its first argument and reads
state through the existing BaseStrategy properties/helpers; the models hold no
candle state of their own.

See plan.md for the rollout phases. Phase 0 ships these contracts plus
default implementations; the engines are wired to the pipeline in a later phase.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


# ─────────────────────────────────────────────────────────────────────────────
# Value objects — passed down the pipeline (Alpha → Risk → Portfolio → Cost → Execution)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Signal:
    """Alpha Model output for one candle.

    direction: +1 long, -1 short, 0 flat.
    conviction: strength in [0, 1] — 1.0 reproduces the legacy boolean signal.
    ref_price: price the forecast was made at (entry reference).
    """
    direction: int
    conviction: float = 1.0
    ref_price: float = 0.0

    @property
    def flat(self) -> bool:
        return self.direction == 0


@dataclass
class RiskFrame:
    """Risk Model output: the trade's risk envelope.

    vetoed: True to block the entry (circuit breaker / invalid stop).
    stop_price: structural stop for this trade (None if undefined).
    risk_per_unit: |entry - stop| — the volatility-scaled risk of one unit.
    budget: capital permitted at risk for this trade (equity * risk_pct).
    max_notional: hard exposure cap (equity * leverage).
    """
    vetoed: bool = False
    stop_price: float | None = None
    risk_per_unit: float = 0.0
    budget: float = 0.0
    max_notional: float = 0.0


@dataclass
class Cost:
    """Transaction Cost Model estimate for a candidate trade."""
    fee: float = 0.0
    slippage: float = 0.0
    impact: float = 0.0

    @property
    def total(self) -> float:
        return self.fee + self.slippage + self.impact


@dataclass
class Target:
    """Portfolio Construction Model output: desired position size."""
    qty: float = 0.0
    weight: float = 0.0


@dataclass
class OrderPlan:
    """Execution Model output: the concrete order(s) to send.

    Phase 0 models a single market/limit order with an attached SL/TP bracket,
    matching what the engines execute today. Slicing/routing fields are added in
    the Execution phase.
    """
    direction: int
    qty: float
    entry_price: float
    stop_loss: float | None = None
    take_profit: float | None = None
    order_type: str = "market"


@dataclass
class EntryFill:
    """Execution Model output for an opening market fill.

    The slippage-adjusted ``fill_price``, the resulting ``notional`` and isolated
    ``req_margin``, and the ``fee`` charged. ``affordable`` is the runner's
    entry-rejection predicate (``req_margin + fee <= balance``).
    """
    fill_price: float
    notional: float
    req_margin: float
    fee: float

    def affordable(self, balance: float) -> bool:
        return self.req_margin + self.fee <= balance


@dataclass
class ExitFill:
    """Execution Model output for a closing market fill: slippage-adjusted
    ``fill_price`` and the ``fee`` charged."""
    fill_price: float
    fee: float


# ─────────────────────────────────────────────────────────────────────────────
# Model interfaces
# ─────────────────────────────────────────────────────────────────────────────

class RiskModel(ABC):
    """Estimates risk and gates exposure: stop placement, per-trade budget,
    drawdown circuit breaker, liquidation-buffer and exposure caps.

    ``can_trade`` and ``frame`` are the abstract contract. The concrete helpers
    below (``update_session_risk``, ``atr_stop``, ``risk_budget_qty``) are the
    single owners of the platform's drawdown-tracking, stop-placement and
    risk-budget sizing math — relocated here in the Risk phase so backtest, live
    and the BaseStrategy helpers all route through one implementation. Each takes
    the strategy ``s`` and reads its public surface; they hold no candle state.
    """

    @abstractmethod
    def can_trade(self, s) -> bool:
        """False halts new entries (position management still runs)."""

    @abstractmethod
    def frame(self, s, sig: Signal) -> RiskFrame:
        """Build the risk envelope for a candidate signal."""

    # ── Concrete defaults (inherited by every RiskModel) ────────────────────

    def update_session_risk(self, s, equity: float | None = None) -> None:
        """Track session peak equity and drawdown for the ``can_trade`` gate.

        Relocated verbatim from the backtest runner's per-candle equity block so
        the Risk Model is the sole owner of drawdown state; both engines call
        this once per candle. ``equity`` defaults to ``s.equity``. Math is
        identical to the former inline block (no behavior change).
        """
        eq = s.equity if equity is None else equity
        if eq > s.peak_equity:
            s.peak_equity = eq
        if s.peak_equity > 0:
            s.session_drawdown = (s.peak_equity - eq) / s.peak_equity

    def atr_stop(self, s, direction: str, mult: float = 2.0, period: int = 14,
                 entry_price: float | None = None) -> float:
        """ATR-based stop price. long: entry - mult*ATR, short: entry + mult*ATR.

        Canonical owner of ``BaseStrategy.atr_stop`` (which delegates here).
        """
        entry = entry_price if entry_price is not None else s.price
        atr = s._atr(period)
        if direction == "long":
            return entry - mult * atr
        return entry + mult * atr

    def risk_budget_qty(self, s, stop_price: float, risk_pct: float | None = None,
                        entry_price: float | None = None) -> float:
        """Quantity such that hitting ``stop_price`` loses ``risk_pct`` of equity
        (platform rule #6: ``(equity*risk_pct)/|entry-stop|``), capped by
        ``s.max_qty``. Canonical owner of ``BaseStrategy.size_by_risk``.
        """
        entry = entry_price if entry_price is not None else s.price
        if risk_pct is None:
            risk_pct = float(getattr(s, "risk_pct", 0.01))
        per_unit = abs(entry - stop_price)
        if per_unit <= 0 or entry <= 0:
            return 0.0
        qty = (s.equity * risk_pct) / per_unit
        return min(qty, s.max_qty(entry))


class CostModel(ABC):
    """Predicts execution cost (fee + slippage + impact) and vetoes trades
    whose expected edge does not beat their expected cost."""

    @abstractmethod
    def estimate(self, s, target: Target) -> Cost:
        """Expected round-trip-relevant cost of trading ``target``."""

    @abstractmethod
    def is_worth_it(self, s, sig: Signal, rf: RiskFrame, cost: Cost) -> bool:
        """True if expected edge justifies the estimated cost."""


class PortfolioModel(ABC):
    """Combines Alpha conviction, Risk budget and Cost into a position size,
    and (across symbols) splits a session's capital between them.

    ``size`` is the abstract per-trade contract. ``allocate`` is a concrete,
    inherited default: it is the single owner of the live session's cross-symbol
    capital split (relocated from ``live_bot_manager``'s inline
    ``capital/len(symbols)``), so a custom PortfolioModel can re-weight every
    symbol at once. The default is an equal split, byte-identical to the former
    inline math.
    """

    @abstractmethod
    def size(self, s, sig: Signal, rf: RiskFrame) -> Target:
        """Desired quantity/weight for this signal."""

    def allocate(self, total_capital: float, symbols: list[str]) -> dict[str, float]:
        """Split ``total_capital`` across ``symbols`` for a live session.

        Default: equal weight — each symbol receives ``total_capital / n``,
        identical to the former ``float(capital) / len(symbols)``. Override to
        weight by conviction, volatility or a target risk-parity allocation; the
        live manager consumes whatever mapping is returned.
        """
        n = len(symbols)
        if n == 0:
            return {}
        per_symbol = total_capital / n
        return {sym: per_symbol for sym in symbols}


class ExecutionModel(ABC):
    """Turns a target position into concrete orders (type, slicing, routing)."""

    @abstractmethod
    def plan(self, s, sig: Signal, target: Target, rf: RiskFrame) -> OrderPlan | None:
        """Build the order plan, or None to place nothing."""
