# Five-Model Quant Architecture & Decision Pipeline

Enma implements a modular, pluggable quant architecture that splits strategy logic, risk checks, portfolio construction, transaction cost estimation, and order execution into separate objects.

Both the backtest engine (`backtest_runner.py`) and live trading engine (`live_bot_manager.py`) execute decisions through the same unified pipeline, ensuring absolute consistency of risk and cost rules across all environments.

---

## 1. The Decision Pipeline (`core/pipeline.py`)

The pipeline represents a sequential assembly line (Narang's canonical workflow): **Alpha → Risk → Portfolio → Cost → Execution**.

```
             [Start: Candle Closed / Event]
                           │
                           ▼
                    Is Position Open?
                    ├── Yes ──► Update Position / Trailing Stops ──► [End]
                    └── No
                           │
                           ▼
                    1. Alpha Model
                    └── signal.flat? ───► Yes ──► [End]
                           │ No
                           ▼
                    2. Risk Model (circuit breakers, structural stop, budget)
                    └── risk_frame.vetoed? ──► Yes ──► [End]
                           │ No
                           ▼
                    4. Portfolio Construction Model (sizing, weighting)
                           │
                           ▼
                    3. Transaction Cost Model (fee, slippage, market impact)
                    └── is_worth_it? ───────► No ──► [End]
                           │ Yes
                           ▼
                    5. Execution Model (order plan creation)
                           │
                           ▼
                    [Output: OrderPlan]
```

The pipeline is implemented by [pipeline.py](file:///c:/Users/harsh/Desktop/enma_trading_platform/engine/core/pipeline.py#L17-L38):
```python
def evaluate(s) -> OrderPlan | None:
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
```

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
- **Contract:** `RiskModel.frame(s, sig: Signal) -> RiskFrame`
- **Output:** `RiskFrame(vetoed: bool, stop_price: float, risk_per_unit: float, budget: float, max_notional: float)`
- **Drawdown Circuit Breaker:** Checked via `RiskModel.can_trade(s)`.
- **Default Implementation:** `DefaultRiskModel` ([risk.py](file:///c:/Users/harsh/Desktop/enma_trading_platform/engine/core/models/risk.py)) implements standard ATR stops, risk-based budgets, and isolated-margin liquidation buffer checks.

### 3. Portfolio Construction Model (PCM)
- **Role:** Sizes position targets by combining alpha conviction and risk parameters, and allocates capital across multiple symbols.
- **Contract:** `PortfolioModel.size(s, sig: Signal, rf: RiskFrame) -> Target`
- **Output:** `Target(qty: float, weight: float)`
- **Capital Allocation:** `PortfolioModel.allocate(total_capital, symbols) -> dict[str, float]` splits capital across multiple symbols.
- **Default Implementation:** `DefaultPortfolioModel` ([portfolio.py](file:///c:/Users/harsh/Desktop/enma_trading_platform/engine/core/models/portfolio.py)) sizes using the risk budget scaled by alpha conviction (`qty = size_by_risk * conviction`).

### 4. Transaction Cost Model (TCM)
- **Role:** Estimates fee, slippage, and market impact costs, and enforces the hurdle gate comparing edge against cost.
- **Contract:**
  - `CostModel.estimate(s, target: Target) -> Cost`
  - `CostModel.is_worth_it(s, sig: Signal, rf: RiskFrame, cost: Cost) -> bool`
- **Output:** `Cost(fee: float, slippage: float, impact: float)`
- **Default Implementation:** `DefaultCostModel` ([cost.py](file:///c:/Users/harsh/Desktop/enma_trading_platform/engine/core/models/cost.py)) computes adverse fill slippage and taker fees. If `min_edge_mult > 0`, it requires the trade's expected edge (`conviction * risk_per_unit * rrr`) to clear the cost hurdle.

### 5. Execution Model
- **Role:** Translates targets into order plans, and simulates (backtest) or tracks (live) order fills.
- **Contract:** `ExecutionModel.plan(s, sig: Signal, target: Target, rf: RiskFrame) -> OrderPlan | None`
- **Output:** `OrderPlan(direction: int, qty: float, entry_price: float, stop_loss: float, take_profit: float, order_type: str)`
- **Fills Assembly:** `ExecutionModel.entry_fill()` and `ExecutionModel.exit_fill()` assemble market fills.
- **Default Implementations:**
  - `BacktestExecution` ([execution.py](file:///c:/Users/harsh/Desktop/enma_trading_platform/engine/core/models/execution.py)) simulates next-open market fills with adverse slippage.
  - `LiveExecution` ([execution.py](file:///c:/Users/harsh/Desktop/enma_trading_platform/engine/core/models/execution.py)) handles Testnet Binance execution and calculates close fees via `exit_fee()`.

---

## 3. Custom Model Extension

To implement custom behaviors, subclass the appropriate model and reassign the instance on your strategy's initialization:

```python
from engine.core.strategy import BaseStrategy
from engine.core.models import RiskModel, RiskFrame, Signal

class CustomVolatilityRiskModel(RiskModel):
    def can_trade(self, s) -> bool:
        # Halt trading if market volatility is too high
        return s.vars.get("market_volatility", 0.0) < 0.05

    def frame(self, s, sig: Signal) -> RiskFrame:
        # Custom stop distance logic
        stop = s.price - (3.0 * s._atr()) if sig.direction > 0 else s.price + (3.0 * s._atr())
        return RiskFrame(
            vetoed=not self.can_trade(s),
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
