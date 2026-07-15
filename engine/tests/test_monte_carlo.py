"""Monte Carlo engine tests (Plan 10 vectorized block-bootstrap rewrite).

Covers: scale_out legs excluded from the resampling pool (QNT-14),
deterministic seeding (same jobId -> identical result), empty-trades
default response, and that the drawdown-exceedance distribution is
monotonically non-increasing (P(DD>=10%) >= P(DD>=50%), a basic sanity
invariant any correct exceedance curve must satisfy).

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_monte_carlo.py
"""
import asyncio

import pytest

import services.monte_carlo as mc_module
from services.monte_carlo import run_monte_carlo_simulation


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length=None):
        return self._docs


class _FakeDB:
    def __init__(self, capital, trades):
        self._capital = capital
        self._trades = trades

    class _Results:
        def __init__(self, outer):
            self._outer = outer

        async def find_one(self, query, projection=None):
            return {"capital": self._outer._capital}

    class _Trades:
        def __init__(self, outer):
            self._outer = outer

        def find(self, query):
            return _FakeCursor(self._outer._trades)

    @property
    def backtestResults(self):
        return self._Results(self)

    @property
    def backtestTrades(self):
        return self._Trades(self)


def _install_fake_db(monkeypatch, capital, trades):
    fake_db = _FakeDB(capital, trades)
    monkeypatch.setattr(mc_module, "get_database", lambda: fake_db)


def _trade(pnl, exit_reason="take_profit"):
    return {"pnl": str(pnl), "exitReason": exit_reason}


def test_empty_trades_returns_default_response(monkeypatch):
    _install_fake_db(monkeypatch, capital=10_000.0, trades=[])
    result = asyncio.get_event_loop().run_until_complete(
        run_monte_carlo_simulation("job1", n_runs=200))
    assert result["ruinProbability"] == "0.000"
    assert len(result["drawdownDistribution"]) == 5


def test_scale_out_legs_excluded_from_resampling_pool(monkeypatch):
    trades = [_trade(100), _trade(-50), _trade(9999, exit_reason="scale_out")]
    _install_fake_db(monkeypatch, capital=10_000.0, trades=trades)
    result = asyncio.get_event_loop().run_until_complete(
        run_monte_carlo_simulation("job2", n_runs=200))
    assert result["meta"]["nTrades"] == 2
    assert result["meta"]["scaleOutLegsExcluded"] == 1


def test_deterministic_seeding_same_jobid_reproduces_identical_result(monkeypatch):
    trades = [_trade(p) for p in (120, -80, 50, -30, 200, -100, 40, -60, 90, -20)]
    _install_fake_db(monkeypatch, capital=10_000.0, trades=trades)

    result_a = asyncio.get_event_loop().run_until_complete(
        run_monte_carlo_simulation("stable-job-id", n_runs=1000))
    result_b = asyncio.get_event_loop().run_until_complete(
        run_monte_carlo_simulation("stable-job-id", n_runs=1000))

    assert result_a == result_b


def test_different_jobids_get_different_seeds(monkeypatch):
    # Volatile, losing-heavy sequence so drawdown probabilities are non-zero
    # and can actually differ between seeds (a near-all-gains sequence never
    # breaches any bucket regardless of seed, which would make this test
    # vacuous).
    trades = [_trade(p) for p in ([-500, 300, -400, 200, -600, 100, -300, 150] * 5)]
    _install_fake_db(monkeypatch, capital=10_000.0, trades=trades)

    result_a = asyncio.get_event_loop().run_until_complete(
        run_monte_carlo_simulation("job-a", n_runs=1000))
    result_b = asyncio.get_event_loop().run_until_complete(
        run_monte_carlo_simulation("job-b", n_runs=1000))

    assert result_a["ruinProbability"] != result_b["ruinProbability"] or \
        result_a["drawdownDistribution"] != result_b["drawdownDistribution"]


def test_drawdown_exceedance_distribution_is_monotonically_non_increasing(monkeypatch):
    # A losing-heavy trade sequence should show real drawdown probabilities
    # across the buckets, with P(DD>=x) monotonically non-increasing in x.
    trades = [_trade(p) for p in ([-500, 300, -400, 200, -600, 100, -300, 150] * 5)]
    _install_fake_db(monkeypatch, capital=10_000.0, trades=trades)

    result = asyncio.get_event_loop().run_until_complete(
        run_monte_carlo_simulation("job-monotonic", n_runs=2000))

    probs = [float(row["probability"]) for row in result["drawdownDistribution"]]
    assert probs == sorted(probs, reverse=True), f"exceedance curve not monotonic: {probs}"


def test_percentiles_are_ordered(monkeypatch):
    trades = [_trade(p) for p in ([-500, 300, -400, 200, -600, 100, -300, 150] * 5)]
    _install_fake_db(monkeypatch, capital=10_000.0, trades=trades)

    result = asyncio.get_event_loop().run_until_complete(
        run_monte_carlo_simulation("job-percentiles", n_runs=2000))

    eq = result["finalEquityPercentiles"]
    assert eq["5"] <= eq["25"] <= eq["50"] <= eq["75"] <= eq["95"]

    dd = result["maxDrawdownPercentiles"]
    assert dd["5"] <= dd["25"] <= dd["50"] <= dd["75"] <= dd["95"]
