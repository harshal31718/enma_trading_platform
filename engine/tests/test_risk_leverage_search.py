"""Plan 10 Phase 4b (risk_pct/leverage search) tests.

2026-07-19 decision, after scoping: a SEPARATE grid (keys `risk_pct`/
`leverage`) cartesian-multiplied against the strategy's own `param_grid`
(`optimizer._build_combined_grid`), not tagged/prefixed keys merged into the
same dict — because `run_backtest_simulation` validates every `alpha_params`
key strictly against the strategy's own `PARAMS` schema and would error on an
unrecognized `risk_pct` key rather than silently ignore it. Searched
independently per fold — verified in `test_walk_forward.py` as simply this
codebase's existing per-fold-independent-optimization behavior, no new
per-fold logic required for that half of the decision.

Covers: `_build_combined_grid`'s pure combinatorics (no risk_leverage_grid ==
identical to before this feature existed; combined-total guardrail sampling
reuses `_decode_combo_index` correctly across the merged key space) and
`run_optimization`/`run_bayesian_optimization`'s per-combo leverage/risk_pct
override actually reaching the (mocked) `run_backtest_simulation` call.
"""
import asyncio

import pytest

import services.optimizer as optimizer_module
from services.optimizer import (
    OptimizerConfig,
    _build_combined_grid,
    run_bayesian_optimization,
    run_optimization,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _FakeCollection:
    async def update_one(self, *a, **kw):
        return None

    async def replace_one(self, *a, **kw):
        return None


class _FakeDB:
    @property
    def backtestResults(self):
        return _FakeCollection()

    @property
    def optimizationResults(self):
        return _FakeCollection()


@pytest.fixture(autouse=True)
def _fake_database(monkeypatch):
    # `_finalize_optimization`'s persistence tail calls `get_database()` —
    # without faking it, this hits the real (unreachable in this sandbox)
    # MONGO_URI and hangs rather than raising, since motor's connection
    # attempt blocks synchronously before the surrounding try/except can
    # catch anything. Same class of hang as the unrelated
    # `test_execute_entry_risk_check_event.py`/`test_reconcile_fixes.py`
    # cases this session already diagnosed.
    monkeypatch.setattr(optimizer_module, "get_database", lambda: _FakeDB())


# ── _build_combined_grid (pure, no I/O) ──────────────────────────────────────

def test_combined_grid_without_risk_leverage_grid_matches_strategy_grid_alone():
    param_grid = {"fast": {"min": 5, "max": 15, "step": 5, "type": "int"}}  # 3 values
    combos = _build_combined_grid(param_grid, None, max_combinations=0)
    assert len(combos) == 3
    for c in combos:
        assert c["riskLeverage"] == {}
        assert set(c["alphaParams"].keys()) == {"fast"}


def test_combined_grid_multiplies_strategy_grid_by_risk_leverage_grid():
    param_grid = {"fast": {"min": 5, "max": 15, "step": 5, "type": "int"}}  # 3 values
    risk_leverage_grid = {
        "risk_pct": {"min": 0.01, "max": 0.03, "num": 3, "type": "float"},  # 3 values
        "leverage": {"values": [5, 10]},  # 2 values
    }
    combos = _build_combined_grid(param_grid, risk_leverage_grid, max_combinations=0)
    assert len(combos) == 3 * 3 * 2  # 18 — the exact multiplication the scoping notes flagged

    # Every combo carries both namespaces, never merged into one dict.
    for c in combos:
        assert set(c["alphaParams"].keys()) == {"fast"}
        assert set(c["riskLeverage"].keys()) == {"risk_pct", "leverage"}

    # Full coverage: every (fast, risk_pct, leverage) triple appears exactly once.
    seen = {
        (c["alphaParams"]["fast"], c["riskLeverage"]["risk_pct"], c["riskLeverage"]["leverage"])
        for c in combos
    }
    assert len(seen) == 18


def test_combined_grid_guardrail_samples_the_true_combined_total_not_just_strategy_grid():
    """The exact risk this feature's scoping notes flagged: a strategy grid
    within its own cap, multiplied externally by risk/leverage values, must
    still respect `max_combinations` against the COMBINED total — not just
    the strategy grid's own size."""
    param_grid = {"fast": {"min": 1, "max": 50, "step": 1, "type": "int"}}  # 50 values — within cap alone
    risk_leverage_grid = {"leverage": {"values": [5, 10, 20]}}  # x3 -> 150 combined, over cap
    combos = _build_combined_grid(param_grid, risk_leverage_grid, max_combinations=50, seed=1)
    assert len(combos) == 50  # sampled down from the TRUE combined total (150), not left at 150


def test_combined_grid_sampled_combos_are_unique():
    param_grid = {"fast": {"min": 1, "max": 100, "step": 1, "type": "int"}}  # 100 values
    risk_leverage_grid = {"leverage": {"values": [5, 10, 20, 40]}}  # 400 combined total
    combos = _build_combined_grid(param_grid, risk_leverage_grid, max_combinations=30, seed=7)
    seen = {(c["alphaParams"]["fast"], c["riskLeverage"]["leverage"]) for c in combos}
    assert len(seen) == 30  # no duplicate combos from the mixed-radix decode


# ── run_optimization / run_bayesian_optimization: per-combo override reaches
#    the (mocked) run_backtest_simulation call ─────────────────────────────

def _base_config(**overrides):
    defaults = dict(
        strategy_file="strategies/AdaptiveTrend",
        exchange="Binance Futures",
        symbol="BTCUSDT",
        timeframe="1h",
        start_date="2024-01-01",
        end_date="2024-06-01",
        capital=10000.0,
        leverage=10,
        objective="sharpe",
    )
    defaults.update(overrides)
    return OptimizerConfig(**defaults)


def test_run_optimization_overrides_leverage_and_risk_pct_per_combo(monkeypatch):
    calls = []

    async def fake_run_backtest_simulation(job_id, **kwargs):
        calls.append({"leverage": kwargs["leverage"], "risk_params": kwargs["risk_params"]})
        return {"metrics": {"sharpeRatio": "1.00", "totalTrades": 20}, "tradeCount": 20}
    monkeypatch.setattr(optimizer_module, "run_backtest_simulation", fake_run_backtest_simulation)

    config = _base_config(leverage=10, risk_params={"rrr": 2.0})
    param_grid = {"fast": {"values": [10]}}  # 1 value — isolate the risk/leverage dimension
    risk_leverage_grid = {
        "risk_pct": {"values": [0.01, 0.02]},
        "leverage": {"values": [5, 20]},
    }

    result = _run(run_optimization(config=config, param_grid=param_grid, risk_leverage_grid=risk_leverage_grid))

    assert result["totalCombinations"] == 4  # 1 (fast) x 2 (risk_pct) x 2 (leverage)
    leverages_used = sorted(c["leverage"] for c in calls)
    assert leverages_used == [5, 5, 20, 20]  # never fell back to config.leverage=10
    risk_pcts_used = sorted(c["risk_params"]["risk_pct"] for c in calls)
    assert risk_pcts_used == [0.01, 0.01, 0.02, 0.02]
    # The job's own risk_params (rrr) survives the override, only risk_pct changes.
    assert all(c["risk_params"]["rrr"] == 2.0 for c in calls)

    # Every scored trial carries its own riskLeverage for downstream OOS reuse.
    for trial in result["results"]:
        assert set(trial["riskLeverage"].keys()) == {"risk_pct", "leverage"}


def test_run_optimization_without_risk_leverage_grid_uses_config_defaults_unchanged(monkeypatch):
    """Zero behavior change for every existing caller that doesn't pass
    `risk_leverage_grid` — the central guarantee this feature must not break."""
    calls = []

    async def fake_run_backtest_simulation(job_id, **kwargs):
        calls.append({"leverage": kwargs["leverage"], "risk_params": kwargs["risk_params"]})
        return {"metrics": {"sharpeRatio": "1.00", "totalTrades": 20}, "tradeCount": 20}
    monkeypatch.setattr(optimizer_module, "run_backtest_simulation", fake_run_backtest_simulation)

    config = _base_config(leverage=10, risk_params={"rrr": 2.0})
    param_grid = {"fast": {"values": [10, 20]}}

    result = _run(run_optimization(config=config, param_grid=param_grid))

    assert all(c["leverage"] == 10 for c in calls)
    assert all(c["risk_params"] == {"rrr": 2.0} for c in calls)
    for trial in result["results"]:
        assert trial["riskLeverage"] is None


def test_run_bayesian_optimization_suggests_risk_leverage_dimensions(monkeypatch):
    calls = []

    async def fake_run_backtest_simulation(job_id, **kwargs):
        calls.append({"leverage": kwargs["leverage"], "risk_params": kwargs["risk_params"]})
        return {"metrics": {"sharpeRatio": "1.00", "totalTrades": 20}, "tradeCount": 20}
    monkeypatch.setattr(optimizer_module, "run_backtest_simulation", fake_run_backtest_simulation)

    config = _base_config(leverage=10)
    param_grid = {"fast": {"min": 5, "max": 20, "step": 5, "type": "int"}}
    risk_leverage_grid = {"leverage": {"values": [5, 10, 20, 40]}}

    result = _run(run_bayesian_optimization(
        config=config, param_grid=param_grid, n_trials=8, risk_leverage_grid=risk_leverage_grid, seed=3,
    ))

    assert len(calls) == 8
    # TPE must actually be choosing from the risk_leverage_grid's values —
    # not silently falling back to config.leverage=10 for every trial.
    used_leverages = {c["leverage"] for c in calls}
    assert used_leverages.issubset({5, 10, 20, 40})
    assert result["riskLeverageGrid"] == risk_leverage_grid
