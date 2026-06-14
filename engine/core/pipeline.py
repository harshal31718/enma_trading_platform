"""Five-Model Quant Architecture — unified decision pipeline.

Routes candidate signals through the canonical quant pipeline: Alpha, Risk,
Portfolio, Cost, and Execution. Shared by both the backtest and live engines
to ensure all risk/cost gates are honored identically in all environments.
"""
from __future__ import annotations

try:
    from engine.core.models import OrderPlan
except ImportError:
    from core.models import OrderPlan


def evaluate(s) -> OrderPlan | None:
    """Evaluate strategy state through the unified decision pipeline.

    If a position is open, runs position management / updates trailing stop
    and returns None. If flat, runs Alpha -> Risk -> Portfolio -> Cost -> Execution.
    """
    if s.is_open:
        s.update_position()
        return None          # exits/trailing = Risk-managed

    sig = s.forecast()                            # 1 Alpha Model
    if sig.flat:
        return None

    rf = s.risk_model.frame(s, sig)              # 2 Risk Model
    if rf.vetoed:
        return None                              # risk circuit breaker

    tgt = s.portfolio_model.size(s, sig, rf)      # 4 Portfolio Construction Model
    cost = s.cost_model.estimate(s, tgt)          # 3 Transaction Cost Model
    if not s.cost_model.is_worth_it(s, sig, rf, cost):
        return None                              # cost hurdle gate

    return s.execution_model.plan(s, sig, tgt, rf)  # 5 Execution Model
