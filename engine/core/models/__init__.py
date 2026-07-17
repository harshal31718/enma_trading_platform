"""Five-Model Quant Architecture — public facade.

Value objects:  Signal, RiskConstraints, CostEstimate, TargetPortfolio, OrderPlan
Deprecated aliases: RiskFrame, Cost, Target (remove in Phase 6)
Interfaces: RiskModel, TransactionCostModel (= CostModel), PortfolioModel, ExecutionModel
Implementations:
  Risk      — DefaultRiskModel, AtrBracketRiskModel, ChandelierRiskModel, SignalExitRiskModel
  TCM       — DefaultTransactionCostModel (= DefaultCostModel), LadderedTransactionCostModel
  Portfolio — DefaultPortfolioModel, RiskBudgetPortfolio, NotionalPortfolio
  Execution — DefaultExecution, BacktestExecution, LiveExecution
"""
from .base import (
    # Value objects (new names)
    Signal,
    RiskConstraints,
    CostEstimate,
    TargetPortfolio,
    OrderPlan,
    EntryFill,
    ExitFill,
    # Deprecated aliases (remove Phase 6)
    RiskFrame,
    Cost,
    Target,
    # Interfaces
    RiskModel,
    TransactionCostModel,
    CostModel,          # alias for TransactionCostModel
    PortfolioModel,
    ExecutionModel,
)
from .risk import (
    DefaultRiskModel,
    AtrBracketRiskModel,
    ChandelierRiskModel,
    SignalExitRiskModel,
)
from .cost import (
    DefaultTransactionCostModel,
    DefaultCostModel,   # alias for DefaultTransactionCostModel
    LadderedTransactionCostModel,
)
from .portfolio import (
    DefaultPortfolioModel,
    RiskBudgetPortfolio,
    NotionalPortfolio,
    InverseVolatilityPortfolio,
    compute_realized_volatility,
)
from .execution import (
    DefaultExecution,
    BacktestExecution,
    LiveExecution,
)
from .protections import (
    ProtectionReturn,
    IProtection,
    CooldownPeriod,
    StoplossGuard,
    MaxDrawdownProtection,
    LowProfitPairsProtection,
    ProtectionManager,
)
from .governor import (
    GovernorVerdict,
    SessionRiskGovernor,
)

__all__ = [
    # Value objects
    "Signal",
    "RiskConstraints",
    "CostEstimate",
    "TargetPortfolio",
    "OrderPlan",
    "EntryFill",
    "ExitFill",
    # Deprecated aliases
    "RiskFrame",
    "Cost",
    "Target",
    # Interfaces
    "RiskModel",
    "TransactionCostModel",
    "CostModel",
    "PortfolioModel",
    "ExecutionModel",
    # Risk implementations
    "DefaultRiskModel",
    "AtrBracketRiskModel",
    "ChandelierRiskModel",
    "SignalExitRiskModel",
    # TCM implementations
    "DefaultTransactionCostModel",
    "DefaultCostModel",
    "LadderedTransactionCostModel",
    # Portfolio implementations
    "DefaultPortfolioModel",
    "RiskBudgetPortfolio",
    "NotionalPortfolio",
    "InverseVolatilityPortfolio",
    "compute_realized_volatility",
    # Execution implementations
    "DefaultExecution",
    "BacktestExecution",
    "LiveExecution",
    # Protections
    "ProtectionReturn",
    "IProtection",
    "CooldownPeriod",
    "StoplossGuard",
    "MaxDrawdownProtection",
    "LowProfitPairsProtection",
    "ProtectionManager",
    # Session Risk Governor (Plan 22)
    "GovernorVerdict",
    "SessionRiskGovernor",
]
