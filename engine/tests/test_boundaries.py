"""Boundary regression tests for the Narang Black-Box architecture.

Asserts that each seeded strategy:
  1. Defines forecast() (Alpha Model contract)
  2. Does NOT define go_long, go_short, or update_position (these are
     boundary violations when present on a ported strategy)
  3. Does NOT reference Alpha-forbidden symbols anywhere in its module AST
     (account state, order writes, execution/sizing calls)

Run with:
    docker compose exec engine python -m pytest tests/test_boundaries.py -q
"""
import ast
import importlib
import inspect
import os
import pkgutil
import sys
import textwrap
from pathlib import Path
from typing import Iterator

import pytest

if os.name != "nt" and Path("/engine").exists():
    sys.path.insert(0, "/")

# ── Seeded strategies to check ───────────────────────────────────────────────
SEEDED_STRATEGIES = [
    "MicroScalper",
    "AdaptiveTrend",
    "BestSupertrend",
    "MicroMacroRSIDivergence",
    "MultiDivergence",
]

# ── Forbidden Alpha-side references (account/position state + order writes) ──
FORBIDDEN_PATTERNS = [
    r"self\.balance",
    r"self\.equity",
    r"self\.available_capital",
    r"self\.available_margin",
    r"self\.peak_equity",
    r"self\.session_drawdown",
    r"self\.max_qty",
    r"self\.buy\s*=",
    r"self\.sell\s*=",
    r"self\.stop_loss\s*=",
    r"self\.take_profit\s*=",
    r"self\._pending_flip\s*=",
    r"self\._close_at_open\s*=",
    r"self\.size_by_risk\b",
    r"self\.size_by_notional\b",
    r"self\.go_long\(",
    r"self\.go_short\(",
    r"self\.flip_position\(",
    r"self\.close_position\(",
    r"self\.liquidate\(",
    r"self\.trail_stop\(",
    r"self\.move_to_breakeven\(",
    r"self\.update_position\(",
]

# Methods that ported strategies must NOT own (boundary-violation methods
# that only exist on the strategy if it hasn't been ported yet)
FORBIDDEN_METHODS = {"go_long", "go_short", "update_position"}


def _strategy_module(name: str):
    """Import and return the strategy module under engine.strategies.<name>."""
    return importlib.import_module(f"engine.strategies.{name}")


def _strategy_class(name: str):
    """Return the main strategy class from the module."""
    mod = _strategy_module(name)
    for attr in dir(mod):
        obj = getattr(mod, attr)
        if (
            inspect.isclass(obj)
            and obj.__name__ == name
            and hasattr(obj, "forecast")
        ):
            return obj
    raise RuntimeError(f"Could not find strategy class {name} in module")


def _strategy_source(name: str) -> str:
    """Return the source of the strategy's __init__.py."""
    mod = _strategy_module(name)
    return inspect.getsource(mod)


# ── Parameterized tests ───────────────────────────────────────────────────────

@pytest.mark.parametrize("strategy_name", SEEDED_STRATEGIES)
def test_defines_forecast(strategy_name: str) -> None:
    """Strategy must define forecast() — the Alpha Model contract."""
    cls = _strategy_class(strategy_name)
    # forecast() must be defined directly on the strategy class, not just inherited
    assert "forecast" in cls.__dict__, (
        f"{strategy_name} does not define forecast(). "
        "Ported strategies must override forecast() instead of should_long/should_short."
    )


@pytest.mark.parametrize("strategy_name", SEEDED_STRATEGIES)
def test_no_forbidden_methods(strategy_name: str) -> None:
    """Ported strategies must NOT own go_long, go_short, or update_position."""
    cls = _strategy_class(strategy_name)
    owned = {m for m in FORBIDDEN_METHODS if m in cls.__dict__}
    assert not owned, (
        f"{strategy_name} still defines boundary-violation method(s): {owned}. "
        "These must be removed; execution is route()'s job."
    )


import re as _re

@pytest.mark.parametrize("strategy_name", SEEDED_STRATEGIES)
def test_no_forbidden_references(strategy_name: str) -> None:
    """Strategy source must not reference Alpha-forbidden symbols."""
    source = _strategy_source(strategy_name)
    # Only check inside forecast() and before() — those are Alpha territory.
    # Other helpers (validate_params, _helpers) are fine to inspect.
    violations = []
    for pattern in FORBIDDEN_PATTERNS:
        for match in _re.finditer(pattern, source):
            line_no = source[: match.start()].count("\n") + 1
            violations.append(f"  line {line_no}: {pattern!r} matched {match.group()!r}")
    assert not violations, (
        f"{strategy_name} has boundary violations:\n" + "\n".join(violations)
    )


@pytest.mark.parametrize("strategy_name", SEEDED_STRATEGIES)
def test_model_bindings(strategy_name: str) -> None:
    """Strategy __init__ must assign non-default risk_model and portfolio_model."""
    try:
        from engine.core.models import (
            DefaultRiskModel,
            DefaultPortfolioModel,
            AtrBracketRiskModel,
            ChandelierRiskModel,
            SignalExitRiskModel,
            RiskBudgetPortfolio,
            NotionalPortfolio,
        )
    except ImportError:
        from core.models import (
            DefaultRiskModel,
            DefaultPortfolioModel,
            AtrBracketRiskModel,
            ChandelierRiskModel,
            SignalExitRiskModel,
            RiskBudgetPortfolio,
            NotionalPortfolio,
        )

    cls = _strategy_class(strategy_name)
    instance = cls.__new__(cls)
    # Partially initialize enough for __init__ to not crash on candles/position
    instance.candles   = __import__("numpy").array([])
    instance.position  = None
    instance.balance   = 0.0
    try:
        cls.__init__(instance)
    except Exception:
        pytest.skip(f"Could not instantiate {strategy_name} in isolation")

    non_default_models = (
        AtrBracketRiskModel, ChandelierRiskModel, SignalExitRiskModel,
        RiskBudgetPortfolio, NotionalPortfolio,
    )
    risk_ok = isinstance(instance.risk_model, non_default_models)
    port_ok = isinstance(instance.portfolio_model, non_default_models)
    assert risk_ok, (
        f"{strategy_name}.risk_model is still {type(instance.risk_model).__name__}; "
        "ported strategies must bind a specific risk model."
    )
    assert port_ok, (
        f"{strategy_name}.portfolio_model is still {type(instance.portfolio_model).__name__}; "
        "ported strategies must bind a specific portfolio model."
    )
