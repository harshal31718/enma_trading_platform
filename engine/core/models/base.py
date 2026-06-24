"""Five-Model Quant Architecture — contracts and value objects (Narang strict boundary).

Value objects passed between models:
  Signal → RiskConstraints → CostEstimate → TargetPortfolio → OrderPlan

Deprecated aliases kept for one refactor phase:
  RiskFrame = RiskConstraints, Cost = CostEstimate, Target = TargetPortfolio,
  TransactionCostModel = CostModel
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


# ─────────────────────────────────────────────────────────────────────────────
# Value objects
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Signal:
    """Alpha Model output: prediction for one candle.

    direction: +1 long, -1 short, 0 flat.
    magnitude: predicted move as decimal fraction (e.g. 0.02 = 2%). Feeds
               the PCM edge-vs-cost veto when min_edge_mult > 0.
    conviction: strength in [0, 1]; 1.0 reproduces legacy boolean signal.
    asset / timeframe: filled by forecast() for multi-asset pipelines.
    ref_price: close at forecast time (entry reference, internal).
    """
    direction: int = 0
    magnitude: float = 0.0
    conviction: float = 1.0
    timeframe: str = ""
    ref_price: float = 0.0
    asset: str = ""

    @property
    def flat(self) -> bool:
        return self.direction == 0


@dataclass
class RiskConstraints:
    """Risk Model output: the trade's risk envelope.

    vetoed: True blocks the entry (drawdown breaker or invalid stop).
    max_drawdown_hit: True specifically when the drawdown circuit breaker fired.
    stop_price: structural stop for this trade; None if no protective stop.
    take_profit_price: structural take-profit; None if signal-driven or pure trail.
    risk_per_unit: |entry - stop| — the per-unit risk (0 if no stop).
    budget: capital permitted at risk (equity * risk_pct).
    max_notional: hard exposure cap (equity * leverage or max_leverage).
    """
    vetoed: bool = False
    max_drawdown_hit: bool = False
    stop_price: float | None = None
    take_profit_price: float | None = None
    risk_per_unit: float = 0.0
    budget: float = 0.0
    max_notional: float = 0.0


# Deprecated alias — remove in Phase 6 cleanup
RiskFrame = RiskConstraints


@dataclass
class CostEstimate:
    """Transaction Cost Model estimate for a candidate trade."""
    fee: float = 0.0
    slippage: float = 0.0
    impact: float = 0.0

    @property
    def total(self) -> float:
        return self.fee + self.slippage + self.impact


# Deprecated alias — remove in Phase 6 cleanup
Cost = CostEstimate


@dataclass
class TargetPortfolio:
    """Portfolio Construction Model output: desired (signed) position.

    qty: SIGNED desired quantity (+long, -short, 0 flat).
    weight: |qty * price| / equity (for cross-asset allocation).
    asset: symbol this target applies to.
    """
    asset: str = ""
    qty: float = 0.0
    weight: float = 0.0


# Deprecated alias — remove in Phase 6 cleanup
Target = TargetPortfolio


@dataclass
class OrderPlan:
    """Execution Model output: the concrete order to send.

    direction: +1 long, -1 short (derived from target sign in route()).
    """
    direction: int
    qty: float
    entry_price: float
    stop_loss: float | None = None
    take_profit: float | None = None
    order_type: str = "market"


@dataclass
class EntryFill:
    """Opening market fill: slippage-adjusted fill_price, notional,
    isolated req_margin, and taker fee. affordable() is the entry-rejection test."""
    fill_price: float
    notional: float
    req_margin: float
    fee: float

    def affordable(self, balance: float) -> bool:
        return self.req_margin + self.fee <= balance


@dataclass
class ExitFill:
    """Closing market fill: slippage-adjusted fill_price and taker fee."""
    fill_price: float
    fee: float


# ─────────────────────────────────────────────────────────────────────────────
# Model interfaces (ABCs)
# ─────────────────────────────────────────────────────────────────────────────

class RiskModel(ABC):
    """Stop placement, per-trade budget, drawdown breaker, trailing, and
    liquidation-buffer guard.  assess() is the primary contract.

    Concrete helpers (update_session_risk, atr_stop, risk_budget_qty) are the
    single owners of the platform's drawdown-tracking, stop-placement and
    risk-budget sizing math — shared across backtest, live, and all variants.
    """

    @abstractmethod
    def can_trade(self, s) -> bool:
        """False halts new entries (position management still runs)."""

    @abstractmethod
    def assess(self, s, sig: Signal, current_holding: float = 0.0) -> RiskConstraints:
        """Build the risk envelope for a signal or an open position.

        Called every candle by the pipeline. When current_holding != 0 the
        model also handles trailing (updating stop_price) so the runner's
        existing bracket fields always reflect the latest constraints.
        """

    def frame(self, s, sig: Signal) -> RiskConstraints:
        """Deprecated shim → assess(s, sig, 0.0). Remove in Phase 6."""
        return self.assess(s, sig, 0.0)

    # ── Concrete helpers (single owners of platform risk math) ──────────────

    def update_session_risk(self, s, equity: float | None = None) -> None:
        """Track session peak equity and drawdown for the can_trade() gate."""
        eq = s.equity if equity is None else equity
        if eq > s.peak_equity:
            s.peak_equity = eq
        if s.peak_equity > 0:
            s.session_drawdown = (s.peak_equity - eq) / s.peak_equity

    def atr_stop(self, s, direction: str, mult: float = 2.0, period: int = 14,
                 entry_price: float | None = None) -> float:
        """ATR-based stop: long = entry − mult·ATR, short = entry + mult·ATR."""
        entry = entry_price if entry_price is not None else s.price
        atr = s._atr(period)
        
        vol_mult = float(getattr(s, "volatility_multiplier", 1.0))
        mult = mult * vol_mult
        
        return entry - mult * atr if direction == "long" else entry + mult * atr

    def risk_budget_qty(self, s, stop_price: float, risk_pct: float | None = None,
                        entry_price: float | None = None) -> float:
        """Qty such that hitting stop_price loses risk_pct of equity (rule #6)."""
        entry = entry_price if entry_price is not None else s.price
        if risk_pct is None:
            risk_pct = float(getattr(s, "risk_pct", 0.01))
        per_unit = abs(entry - stop_price)
        if per_unit <= 0 or entry <= 0:
            return 0.0
        qty = (s.equity * risk_pct) / per_unit
        return min(qty, s.max_qty(entry))


class TransactionCostModel(ABC):
    """Predicts execution cost (fee + slippage + impact) — descriptive only.

    The edge-vs-cost veto decision lives in PortfolioModel.construct().
    """

    min_edge_mult: float = 0.0   # 0 = veto off (golden-master default)

    @abstractmethod
    def estimate(self, s, sig: Signal, constraints: RiskConstraints) -> CostEstimate:
        """Expected cost of a candidate trade; used by PCM for the edge gate."""


# Deprecated alias — remove in Phase 6 cleanup
CostModel = TransactionCostModel


class PortfolioModel(ABC):
    """Combines Alpha conviction, Risk budget and Cost into a signed target.

    construct() is the primary contract. allocate() splits capital cross-symbol.
    """

    @abstractmethod
    def construct(self, s, sig: Signal, constraints: RiskConstraints,
                  cost: CostEstimate, current_holding: float = 0.0) -> TargetPortfolio:
        """Build the desired signed position target for this candle."""

    def allocate(self, total_capital: float, symbols: list[str]) -> dict[str, float]:
        """Split total_capital across symbols. Default: equal weight."""
        n = len(symbols)
        if n == 0:
            return {}
        per_symbol = total_capital / n
        return {sym: per_symbol for sym in symbols}

    def size(self, s, sig: Signal, rf: RiskConstraints) -> TargetPortfolio:
        """Deprecated shim — calls construct() with empty cost. Remove in Phase 6."""
        from .base import CostEstimate as _CE
        return self.construct(s, sig, rf, _CE(), 0.0)


class ExecutionModel(ABC):
    """Sole writer of order state (buy/sell/stop_loss/take_profit/_pending_flip/
    _close_at_open). Flips and closes are implicit from target vs current_holding.
    """

    @abstractmethod
    def route(self, s, target: TargetPortfolio, current_holding: float = 0.0,
              constraints: RiskConstraints | None = None) -> OrderPlan | None:
        """Diff desired target against current_holding and write the order state."""
