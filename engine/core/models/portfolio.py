"""Default Portfolio Construction Model.

Two responsibilities (Phase 3):

* **Per-trade sizing** — ``size`` does risk-budget sizing scaled by Alpha
  conviction. With the default unit-conviction Signal it is identical to
  ``BaseStrategy.size_by_risk(stop)``: ``qty = budget / risk_per_unit`` capped by
  ``max_qty`` (leverage). Continuous conviction in [0, 1] scales it linearly.
  This wires into the engines via the shared pipeline in Phase 5; until then the
  backtest runner sizes inside each strategy's ``go_long/go_short`` (so Phase 3
  changes no backtest numbers).
* **Cross-symbol allocation** — ``allocate`` (inherited from ``PortfolioModel``)
  splits a live session's capital across its symbols. The default equal split is
  byte-identical to the live manager's former ``capital/len(symbols)``; this
  phase makes the Portfolio Model its single owner so a custom model can
  re-weight by conviction/volatility without touching the live manager.
"""
from __future__ import annotations

from .base import PortfolioModel, Target, Signal, RiskFrame


class DefaultPortfolioModel(PortfolioModel):

    def size(self, s, sig: Signal, rf: RiskFrame) -> Target:
        if rf.stop_price is None:
            return Target(qty=0.0, weight=0.0)
        conviction = max(0.0, min(float(sig.conviction), 1.0))
        # Reuse the centralized risk-sizing helper so numbers match the engine.
        qty = s.size_by_risk(rf.stop_price) * conviction
        weight = (qty * s.price) / s.equity if s.equity > 0 else 0.0
        return Target(qty=qty, weight=weight)
