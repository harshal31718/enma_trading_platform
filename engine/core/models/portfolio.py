"""Portfolio Construction Models — size the target position.

DefaultPortfolioModel — default risk-budget sizing (legacy-equivalent).
RiskBudgetPortfolio   — min(budget/risk_per_unit, max_notional/price) × conviction.
NotionalPortfolio     — equity × position_size_pct / price (BestSupertrend).

construct() is the primary contract. _size() is the internal sizing hook
that subclasses override; PortfolioModel.size() (deprecated shim on the ABC)
is not overridden and continues to call construct() via the ABC.
"""
from __future__ import annotations

from .base import (
    PortfolioModel, TargetPortfolio, Target, Signal, RiskConstraints, CostEstimate,
)


class DefaultPortfolioModel(PortfolioModel):
    """Combines veto checks, maintain logic, edge gate and sizing into one call.

    construct() implements the full five-path decision tree:
      flat+no-signal  → qty=0
      holding+same    → maintain current holding (no re-size)
      vetoed          → qty=0 (flat) or current_holding (holding, don't force close)
      edge-veto       → same as vetoed
      new/flip        → _size() → signed target
    """

    # Edge gate strength. Subclasses may override. 0.0 = always trade (default).
    min_edge_mult: float = 0.0

    def construct(
        self, s, sig: Signal, constraints: RiskConstraints,
        cost: CostEstimate, current_holding: float = 0.0,
    ) -> TargetPortfolio:
        is_holding = current_holding != 0.0
        same_dir = (
            (sig.direction > 0 and current_holding > 0) or
            (sig.direction < 0 and current_holding < 0)
        )

        # Flat/close signal
        if sig.direction == 0:
            return TargetPortfolio(qty=0.0)

        # Maintain: don't re-size an existing position in the same direction
        if is_holding and same_dir:
            return TargetPortfolio(qty=current_holding)

        # Risk veto — halts new entries and flips, but never force-closes
        if constraints.vetoed:
            return TargetPortfolio(qty=current_holding) if is_holding else TargetPortfolio(qty=0.0)

        # Edge-vs-cost gate (only blocks new entries/flips)
        if not self._edge_beats_cost(s, sig, constraints, cost):
            return TargetPortfolio(qty=current_holding) if is_holding else TargetPortfolio(qty=0.0)

        # Size the position (new entry or flip)
        raw_qty = self._size(s, sig, constraints)
        if raw_qty <= 0:
            return TargetPortfolio(qty=current_holding) if is_holding else TargetPortfolio(qty=0.0)

        # Portfolio exposure cap: veto if this position's risk exceeds max_portfolio_risk × equity.
        # Default 0.06 (6%). With risk_pct=0.01, new_risk_pct≈0.01 << 0.06 → never triggered
        # at default settings → golden-master safe. Only bites when risk_pct > max_portfolio_risk.
        max_port_risk = float(getattr(s, "max_portfolio_risk", 0.06))
        if max_port_risk > 0 and s.equity > 0 and constraints.risk_per_unit > 0:
            new_risk_pct = (constraints.risk_per_unit * raw_qty) / s.equity
            if new_risk_pct > max_port_risk:
                return TargetPortfolio(qty=current_holding) if is_holding else TargetPortfolio(qty=0.0)

        signed_qty = raw_qty * sig.direction
        weight = abs(signed_qty * s.price) / s.equity if s.equity > 0 else 0.0
        return TargetPortfolio(qty=signed_qty, weight=weight)

    def _size(self, s, sig: Signal, constraints: RiskConstraints) -> float:
        """Default risk-budget sizing. Byte-identical to the old size() behavior:
        (equity * risk_pct) / risk_per_unit, capped by max_qty() / leverage."""
        if constraints.stop_price is None:
            return 0.0
        conviction = max(0.0, min(float(sig.conviction), 1.0))
        return s.size_by_risk(constraints.stop_price) * conviction

    def _edge_beats_cost(
        self, s, sig: Signal, constraints: RiskConstraints, cost: CostEstimate,
    ) -> bool:
        """Returns False when estimated cost exceeds min_edge_mult × expected edge.

        Default min_edge_mult=0.0 → always True (never veto). Override in a
        subclass or set on an instance to opt in to the cost gate.
        """
        # Always honor strategy cost vetoes
        if not s.alpha_beats_cost(float(sig.direction)):
            return False

        mult = float(getattr(self, "min_edge_mult", 0.0))
        if mult <= 0.0:
            return True
        rrr  = float(getattr(s, "rrr", 2.0))
        edge = abs(sig.conviction) * constraints.risk_per_unit * rrr
        return edge >= mult * cost.total


class RiskBudgetPortfolio(DefaultPortfolioModel):
    """Risk-budget sizing: size = min(budget/risk_per_unit, max_notional/price) × conviction.

    Used by MicroScalper, MicroMacroRSIDivergence, MultiDivergence (via AtrBracketRiskModel)
    and AdaptiveTrend (via ChandelierRiskModel with max_notional = equity * min(max_leverage, lev)).

    Golden-master equivalent to the old _position_qty() and size_by_risk() calls
    in each strategy's go_long/go_short, because:
      budget      = equity * risk_pct
      risk_per_unit = |price - stop|
      max_notional = equity * leverage  (or equity * min(max_leverage, lev) for Chandelier)
      → min(budget/rpu, max_notional/price) × 1.0 = old min(qty, lev_cap, max_qty)
    """

    def _size(self, s, sig: Signal, constraints: RiskConstraints) -> float:
        if constraints.risk_per_unit <= 0 or constraints.budget <= 0 or s.price <= 0:
            return 0.0
        conviction = max(0.0, min(float(sig.conviction), 1.0))
        qty_by_risk     = constraints.budget / constraints.risk_per_unit
        qty_by_notional = constraints.max_notional / s.price
        return min(qty_by_risk, qty_by_notional) * conviction


class NotionalPortfolio(DefaultPortfolioModel):
    """Notional sizing: equity × position_size_pct / price. Used by BestSupertrend.

    Golden-master equivalent to BestSupertrend's go_long/go_short calling
    self.size_by_notional(self.position_size_pct) directly.
    """

    def _size(self, s, sig: Signal, constraints: RiskConstraints) -> float:
        conviction = max(0.0, min(float(sig.conviction), 1.0))
        pct = float(getattr(s, "position_size_pct", 0.1))
        return s.size_by_notional(pct) * conviction
