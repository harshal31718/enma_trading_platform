"""Five-Model Quant Architecture — unified every-candle decision pipeline.

evaluate() runs all five models on every candle, regardless of position state.
forecast() handles the is_open check internally (maintain/exit/flip while holding;
entry logic while flat). The old guard `if s.is_open: update_position(); return`
is gone — the pipeline is now unconditional.

Call sites must pass current_holding as a signed quantity:
  current_holding = (position.qty * (1 if is_long else -1)) if position else 0.0
"""
from __future__ import annotations

try:
    from engine.core.models import OrderPlan
except ImportError:
    from core.models import OrderPlan


def evaluate(s, current_holding: float = 0.0) -> "OrderPlan | None":
    """Run the five-model pipeline for one candle.

    Flow: forecast → assess → estimate → construct → route.
    All five models run every candle; no early return for open positions.
    """
    sig         = s.forecast()                                          # 1 Alpha
    constraints = s.risk_model.assess(s, sig, current_holding)         # 2 Risk
    cost        = s.cost_model.estimate(s, sig, constraints)           # 3 TCM
    target      = s.portfolio_model.construct(s, sig, constraints,     # 4 PCM
                                              cost, current_holding)
    return s.execution_model.route(s, target, current_holding,         # 5 Execution
                                   constraints)
