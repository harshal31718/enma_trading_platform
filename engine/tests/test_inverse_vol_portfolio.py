"""Plan 22 Step 22.6 regression: `InverseVolatilityPortfolio.allocate()` and
`compute_realized_volatility()` (`engine/core/models/portfolio.py`).

Golden-master-gated by design: the default `allocation == "equal"` path
never touches this code at all (`backtest_runner.py`/`live_bot_manager.py`
both leave the pre-existing `DefaultPortfolioModel().allocate()` call
untouched unless `risk_params["allocation"] == "inverse_vol"` is explicitly
set) — verified separately via `scripts/golden_master.py` (pre/post 22.6
byte-identical, 5/5 strategies). This file only drives the new class/
function directly, no session/backtest harness needed.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_inverse_vol_portfolio.py
"""
import numpy as np

from core.models.portfolio import InverseVolatilityPortfolio, compute_realized_volatility


def test_compute_realized_volatility_basic():
    prices = {
        "LOWVOL": np.linspace(100, 101, 30),   # near-flat -> low vol
        "HIGHVOL": 100 + np.sin(np.arange(30)) * 20,  # swings hard -> high vol
    }
    vols = compute_realized_volatility(prices)
    assert set(vols.keys()) == {"LOWVOL", "HIGHVOL"}
    assert vols["LOWVOL"] < vols["HIGHVOL"]


def test_compute_realized_volatility_drops_insufficient_data():
    prices = {"ONEPOINT": [100.0], "EMPTY": [], "GOOD": np.linspace(100, 110, 10)}
    vols = compute_realized_volatility(prices)
    assert "ONEPOINT" not in vols
    assert "EMPTY" not in vols
    assert "GOOD" in vols


def test_compute_realized_volatility_drops_nan_and_nonpositive():
    prices = {"BAD": [100.0, float("nan"), -5.0, 101.0]}
    vols = compute_realized_volatility(prices)
    # after dropping NaN: [100.0, -5.0, 101.0] -> has a non-positive value -> dropped entirely
    assert "BAD" not in vols


def test_allocate_degrades_to_equal_when_no_volatilities():
    gov = InverseVolatilityPortfolio()
    result = gov.allocate(1000.0, ["A", "B", "C"], volatilities=None)
    assert result == {"A": pytest_approx(1000/3), "B": pytest_approx(1000/3), "C": pytest_approx(1000/3)}


def test_allocate_degrades_to_equal_when_fewer_than_two_known():
    gov = InverseVolatilityPortfolio()
    result = gov.allocate(1000.0, ["A", "B"], volatilities={"A": 0.05})
    assert result["A"] == pytest_approx(500.0)
    assert result["B"] == pytest_approx(500.0)


def test_allocate_weights_inversely_to_volatility():
    gov = InverseVolatilityPortfolio()
    # B is 4x more volatile than A -> A should get ~4x B's weight (pre-clamp)
    result = gov.allocate(1000.0, ["A", "B"], volatilities={"A": 0.01, "B": 0.04}, floor_pct=0.0, cap_pct=1.0)
    assert result["A"] > result["B"]
    assert result["A"] == pytest_approx(800.0)
    assert result["B"] == pytest_approx(200.0)


def test_allocate_weights_sum_to_total_capital():
    gov = InverseVolatilityPortfolio()
    result = gov.allocate(
        10_000.0, ["A", "B", "C", "D"],
        volatilities={"A": 0.01, "B": 0.02, "C": 0.05, "D": 0.10},
    )
    assert sum(result.values()) == pytest_approx(10_000.0)


def test_allocate_respects_floor_and_cap():
    gov = InverseVolatilityPortfolio()
    # A is vastly less volatile than the others -> would dominate without a cap
    result = gov.allocate(
        1000.0, ["A", "B", "C"],
        volatilities={"A": 0.0001, "B": 0.5, "C": 0.5},
        floor_pct=0.05, cap_pct=0.5,
    )
    for sym, notional in result.items():
        weight = notional / 1000.0
        assert weight >= 0.05 - 1e-9
        assert weight <= 0.5 + 1e-9


def test_allocate_missing_symbol_gets_mean_known_weight_not_zero():
    gov = InverseVolatilityPortfolio()
    result = gov.allocate(
        1000.0, ["A", "B", "NEWSYM"],
        volatilities={"A": 0.02, "B": 0.02},  # NEWSYM has no vol estimate
    )
    assert result["NEWSYM"] > 0.0
    assert sum(result.values()) == pytest_approx(1000.0)


def test_allocate_empty_symbols_returns_empty():
    gov = InverseVolatilityPortfolio()
    assert gov.allocate(1000.0, [], volatilities={"A": 0.01}) == {}


def pytest_approx(x):
    import pytest
    return pytest.approx(x, rel=1e-6)
