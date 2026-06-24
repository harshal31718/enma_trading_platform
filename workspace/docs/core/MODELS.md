# Five-Model Quant Architecture & Decision Pipeline

Enma implements a modular, pluggable quant architecture that splits strategy logic, risk checks, portfolio construction, transaction cost estimation, and order execution into separate objects.

Both the backtest engine (`backtest_runner.py`) and live trading engine (`live_bot_manager.py`) execute decisions through the same unified pipeline, ensuring absolute consistency of risk and cost rules across all environments.

---

## 1. The Decision Pipeline (`core/pipeline.py`)

The pipeline represents a sequential assembly line (Narang's canonical workflow), now run
**unconditionally on every candle** — there is no early return for open positions. Execution order:
**Alpha → Risk → Cost → Portfolio → Execution**. A signed `current_holding` (+long, −short, 0 flat)
flows through all five models, so `forecast()` itself decides maintain / exit / flip while holding.

```
             [Every candle — no position-state branch]
                           │
                           ▼
                    1. Alpha Model — forecast() -> Signal
                           │  (handles maintain/exit/flip while holding; entry while flat)
                           ▼
                    2. Risk Model — assess() -> RiskConstraints
                           │  (drawdown breaker, structural stop, budget, max_notional)
                           ▼
                    3. Transaction Cost Model — estimate() -> CostEstimate
                           │  (fee, slippage, market impact)
                           ▼
                    4. Portfolio Construction Model — construct() -> TargetPortfolio
                           │  (signed sizing/weighting; edge-vs-cost veto)
                           ▼
                    5. Execution Model — route() -> OrderPlan | None
                           │
                           ▼
                    [Output: OrderPlan or None]
```

The pipeline is implemented by [pipeline.py](file:///c:/Users/harsh/Desktop/enma_trading_platform/engine/core/pipeline.py):
```python
def evaluate(s, current_holding: float = 0.0) -> "OrderPlan | None":
    sig         = s.forecast()                                    # 1 Alpha
    constraints = s.risk_model.assess(s, sig, current_holding)    # 2 Risk
    cost        = s.cost_model.estimate(s, sig, constraints)      # 3 TCM
    target      = s.portfolio_model.construct(s, sig, constraints,# 4 PCM
                                              cost, current_holding)
    return s.execution_model.route(s, target, current_holding,    # 5 Execution
                                   constraints)
```
All five models run every candle; none short-circuit the pipeline. Vetoes/flat signals are expressed
as a zero/closing `TargetPortfolio` and resolved inside `route()` (its 5 paths: flat→flat, hold→close,
flat→enter, flip, maintain bracket).

---

## 2. Model Specifications & Contracts

All pluggable models inherit from abstract base classes defined in [core/models/base.py](file:///c:/Users/harsh/Desktop/enma_trading_platform/engine/core/models/base.py).

### 1. Alpha Model (The Strategy Itself)
- **Role:** Generates directional predictions and conviction levels.
- **Contract:** `BaseStrategy.forecast() -> Signal`
- **Output:** `Signal(direction: int, conviction: float, ref_price: float)`
  - `direction`: `+1` (long), `-1` (short), `0` (flat)
  - `conviction`: float in `[0, 1]` indicating signal strength (defaults to `1.0` for legacy boolean signals).
  - `ref_price`: entry price reference.

### 2. Risk Model
- **Role:** Controls structural stop placement, calculates risk budgets, and checks circuit breakers.
- **Contract:** `RiskModel.assess(s, sig: Signal, current_holding: float) -> RiskConstraints`
- **Output:** `RiskConstraints(vetoed: bool, max_drawdown_hit: bool, stop_price: float | None, take_profit_price: float | None, risk_per_unit: float, budget: float, max_notional: float)` (alias `RiskFrame` kept for one phase)
- **Drawdown Circuit Breaker:** sets `vetoed=True` / `max_drawdown_hit=True` inside `assess()`.
- **Variants** ([risk.py](file:///c:/Users/harsh/Desktop/enma_trading_platform/engine/core/models/risk.py)): `AtrBracketRiskModel` (ATR stop + R:R target), `ChandelierRiskModel` (trailing chandelier exit), `SignalExitRiskModel` (no hard stop; exit on signal). All apply isolated-margin liquidation-buffer checks.

### 3. Portfolio Construction Model (PCM)
- **Role:** Sizes the (signed) position target by combining alpha conviction, risk constraints, and the cost estimate; owns the edge-vs-cost veto (returns a zero target when the edge doesn't clear the cost hurdle).
- **Contract:** `PortfolioModel.construct(s, sig: Signal, constraints: RiskConstraints, cost: CostEstimate, current_holding: float) -> TargetPortfolio`
- **Output:** `TargetPortfolio(asset: str, qty: float, weight: float)` — `qty` is **signed** (+long, −short, 0 flat); alias `Target` kept for one phase.
- **Variants** ([portfolio.py](file:///c:/Users/harsh/Desktop/enma_trading_platform/engine/core/models/portfolio.py)): `RiskBudgetPortfolio` (risk-budget sizing scaled by conviction) and `NotionalPortfolio` (fixed equity-fraction notional sizing).

### 4. Transaction Cost Model (TCM)
- **Role:** Estimates fee, slippage, and market impact costs. (The edge-vs-cost hurdle gate itself is applied downstream in `PortfolioModel.construct()`, which consumes this estimate.)
- **Contract:** `CostModel.estimate(s, sig: Signal, constraints: RiskConstraints) -> CostEstimate`
- **Output:** `CostEstimate(fee: float, slippage: float, impact: float)` with a `.total` property; alias `Cost` kept for one phase.
- **Default Implementation:** `DefaultTransactionCostModel` ([cost.py](file:///c:/Users/harsh/Desktop/enma_trading_platform/engine/core/models/cost.py)) computes adverse fill slippage and taker fees. When `min_edge_mult > 0`, the PCM requires the trade's expected edge to clear `min_edge_mult × total cost`.

### 5. Execution Model
- **Role:** Translates the signed target (vs `current_holding`) into a concrete order plan — and is the **sole writer** of `buy`/`sell`/`stop_loss`/`take_profit`/`_pending_flip`/`_close_at_open`.
- **Contract:** `ExecutionModel.route(s, target: TargetPortfolio, current_holding: float, constraints: RiskConstraints) -> OrderPlan | None`
- **Output:** `OrderPlan(direction: int, qty: float, entry_price: float, stop_loss: float | None, take_profit: float | None, order_type: str)`
- **5 routing paths:** flat→flat (no-op), hold→close, flat→enter, flip (atomic close-and-reverse), maintain bracket.
- **Default Implementation:** `DefaultExecution` ([execution.py](file:///c:/Users/harsh/Desktop/enma_trading_platform/engine/core/models/execution.py)) — backtest simulates next-open market fills with adverse slippage; live routes to Binance Testnet.

---

## 3. Custom Model Extension

To implement custom behaviors, subclass the appropriate model and reassign the instance on your strategy's initialization:

```python
from engine.core.strategy import BaseStrategy
from engine.core.models import RiskModel, RiskConstraints, Signal

class CustomVolatilityRiskModel(RiskModel):
    def assess(self, s, sig: Signal, current_holding: float) -> RiskConstraints:
        # Halt trading if market volatility is too high
        too_volatile = s.vars.get("market_volatility", 0.0) >= 0.05
        # Custom stop distance logic
        stop = s.price - (3.0 * s._atr()) if sig.direction > 0 else s.price + (3.0 * s._atr())
        return RiskConstraints(
            vetoed=too_volatile,
            stop_price=stop,
            risk_per_unit=abs(s.price - stop),
            budget=s.equity * 0.02, # risk 2% instead of default 1%
            max_notional=s.equity * s.leverage
        )

class MyStrategy(BaseStrategy):
    def __init__(self):
        super().__init__()
        # Swap the default risk model with the custom one
        self.risk_model = CustomVolatilityRiskModel()
```
