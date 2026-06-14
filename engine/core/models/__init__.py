"""Five-Model Quant Architecture (see plan.md).

Public facade: value objects, model interfaces, and default implementations.
The Alpha Model is the strategy itself (BaseStrategy.forecast()); the other four
models are pluggable and default to legacy-equivalent behavior.
"""
from .base import (
    Signal,
    RiskFrame,
    Cost,
    Target,
    OrderPlan,
    EntryFill,
    ExitFill,
    RiskModel,
    CostModel,
    PortfolioModel,
    ExecutionModel,
)
from .risk import DefaultRiskModel
from .cost import DefaultCostModel
from .portfolio import DefaultPortfolioModel
from .execution import DefaultExecution, BacktestExecution, LiveExecution

__all__ = [
    "Signal",
    "RiskFrame",
    "Cost",
    "Target",
    "OrderPlan",
    "EntryFill",
    "ExitFill",
    "RiskModel",
    "CostModel",
    "PortfolioModel",
    "ExecutionModel",
    "DefaultRiskModel",
    "DefaultCostModel",
    "DefaultPortfolioModel",
    "DefaultExecution",
    "BacktestExecution",
    "LiveExecution",
]
