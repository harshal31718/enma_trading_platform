"""Transaction Cost Model — single owner of the platform's cost math.

estimate(s, sig, constraints) replaces the old estimate(s, target) signature.
Notional is estimated from the risk constraints (budget / risk_per_unit) rather
than from a sized target, so cost can be evaluated before PCM runs.

DefaultCostModel alias kept for one refactor phase.
"""
from __future__ import annotations

from .base import TransactionCostModel, CostEstimate, Cost, Signal, RiskConstraints


class DefaultTransactionCostModel(TransactionCostModel):

    # Opt-in edge-vs-cost gate strength moved to PortfolioModel._edge_beats_cost().
    min_edge_mult: float = 0.0

    # ── Realized fill mechanics (single owner of fill cost math) ─────────────

    def adverse_fill(self, s, ref_price: float, side: str) -> float:
        """Adverse slippage on a market fill of ref_price.

        buy (long entry / short cover): fills higher — ref*(1+slip).
        sell (short entry / long exit): fills lower — ref*(1-slip).
        Byte-identical to the runner's former inline arithmetic.
        """
        slip = float(getattr(s, "slippage_pct", 0.0))
        if side == "buy":
            return ref_price * (1.0 + slip)
        return ref_price * (1.0 - slip)

    def fee(self, s, notional: float) -> float:
        """Taker fee on a notional: notional * fee_rate.

        Byte-identical to the runner's former inline notional * taker_fee.
        """
        return notional * float(getattr(s, "fee_rate", 0.0))

    # ── Predictive cost estimate ──────────────────────────────────────────────

    def impact_cost(self, s, notional: float) -> float:
        """Market-impact term. Default 0.0 (opt-in; requires ADV data)."""
        return 0.0

    def estimate(self, s, sig: Signal, constraints: RiskConstraints) -> CostEstimate:
        """Expected cost of a candidate trade in quote currency.

        Notional is estimated from risk constraints rather than a sized target so
        cost can be computed before PCM runs. With min_edge_mult=0 (default) the
        returned value only matters for strategies that override min_edge_mult > 0.
        """
        if sig.direction == 0 or constraints.risk_per_unit <= 0 or s.price <= 0:
            return CostEstimate()
        qty_est = min(
            constraints.budget / constraints.risk_per_unit,
            constraints.max_notional / s.price,
        )
        notional = abs(qty_est) * s.price
        slip = float(getattr(s, "slippage_pct", 0.0))
        return CostEstimate(
            fee=self.fee(s, notional),
            slippage=notional * slip,
            impact=self.impact_cost(s, notional),
        )

    # ── Deprecated gate (moved to PortfolioModel._edge_beats_cost) ───────────

    def is_worth_it(self, s, sig: Signal, rf: RiskConstraints, cost: CostEstimate) -> bool:
        """Deprecated. Gate logic now lives in DefaultPortfolioModel._edge_beats_cost().

        Kept only for any call sites in legacy runners that have not been updated
        to the new pipeline. Always returns True (permissive) unless min_edge_mult
        is set — matching the former default behavior.
        """
        if self.min_edge_mult <= 0.0:
            return s.alpha_beats_cost(float(sig.direction))
        rrr = float(getattr(s, "rrr", 1.0))
        edge = abs(sig.conviction) * rf.risk_per_unit * rrr
        return edge >= self.min_edge_mult * cost.total and s.alpha_beats_cost(float(sig.direction))


# Backward-compat alias — remove in Phase 6 cleanup
DefaultCostModel = DefaultTransactionCostModel
