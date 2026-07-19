"""Bayesian (Optuna TPE) optimizer tests (Plan 10 Phase 3b).

Covers Plan 19's own verification gate: param-suggestion mapping correctness
(int/float/categorical specs map onto the right optuna `trial.suggest_*`
call), a seeded study is reproducible (same seed + same space -> identical
best params), and TPE reaches within a small band of a known optimum in far
fewer trials than the grid would need for the same space. `run_backtest_simulation`
is faked with a synthetic quadratic loss landscape (peak at a known params
combo) so this is fully hermetic — no engine/DB dependency chain, same style
as `test_walk_forward.py`.
"""
import pytest

import services.optimizer as optimizer_module
from services.optimizer import (
    OptimizerConfig,
    _finalize_optimization,
    _suggest_params,
    run_bayesian_optimization,
    run_optimization,
)


def _base_config(objective="sharpe", min_trades=0):
    return OptimizerConfig(
        strategy_file="strategies/AdaptiveTrend",
        exchange="Binance Futures",
        symbol="BTCUSDT",
        timeframe="1h",
        start_date="2024-01-01",
        end_date="2024-06-01",
        capital=10000,
        leverage=10,
        objective=objective,
        min_trades=min_trades,
    )


# ── _suggest_params (pure, no I/O) ───────────────────────────────────────────

class _FakeTrial:
    """Records which suggest_* method was called with which bounds, without
    depending on optuna's own Trial internals."""

    def __init__(self):
        self.calls = []

    def suggest_int(self, name, low, high, step=1):
        self.calls.append(("int", name, low, high, step))
        return low

    def suggest_float(self, name, low, high):
        self.calls.append(("float", name, low, high))
        return low

    def suggest_categorical(self, name, choices):
        self.calls.append(("categorical", name, tuple(choices)))
        return choices[0]


def test_suggest_params_maps_int_spec_to_suggest_int():
    trial = _FakeTrial()
    _suggest_params(trial, {"fast": {"min": 5, "max": 30, "step": 5, "type": "int"}})
    assert trial.calls == [("int", "fast", 5, 30, 5)]


def test_suggest_params_maps_float_spec_to_suggest_float():
    trial = _FakeTrial()
    _suggest_params(trial, {"atr_mult": {"min": 1.0, "max": 4.0, "type": "float"}})
    assert trial.calls == [("float", "atr_mult", 1.0, 4.0)]


def test_suggest_params_maps_categorical_spec():
    trial = _FakeTrial()
    _suggest_params(trial, {"mode": {"type": "categorical", "values": ["a", "b", "c"]}})
    assert trial.calls == [("categorical", "mode", ("a", "b", "c"))]


def test_suggest_params_values_key_implies_categorical_without_explicit_type():
    trial = _FakeTrial()
    _suggest_params(trial, {"mode": {"values": ["x", "y"]}})
    assert trial.calls == [("categorical", "mode", ("x", "y"))]


def test_suggest_params_multiple_specs_all_applied():
    trial = _FakeTrial()
    params = _suggest_params(trial, {
        "fast": {"min": 5, "max": 30, "step": 5, "type": "int"},
        "atr_mult": {"min": 1.0, "max": 4.0, "type": "float"},
    })
    assert set(params.keys()) == {"fast", "atr_mult"}
    assert len(trial.calls) == 2


# ── run_bayesian_optimization (fully faked backtest, quadratic landscape) ───

def _install_quadratic_backtest(monkeypatch, optimum=15, width=2.0):
    """Fakes `run_backtest_simulation` with a Sharpe that peaks at
    `fast == optimum` — TPE should converge toward it faster than a blind
    search would need to cover the space exhaustively."""

    async def fake_run_backtest_simulation(job_id, alpha_params, **kwargs):
        fast = alpha_params["fast"]
        sharpe = 3.0 - ((fast - optimum) ** 2) / (width ** 2 * 10)
        return {
            "jobId": job_id,
            "status": "completed",
            "metrics": {"sharpeRatio": f"{sharpe:.6f}", "totalTrades": 40},
            "tradeCount": 40,
        }

    monkeypatch.setattr(optimizer_module, "run_backtest_simulation", fake_run_backtest_simulation)
    monkeypatch.setattr(optimizer_module, "get_database", lambda: _FakeDB())


class _FakeCollection:
    async def update_one(self, *a, **kw):
        return None

    async def replace_one(self, *a, **kw):
        return None


class _FakeDB:
    def __init__(self):
        self.backtestResults = _FakeCollection()
        self.optimizationResults = _FakeCollection()


def _run(coro):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro)


def test_bayesian_optimization_returns_same_shape_as_grid(monkeypatch):
    _install_quadratic_backtest(monkeypatch)
    config = _base_config()
    param_grid = {"fast": {"min": 1, "max": 30, "step": 1, "type": "int"}}

    result = _run(run_bayesian_optimization(
        config=config, param_grid=param_grid, n_trials=15, job_id="bo_test1", seed=7,
    ))

    assert result["method"] == "bayesian"
    assert result["totalCombinations"] == 15
    assert len(result["results"]) == 15
    assert result["best"] is not None
    assert all("rank" in r for r in result["results"])
    # same shape keys as grid's own result
    grid_keys = {"jobId", "status", "method", "objective", "totalCombinations",
                 "errorCount", "minTrades", "eligibleCount", "paramGrid",
                 "config", "results", "best"}
    assert grid_keys <= set(result.keys())


def test_bayesian_optimization_converges_near_known_optimum(monkeypatch):
    _install_quadratic_backtest(monkeypatch, optimum=15)
    config = _base_config()
    param_grid = {"fast": {"min": 1, "max": 30, "step": 1, "type": "int"}}

    # 20 trials over a 30-point space — far fewer than exhaustive grid (30),
    # TPE should still land within a few units of the true optimum (15).
    result = _run(run_bayesian_optimization(
        config=config, param_grid=param_grid, n_trials=20, job_id="bo_test2", seed=7,
    ))

    best_fast = result["best"]["params"]["fast"]
    assert abs(best_fast - 15) <= 5


def test_bayesian_optimization_seeded_reproducibility(monkeypatch):
    _install_quadratic_backtest(monkeypatch)
    config = _base_config()
    param_grid = {"fast": {"min": 1, "max": 30, "step": 1, "type": "int"}}

    result_a = _run(run_bayesian_optimization(
        config=config, param_grid=param_grid, n_trials=12, job_id="bo_seed_a", seed=99,
    ))
    result_b = _run(run_bayesian_optimization(
        config=config, param_grid=param_grid, n_trials=12, job_id="bo_seed_b", seed=99,
    ))

    params_a = [r["params"] for r in sorted(result_a["results"], key=lambda r: r["rank"])]
    params_b = [r["params"] for r in sorted(result_b["results"], key=lambda r: r["rank"])]
    assert params_a == params_b
    assert result_a["best"]["params"] == result_b["best"]["params"]


def test_bayesian_optimization_different_seeds_can_differ(monkeypatch):
    _install_quadratic_backtest(monkeypatch, optimum=15, width=8.0)  # flatter landscape
    config = _base_config()
    param_grid = {"fast": {"min": 1, "max": 30, "step": 1, "type": "int"}}

    result_a = _run(run_bayesian_optimization(
        config=config, param_grid=param_grid, n_trials=8, job_id="bo_diff_a", seed=1,
    ))
    result_b = _run(run_bayesian_optimization(
        config=config, param_grid=param_grid, n_trials=8, job_id="bo_diff_b", seed=2,
    ))

    trials_a = [r["params"]["fast"] for r in result_a["results"]]
    trials_b = [r["params"]["fast"] for r in result_b["results"]]
    assert trials_a != trials_b


def test_bayesian_optimization_zero_trials_returns_empty():
    config = _base_config()
    result = _run(run_bayesian_optimization(
        config=config, param_grid={"fast": {"min": 1, "max": 30, "type": "int"}},
        n_trials=0, job_id="bo_empty",
    ))
    assert result["totalCombinations"] == 0
    assert result["results"] == []
    assert result["method"] == "bayesian"


def test_bayesian_optimization_unknown_objective_raises():
    config = _base_config(objective="not_a_real_objective")
    with pytest.raises(ValueError):
        _run(run_bayesian_optimization(
            config=config, param_grid={"fast": {"min": 1, "max": 30, "type": "int"}},
            n_trials=5, job_id="bo_bad_obj",
        ))


def test_bayesian_min_trades_filter_excludes_low_trade_combos(monkeypatch):
    """Same honesty-layer filter as grid search (`_finalize_optimization` is
    the shared tail both `run_optimization` and `run_bayesian_optimization`
    call) — a combo posting a great loss with too few trades must not become
    `best`. Exercised directly against the shared tail rather than through a
    live TPE run, since TPE sampling isn't guaranteed to visit every point in
    a search space the way grid's exhaustive enumeration is."""
    monkeypatch.setattr(optimizer_module, "get_database", lambda: _FakeDB())
    config = _base_config(min_trades=30)
    scored = [
        {"params": {"fast": 3}, "loss": -9.99, "rank": 0,
         "metrics": {"totalTrades": 2}},
        {"params": {"fast": 7}, "loss": -1.0, "rank": 0,
         "metrics": {"totalTrades": 50}},
    ]

    result = _run(_finalize_optimization(
        job_id="bo_mintrades", config=config, param_grid={"fast": {"min": 1, "max": 10, "type": "int"}},
        scored=scored, total=2, errors=0, method="bayesian",
    ))

    assert result["best"]["params"]["fast"] == 7
    assert result["eligibleCount"] == 1
    assert result["eligibleCount"] < result["totalCombinations"]


def test_bayesian_optimization_errored_trial_gets_inf_loss_and_survives(monkeypatch):
    """A failing backtest must not crash the study (optuna's `tell()` rejects
    non-finite losses) and must still surface as an inf-loss trial, mirroring
    grid search's own error-path shape."""

    async def fake_run_backtest_simulation(job_id, alpha_params, **kwargs):
        if alpha_params["fast"] == 5:
            raise RuntimeError("simulated backtest failure")
        return {"jobId": job_id, "status": "completed",
                "metrics": {"sharpeRatio": "1.00", "totalTrades": 40}, "tradeCount": 40}

    monkeypatch.setattr(optimizer_module, "run_backtest_simulation", fake_run_backtest_simulation)
    monkeypatch.setattr(optimizer_module, "get_database", lambda: _FakeDB())

    config = _base_config()
    # Fixed to always suggest fast=5 by pinning min==max.
    param_grid = {"fast": {"min": 5, "max": 5, "step": 1, "type": "int"}}

    result = _run(run_bayesian_optimization(
        config=config, param_grid=param_grid, n_trials=3, job_id="bo_error", seed=1,
    ))

    assert result["errorCount"] == 3
    # `_finalize_optimization`'s JSON-safety pass sanitizes a non-finite loss
    # to `None` (same fix class as walk_forward.py's own `_json_safe_trials`,
    # applied here at the source so every caller — including the raw
    # `/optimize/run` response — gets it for free).
    assert all(r["loss"] is None for r in result["results"])
    # No min-trades filter is set (default 0/off), so `eligible == scored`
    # even though every entry had an inf loss — matches grid's own existing
    # behavior (min_trades=0 does not filter on finiteness either); `best`
    # is structurally present but meaningless when every trial failed.
    assert result["best"] is not None
    assert result["best"]["loss"] is None


# ── back-compat: method omitted anywhere still behaves like grid ───────────

def test_grid_result_now_carries_method_key_for_back_compat_shape_parity(monkeypatch):
    async def fake_run_backtest_simulation(job_id, alpha_params, **kwargs):
        return {"jobId": job_id, "status": "completed",
                "metrics": {"sharpeRatio": "1.00", "totalTrades": 40}, "tradeCount": 40}

    monkeypatch.setattr(optimizer_module, "run_backtest_simulation", fake_run_backtest_simulation)
    monkeypatch.setattr(optimizer_module, "get_database", lambda: _FakeDB())

    config = _base_config()
    param_grid = {"fast": {"min": 1, "max": 3, "step": 1, "type": "int"}}

    result = _run(run_optimization(config=config, param_grid=param_grid, job_id="grid_shape"))
    assert result["method"] == "grid"
