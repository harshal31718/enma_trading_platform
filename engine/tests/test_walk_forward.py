"""Walk-forward analysis tests (Plan 10 Phase 3a/3d).

Covers: the fold-split conservation property (test windows tile the OOS span
with no gaps/overlap), anchored-vs-rolling train-window behavior, the
stitched-OOS trade aggregate (scale_out exclusion, empty-trades default), an
end-to-end wiring test of `run_lab_walk_forward` against fakes for
`run_optimization`/`run_backtest_simulation`/candle-time-fetch/Mongo (no real
DB/engine dependency chain, same style as `test_lab_simulation.py`),
per-fold trials persistence (Phase 3d) including the inf-loss JSON-safety
fix, and Phase 4a's MC-scored trial selection (`_eligible_trials` unit tests
plus an end-to-end `mcScoring` run verifying the raw pick's OOS backtest is
reused rather than re-run and that the MC-robust pick can diverge from it).
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import services.walk_forward as wf_module
from services.walk_forward import _aggregate_stitched_oos, _eligible_trials, _split_folds, run_lab_walk_forward


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _times(n, start=datetime(2024, 1, 1, tzinfo=timezone.utc), step=timedelta(hours=1)):
    return [start + i * step for i in range(n)]


# ── _split_folds (pure, no I/O) ──────────────────────────────────────────────

def test_split_folds_rolling_tiles_without_gaps_or_overlap():
    times = _times(400)
    folds = _split_folds(times, n_folds=4, train_ratio=0.7, mode="rolling", timeframe="1h")
    assert len(folds) == 4

    # Conservation: fold test windows are chronologically ordered and never
    # overlap each other. (They are NOT contiguous with each other — each
    # fold reserves its own train slice before its test slice, so there's a
    # gap between fold i's test window and fold i+1's, equal to fold i+1's
    # own train length. That gap IS fold i+1's train data — by design, a
    # candle is either training data for its own fold or OOS test data for
    # its own fold, never both, and no two folds' test windows can overlap.)
    for i in range(len(folds) - 1):
        assert folds[i]["testEnd"] <= folds[i + 1]["testStart"]

    # No overlap between a fold's own train and test window.
    for f in folds:
        assert f["trainEnd"] == f["testStart"]
        assert f["trainStart"] < f["trainEnd"]
        assert f["testStart"] < f["testEnd"]

    # Fold blocks themselves ARE contiguous (no gap at the block level, only
    # within a block between its train and test portions).
    fold_size = 400 // 4
    for i, f in enumerate(folds):
        assert datetime.fromisoformat(f["trainStart"]) == times[i * fold_size]

    # Last fold's testEnd is strictly after the last candle in `times` (the
    # exclusive-upper-bound convention needs one bar past the real last candle
    # so it isn't dropped by a `time < end` query).
    last_end = datetime.fromisoformat(folds[-1]["testEnd"])
    assert last_end > times[-1]


def test_split_folds_rolling_train_window_is_fixed_width_per_fold():
    times = _times(400)
    folds = _split_folds(times, n_folds=4, train_ratio=0.7, mode="rolling", timeframe="1h")
    # Rolling: each fold's train slice comes from within that fold's own
    # window only — train start should NOT be the very first candle for any
    # fold after the first (unlike anchored).
    fold_size = 400 // 4
    for i, f in enumerate(folds):
        expected_train_start = times[i * fold_size]
        assert datetime.fromisoformat(f["trainStart"]) == expected_train_start


def test_split_folds_anchored_train_grows_each_fold():
    times = _times(400)
    folds = _split_folds(times, n_folds=4, train_ratio=0.7, mode="anchored", timeframe="1h")
    assert len(folds) == 4
    # Anchored: every fold's train start is the very first candle in the
    # whole range — only trainEnd (== testStart) advances.
    for f in folds:
        assert datetime.fromisoformat(f["trainStart"]) == times[0]

    train_ends = [datetime.fromisoformat(f["trainEnd"]) for f in folds]
    assert train_ends == sorted(train_ends)
    assert len(set(train_ends)) == len(train_ends)  # strictly increasing


def test_split_folds_rejects_range_too_short_for_fold_count():
    times = _times(30)  # far fewer than MIN_FOLD_CANDLES * n_folds
    folds = _split_folds(times, n_folds=4, train_ratio=0.7, mode="rolling", timeframe="1h")
    assert folds == []


def test_split_folds_invalid_n_folds_returns_empty():
    times = _times(400)
    assert _split_folds(times, n_folds=0, train_ratio=0.7, mode="rolling") == []


# ── _aggregate_stitched_oos (pure, no I/O) ───────────────────────────────────

def _trade(pnl, exit_reason="take_profit"):
    return {"pnl": str(pnl), "exitReason": exit_reason}


def test_aggregate_stitched_oos_empty_trades():
    out = _aggregate_stitched_oos([], capital=10_000.0)
    assert out["totalTrades"] == 0
    assert out["netProfitPct"] == "0.00"


def test_aggregate_stitched_oos_excludes_scale_out_legs():
    trades = [_trade(100), _trade(50, exit_reason="scale_out"), _trade(-40)]
    out = _aggregate_stitched_oos(trades, capital=10_000.0)
    assert out["totalTrades"] == 2  # scale_out leg excluded (QNT-14 convention)


def test_aggregate_stitched_oos_win_rate_and_profit():
    trades = [_trade(100), _trade(-50), _trade(200)]
    out = _aggregate_stitched_oos(trades, capital=10_000.0)
    assert out["totalTrades"] == 3
    assert out["winRate"] == "0.67"
    # (100 - 50 + 200) / 10000 * 100 = 2.50%
    assert out["netProfitPct"] == "2.50"


# ── run_lab_walk_forward (wiring, fully faked I/O) ───────────────────────────

class _FakeLabResults:
    def __init__(self):
        self.docs = {}

    async def update_one(self, query, update, upsert=False):
        lab_id = query["labId"]
        doc = self.docs.setdefault(lab_id, {})
        doc.update(update["$set"])


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length=None):
        return self._docs


class _FakeDB:
    def __init__(self, trades_by_job_id):
        self.labResults = _FakeLabResults()
        self._trades_by_job_id = trades_by_job_id

    class _Trades:
        def __init__(self, outer):
            self._outer = outer

        def find(self, query):
            job_id = query["jobId"]
            return _FakeCursor(self._outer._trades_by_job_id.get(job_id, []))

    @property
    def backtestTrades(self):
        return self._Trades(self)


def _install_fakes(monkeypatch, n_candles=400, is_sharpe=2.0, oos_sharpe=1.0, trade_pnls=(100, -50, 80)):
    times = _times(n_candles)
    monkeypatch.setattr(wf_module, "_fetch_candle_times", lambda *a, **kw: _fake_coro(times))

    async def fake_run_optimization(config, param_grid, job_id, **kwargs):
        return {
            "best": {
                "params": {"fast": 10, "slow": 30},
                "loss": -is_sharpe,
                "metrics": {"sharpeRatio": f"{is_sharpe:.2f}", "totalTrades": 40},
            },
            "results": [
                {"params": {"fast": 10, "slow": 30}, "loss": -is_sharpe, "rank": 1,
                 "metrics": {"sharpeRatio": f"{is_sharpe:.2f}", "totalTrades": 40}},
                {"params": {"fast": 5, "slow": 30}, "loss": -is_sharpe / 2, "rank": 2,
                 "metrics": {"sharpeRatio": f"{is_sharpe / 2:.2f}", "totalTrades": 12}},
            ],
        }
    monkeypatch.setattr(wf_module, "run_optimization", fake_run_optimization)

    trades_by_job_id = {}

    async def fake_run_backtest_simulation(job_id, **kwargs):
        trades_by_job_id[job_id] = [_trade(p) for p in trade_pnls]
        return {
            "jobId": job_id,
            "status": "completed",
            "metrics": {"sharpeRatio": f"{oos_sharpe:.2f}"},
            "tradeCount": len(trade_pnls),
        }
    monkeypatch.setattr(wf_module, "run_backtest_simulation", fake_run_backtest_simulation)

    fake_db = _FakeDB(trades_by_job_id)
    monkeypatch.setattr(wf_module, "get_database", lambda: fake_db)
    return fake_db


async def _fake_coro(value):
    return value


def test_run_lab_walk_forward_computes_degradation_and_persists(monkeypatch):
    fake_db = _install_fakes(monkeypatch, is_sharpe=2.0, oos_sharpe=1.0)

    config = {
        "strategyFile": "strategies/AdaptiveTrend",
        "exchange": "Binance Futures",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "startDate": "2024-01-01T00:00:00+00:00",
        "endDate": "2024-01-20T00:00:00+00:00",
        "capital": 10000,
        "leverage": 10,
        "objective": "sharpe",
        "paramGrid": {"fast": {"min": 5, "max": 15, "step": 5, "type": "int"}},
        "nFolds": 4,
        "trainRatio": 0.7,
        "mode": "rolling",
    }

    result = _run(run_lab_walk_forward("lab1", config, "hash1"))

    assert result["nFoldsBuilt"] == 4
    assert len(result["folds"]) == 4
    for f in result["folds"]:
        assert f["degradationRatio"] == pytest.approx(0.5)  # oos(1.0) / is(2.0)
        assert len(f["trials"]) == 2  # every combo run_optimization scored, not just best
        assert f["trials"][0]["params"] == {"fast": 10, "slow": 30}
        assert f["trials"][1]["rank"] == 2
    assert result["avgDegradationRatio"] == pytest.approx(0.5)
    assert result["stitchedOOS"]["totalTrades"] == 4 * 3  # 3 trades/fold x 4 folds

    assert fake_db.labResults.docs["lab1"]["status"] == "completed"
    assert fake_db.labResults.docs["lab1"]["results"] == result


def test_run_lab_walk_forward_skipped_fold_still_carries_trials(monkeypatch):
    times = _times(400)
    monkeypatch.setattr(wf_module, "_fetch_candle_times", lambda *a, **kw: _fake_coro(times))

    async def fake_run_optimization_no_eligible(config, param_grid, job_id, **kwargs):
        return {
            "best": None,
            "results": [
                {"params": {"fast": 10}, "loss": float("inf"), "rank": 1,
                 "metrics": {"totalTrades": 0}},
            ],
        }
    monkeypatch.setattr(wf_module, "run_optimization", fake_run_optimization_no_eligible)

    async def fake_run_backtest_simulation(job_id, **kwargs):
        return {"jobId": job_id, "status": "completed", "metrics": {}, "tradeCount": 0}
    monkeypatch.setattr(wf_module, "run_backtest_simulation", fake_run_backtest_simulation)

    fake_db = _FakeDB({})
    monkeypatch.setattr(wf_module, "get_database", lambda: fake_db)

    config = {
        "strategyFile": "strategies/AdaptiveTrend",
        "exchange": "Binance Futures",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "startDate": "2024-01-01T00:00:00+00:00",
        "endDate": "2024-01-20T00:00:00+00:00",
        "capital": 10000,
        "objective": "sharpe",
        "paramGrid": {"fast": {"min": 5, "max": 15, "step": 5, "type": "int"}},
        "nFolds": 4,
        "trainRatio": 0.7,
        "mode": "rolling",
    }

    result = _run(run_lab_walk_forward("lab5", config, "hash5"))
    for f in result["folds"]:
        assert f["skipped"] is True
        assert len(f["trials"]) == 1
        # inf loss must not survive into the persisted/returned trial — Python's
        # json module rejects inf/-inf/nan outright, and every trial's `loss`
        # now reaches the HTTP response (Phase 3d), not just `best`.
        assert f["trials"][0]["loss"] is None


def test_run_lab_walk_forward_trials_are_always_json_serializable(monkeypatch):
    """Regression test for the real bug this session's live browser exercise
    caught: an errored/ineligible combo's `loss=float("inf")` (optimizer.py's
    own error path) made it into `fold["trials"]` verbatim and broke
    `json.dumps` at the FastAPI response layer with `ValueError: Out of range
    float values are not JSON compliant` — a 500 that unit tests alone (which
    never call `json.dumps`) couldn't have caught."""
    import json

    fake_db = _install_fakes(monkeypatch, is_sharpe=2.0, oos_sharpe=1.0)

    async def fake_run_optimization_with_inf_and_nan(config, param_grid, job_id, **kwargs):
        return {
            "best": {
                "params": {"fast": 10, "slow": 30},
                "loss": -2.0,
                "metrics": {"sharpeRatio": "2.00", "totalTrades": 40},
            },
            "results": [
                {"params": {"fast": 10, "slow": 30}, "loss": -2.0, "rank": 1,
                 "metrics": {"sharpeRatio": "2.00", "totalTrades": 40}},
                {"params": {"fast": 5, "slow": 30}, "loss": float("inf"), "rank": 2,
                 "error": "no trades"},
                {"params": {"fast": 15, "slow": 30}, "loss": float("nan"), "rank": 3,
                 "metrics": {"totalTrades": 0}},
            ],
        }
    monkeypatch.setattr(wf_module, "run_optimization", fake_run_optimization_with_inf_and_nan)

    config = {
        "strategyFile": "strategies/AdaptiveTrend",
        "exchange": "Binance Futures",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "startDate": "2024-01-01T00:00:00+00:00",
        "endDate": "2024-01-20T00:00:00+00:00",
        "capital": 10000,
        "objective": "sharpe",
        "paramGrid": {"fast": {"min": 5, "max": 15, "step": 5, "type": "int"}},
        "nFolds": 4,
        "trainRatio": 0.7,
        "mode": "rolling",
    }

    result = _run(run_lab_walk_forward("lab6", config, "hash6"))
    json.dumps(result)  # raises ValueError if any non-finite float survived
    for f in result["folds"]:
        losses = [t["loss"] for t in f["trials"]]
        assert -2.0 in losses
        assert None in losses  # both the inf and the nan trial sanitize to None


def test_run_lab_walk_forward_rejects_unknown_objective(monkeypatch):
    _install_fakes(monkeypatch)
    config = {
        "strategyFile": "strategies/AdaptiveTrend", "exchange": "Binance Futures",
        "symbol": "BTCUSDT", "timeframe": "1h",
        "startDate": "2024-01-01T00:00:00+00:00", "endDate": "2024-01-20T00:00:00+00:00",
        "capital": 10000, "objective": "not_a_real_objective",
        "paramGrid": {"fast": {"min": 5, "max": 15, "step": 5, "type": "int"}},
    }
    with pytest.raises(ValueError, match="Unknown objective"):
        _run(run_lab_walk_forward("lab2", config, "hash2"))


def test_run_lab_walk_forward_rejects_empty_param_grid(monkeypatch):
    _install_fakes(monkeypatch)
    config = {
        "strategyFile": "strategies/AdaptiveTrend", "exchange": "Binance Futures",
        "symbol": "BTCUSDT", "timeframe": "1h",
        "startDate": "2024-01-01T00:00:00+00:00", "endDate": "2024-01-20T00:00:00+00:00",
        "capital": 10000, "paramGrid": {},
    }
    with pytest.raises(ValueError, match="paramGrid"):
        _run(run_lab_walk_forward("lab3", config, "hash3"))


def test_run_lab_walk_forward_rejects_invalid_mode(monkeypatch):
    _install_fakes(monkeypatch)
    config = {
        "strategyFile": "strategies/AdaptiveTrend", "exchange": "Binance Futures",
        "symbol": "BTCUSDT", "timeframe": "1h",
        "startDate": "2024-01-01T00:00:00+00:00", "endDate": "2024-01-20T00:00:00+00:00",
        "capital": 10000, "mode": "bogus",
        "paramGrid": {"fast": {"min": 5, "max": 15, "step": 5, "type": "int"}},
    }
    with pytest.raises(ValueError, match="mode must be"):
        _run(run_lab_walk_forward("lab4", config, "hash4"))


def test_run_lab_walk_forward_rejects_invalid_method(monkeypatch):
    _install_fakes(monkeypatch)
    config = {
        "strategyFile": "strategies/AdaptiveTrend", "exchange": "Binance Futures",
        "symbol": "BTCUSDT", "timeframe": "1h",
        "startDate": "2024-01-01T00:00:00+00:00", "endDate": "2024-01-20T00:00:00+00:00",
        "capital": 10000, "method": "bogus",
        "paramGrid": {"fast": {"min": 5, "max": 15, "step": 5, "type": "int"}},
    }
    with pytest.raises(ValueError, match="method must be"):
        _run(run_lab_walk_forward("lab7", config, "hash7"))


# ── Phase 3b: method="bayesian" dispatches the fold train step to TPE ──────

def test_run_lab_walk_forward_computes_dsr_per_fold_when_metrics_available(monkeypatch):
    """Phase 3e: with sqn/totalTrades/skewness/kurtosis present in the trial
    pool's metrics, `fold.dsr` should be a real computed value (not the
    insufficient-data 0.5 default) and stay in [0, 1]."""
    times = _times(400)
    monkeypatch.setattr(wf_module, "_fetch_candle_times", lambda *a, **kw: _fake_coro(times))

    async def fake_run_optimization(config, param_grid, job_id, **kwargs):
        return {
            "best": {
                "params": {"fast": 10, "slow": 30},
                "loss": -2.0,
                "metrics": {"sharpeRatio": "2.00", "totalTrades": 40, "sqn": "1.20",
                            "skewness": "0.10", "kurtosis": "3.20"},
            },
            "results": [
                {"params": {"fast": 10, "slow": 30}, "loss": -2.0, "rank": 1,
                 "metrics": {"sharpeRatio": "2.00", "totalTrades": 40, "sqn": "1.20",
                             "skewness": "0.10", "kurtosis": "3.20"}},
                {"params": {"fast": 5, "slow": 30}, "loss": -0.5, "rank": 2,
                 "metrics": {"sharpeRatio": "0.50", "totalTrades": 35, "sqn": "0.30",
                             "skewness": "0.05", "kurtosis": "2.90"}},
                {"params": {"fast": 8, "slow": 30}, "loss": -0.3, "rank": 3,
                 "metrics": {"sharpeRatio": "0.30", "totalTrades": 38, "sqn": "0.18",
                             "skewness": "-0.02", "kurtosis": "3.10"}},
            ],
        }
    monkeypatch.setattr(wf_module, "run_optimization", fake_run_optimization)

    async def fake_run_backtest_simulation(job_id, **kwargs):
        return {"jobId": job_id, "status": "completed",
                "metrics": {"sharpeRatio": "1.00"}, "tradeCount": 3}
    monkeypatch.setattr(wf_module, "run_backtest_simulation", fake_run_backtest_simulation)

    fake_db = _FakeDB({})
    monkeypatch.setattr(wf_module, "get_database", lambda: fake_db)

    config = {
        "strategyFile": "strategies/AdaptiveTrend", "exchange": "Binance Futures",
        "symbol": "BTCUSDT", "timeframe": "1h",
        "startDate": "2024-01-01T00:00:00+00:00", "endDate": "2024-01-20T00:00:00+00:00",
        "capital": 10000, "objective": "sharpe",
        "paramGrid": {"fast": {"min": 5, "max": 15, "step": 5, "type": "int"}},
        "nFolds": 4, "trainRatio": 0.7, "mode": "rolling",
    }

    result = _run(run_lab_walk_forward("lab9", config, "hash9"))
    for f in result["folds"]:
        assert "dsr" in f
        assert f["dsr"]["insufficientData"] is False
        assert 0.0 <= f["dsr"]["dsr"] <= 1.0
        assert f["dsr"]["nTrials"] == 3


def test_run_lab_walk_forward_skipped_fold_carries_uninformative_dsr(monkeypatch):
    times = _times(400)
    monkeypatch.setattr(wf_module, "_fetch_candle_times", lambda *a, **kw: _fake_coro(times))

    async def fake_run_optimization_no_eligible(config, param_grid, job_id, **kwargs):
        return {
            "best": None,
            "results": [
                {"params": {"fast": 10}, "loss": float("inf"), "rank": 1,
                 "metrics": {"totalTrades": 0}},
            ],
        }
    monkeypatch.setattr(wf_module, "run_optimization", fake_run_optimization_no_eligible)

    async def fake_run_backtest_simulation(job_id, **kwargs):
        return {"jobId": job_id, "status": "completed", "metrics": {}, "tradeCount": 0}
    monkeypatch.setattr(wf_module, "run_backtest_simulation", fake_run_backtest_simulation)

    fake_db = _FakeDB({})
    monkeypatch.setattr(wf_module, "get_database", lambda: fake_db)

    config = {
        "strategyFile": "strategies/AdaptiveTrend", "exchange": "Binance Futures",
        "symbol": "BTCUSDT", "timeframe": "1h",
        "startDate": "2024-01-01T00:00:00+00:00", "endDate": "2024-01-20T00:00:00+00:00",
        "capital": 10000, "objective": "sharpe",
        "paramGrid": {"fast": {"min": 5, "max": 15, "step": 5, "type": "int"}},
        "nFolds": 4, "trainRatio": 0.7, "mode": "rolling",
    }

    result = _run(run_lab_walk_forward("lab10", config, "hash10"))
    for f in result["folds"]:
        assert f["dsr"] == {"dsr": 0.5, "expectedMaxSharpe": None, "nTrials": 0, "insufficientData": True}


def test_run_lab_walk_forward_bayesian_method_dispatches_to_bayesian_optimizer(monkeypatch):
    """Grid dispatch is covered by every other test in this file (the default
    fake patches `run_optimization`). This confirms `method: "bayesian"`
    calls `run_bayesian_optimization` instead — with `nTrials` and a
    per-fold-offset seed — and that grid's `run_optimization` is left
    untouched (never called) in that mode."""
    times = _times(400)
    monkeypatch.setattr(wf_module, "_fetch_candle_times", lambda *a, **kw: _fake_coro(times))

    grid_calls = []

    async def fake_run_optimization(config, param_grid, job_id, **kwargs):
        grid_calls.append(job_id)
        raise AssertionError("grid optimizer must not be called in bayesian mode")
    monkeypatch.setattr(wf_module, "run_optimization", fake_run_optimization)

    bayesian_calls = []

    async def fake_run_bayesian_optimization(config, param_grid, n_trials, job_id, seed=42, **kwargs):
        bayesian_calls.append({"job_id": job_id, "n_trials": n_trials, "seed": seed})
        return {
            "best": {
                "params": {"fast": 10},
                "loss": -2.0,
                "metrics": {"sharpeRatio": "2.00", "totalTrades": 40},
            },
            "results": [
                {"params": {"fast": 10}, "loss": -2.0, "rank": 1,
                 "metrics": {"sharpeRatio": "2.00", "totalTrades": 40}},
            ],
        }
    monkeypatch.setattr(wf_module, "run_bayesian_optimization", fake_run_bayesian_optimization)

    async def fake_run_backtest_simulation(job_id, **kwargs):
        return {"jobId": job_id, "status": "completed",
                "metrics": {"sharpeRatio": "1.00"}, "tradeCount": 3}
    monkeypatch.setattr(wf_module, "run_backtest_simulation", fake_run_backtest_simulation)

    fake_db = _FakeDB({})
    monkeypatch.setattr(wf_module, "get_database", lambda: fake_db)

    config = {
        "strategyFile": "strategies/AdaptiveTrend", "exchange": "Binance Futures",
        "symbol": "BTCUSDT", "timeframe": "1h",
        "startDate": "2024-01-01T00:00:00+00:00", "endDate": "2024-01-20T00:00:00+00:00",
        "capital": 10000, "objective": "sharpe",
        "paramGrid": {"fast": {"min": 5, "max": 15, "step": 5, "type": "int"}},
        "nFolds": 4, "trainRatio": 0.7, "mode": "rolling",
        "method": "bayesian", "nTrials": 25,
    }

    result = _run(run_lab_walk_forward("lab8", config, "hash8"))

    assert grid_calls == []
    assert len(bayesian_calls) == 4  # one per fold
    assert all(c["n_trials"] == 25 for c in bayesian_calls)
    seeds = [c["seed"] for c in bayesian_calls]
    assert seeds == sorted(seeds)  # distinct-but-deterministic per fold
    assert len(set(seeds)) == 4

    assert result["method"] == "bayesian"
    assert result["nTrials"] == 25
    for f in result["folds"]:
        assert f["bestParams"] == {"fast": 10}


# ── Phase 4a: MC-scored trial selection (`_eligible_trials` + `_mc_score_fold`,
# wired end-to-end through `run_lab_walk_forward`) ──────────────────────────
#
# This coverage did not exist before this session — `mcScoring`/`mcTopK` were
# never read out of the request body at all (server/src/utils/labConfig.js
# gap, fixed alongside these tests), so the already-built engine feature was
# unreachable via the API and untested end-to-end. Cannot execute these
# locally (no Docker/asyncpg/numpy verification in this sandbox, per this
# project's disclosed environment constraints) — written and reasoned through
# against the actual `_eligible_trials`/`_mc_score_fold` implementation in
# `services/walk_forward.py`, not executed.

def test_eligible_trials_filters_by_min_trades_and_finite_loss():
    trials = [
        {"params": {"fast": 10}, "loss": -2.0, "rank": 1, "metrics": {"totalTrades": 40}},
        {"params": {"fast": 5}, "loss": -1.5, "rank": 2, "metrics": {"totalTrades": 35}},
        {"params": {"fast": 3}, "loss": -1.0, "rank": 3, "metrics": {"totalTrades": 5}},  # below bar
        {"params": {"fast": 1}, "loss": None, "rank": 4, "metrics": {"totalTrades": 999}},  # errored trial
    ]
    eligible = _eligible_trials(trials, min_trades=10)
    assert [t["rank"] for t in eligible] == [1, 2]
    # `eligible[0]` must always be identical to the fold's own raw-loss
    # winner (rank 1) — `_mc_score_fold` reuses its OOS result rather than
    # re-running it, and that identity is load-bearing, not incidental.
    assert eligible[0]["params"] == {"fast": 10}


def test_eligible_trials_min_trades_zero_still_drops_errored_entries():
    trials = [
        {"params": {"fast": 10}, "loss": -2.0, "rank": 1, "metrics": {"totalTrades": 2}},
        {"params": {"fast": 1}, "loss": None, "rank": 2, "metrics": {"totalTrades": 999}},
    ]
    eligible = _eligible_trials(trials, min_trades=0)
    assert [t["rank"] for t in eligible] == [1]


def test_mc_scoring_disabled_by_default_no_mcscoring_key(monkeypatch):
    """Zero behavior change for every existing run that doesn't opt in —
    the central guarantee `mcScoring: default False` makes."""
    _install_fakes(monkeypatch)
    config = {
        "strategyFile": "strategies/AdaptiveTrend", "exchange": "Binance Futures",
        "symbol": "BTCUSDT", "timeframe": "1h",
        "startDate": "2024-01-01T00:00:00+00:00", "endDate": "2024-01-20T00:00:00+00:00",
        "capital": 10000, "objective": "sharpe",
        "paramGrid": {"fast": {"min": 5, "max": 15, "step": 5, "type": "int"}},
        "nFolds": 4, "trainRatio": 0.7, "mode": "rolling",
    }
    result = _run(run_lab_walk_forward("lab12", config, "hash12"))
    for f in result["folds"]:
        assert "mcScoring" not in f


def test_mc_scoring_end_to_end_reuses_raw_pick_oos_and_ranks_by_mc_p5(monkeypatch):
    """End-to-end Phase 4a wiring: mcTopK=3 but only 2 of 3 trials clear the
    minTrades=10 eligibility bar, so only 1 extra OOS backtest is run (rank
    2 — rank 1 reuses the fold's own existing OOS job, never re-run). Rank
    1's OOS trades are constructed with the same net profit as a smooth,
    all-small-wins run BUT concentrated into a big tail loss — the kind of
    fragility a single point-estimate metric hides and MC p5 is designed to
    catch. Rank 2's trades are deliberately low-variance. The MC-robust pick
    must therefore differ from the raw point-estimate pick (which is always
    rank 1, `eligible[0]`)."""
    times = _times(400)
    monkeypatch.setattr(wf_module, "_fetch_candle_times", lambda *a, **kw: _fake_coro(times))

    async def fake_run_optimization(config, param_grid, job_id, **kwargs):
        return {
            "best": {
                "params": {"fast": 10}, "loss": -2.0,
                "metrics": {"sharpeRatio": "2.00", "totalTrades": 40},
            },
            "results": [
                {"params": {"fast": 10}, "loss": -2.0, "rank": 1,
                 "metrics": {"sharpeRatio": "2.00", "totalTrades": 40}},
                {"params": {"fast": 5}, "loss": -1.5, "rank": 2,
                 "metrics": {"sharpeRatio": "1.50", "totalTrades": 35}},
                {"params": {"fast": 3}, "loss": -1.0, "rank": 3,
                 "metrics": {"sharpeRatio": "1.00", "totalTrades": 5}},  # below minTrades=10, ineligible
            ],
        }
    monkeypatch.setattr(wf_module, "run_optimization", fake_run_optimization)

    trades_by_job_id = {}
    backtest_calls = []

    async def fake_run_backtest_simulation(job_id, **kwargs):
        backtest_calls.append(job_id)
        if job_id.endswith("_test_k2"):
            # rank-2's extra Phase 4a OOS run — low-variance, consistently
            # small-positive trades.
            pnls = [1] * 15
        else:
            # the fold's own raw-pick OOS run (rank 1, reused as `best_oos`)
            # — concentrated into one large tail loss offsetting many small
            # wins (much higher variance than rank 2's smooth run above).
            pnls = [50] * 14 + [-700]
        trades_by_job_id[job_id] = [_trade(p) for p in pnls]
        net_pct = f"{sum(pnls) / 10000 * 100:.2f}"
        return {
            "jobId": job_id, "status": "completed",
            "metrics": {"sharpeRatio": "1.00", "netProfitPct": net_pct},
            "tradeCount": len(pnls),
        }
    monkeypatch.setattr(wf_module, "run_backtest_simulation", fake_run_backtest_simulation)

    fake_db = _FakeDB(trades_by_job_id)
    monkeypatch.setattr(wf_module, "get_database", lambda: fake_db)

    config = {
        "strategyFile": "strategies/AdaptiveTrend", "exchange": "Binance Futures",
        "symbol": "BTCUSDT", "timeframe": "1h",
        "startDate": "2024-01-01T00:00:00+00:00", "endDate": "2024-01-20T00:00:00+00:00",
        "capital": 10000, "objective": "sharpe",
        "paramGrid": {"fast": {"min": 3, "max": 10, "step": 1, "type": "int"}},
        "nFolds": 1, "trainRatio": 0.7, "mode": "rolling",
        "minTrades": 10, "mcScoring": True, "mcTopK": 3,
    }

    result = _run(run_lab_walk_forward("lab13", config, "hash13"))

    fold = result["folds"][0]
    scoring = fold["mcScoring"]
    assert scoring["enabled"] is True
    # topK reflects candidates actually eligible/scored (2), not the
    # requested cap (3) — rank 3 (totalTrades=5) fails minTrades=10.
    assert scoring["topK"] == 2
    assert len(scoring["candidates"]) == 2
    assert scoring["runsPerCandidate"] == wf_module.MC_SCORING_RUNS

    main_test_job = "wf_lab13_fold0_test"
    candidate_test_job = "wf_lab13_fold0_test_k2"
    # Rank 1 (the raw pick, i=0 in `_mc_score_fold`) must reuse the fold's
    # existing OOS backtest — no duplicate `run_backtest_simulation` call for
    # the job id it already has metrics/trades for.
    assert backtest_calls.count(main_test_job) == 1  # only the fold's own normal OOS call
    assert backtest_calls.count(candidate_test_job) == 1  # rank 2's extra Phase 4a call

    rank1 = next(c for c in scoring["candidates"] if c["rank"] == 1)
    rank2 = next(c for c in scoring["candidates"] if c["rank"] == 2)
    assert rank1["insufficientData"] is False
    assert rank2["insufficientData"] is False

    # Raw pick is always the fold's own raw-loss winner (rank 1, `scored[0]`).
    assert scoring["rawPick"]["rank"] == 1
    # But the MC-robust pick prefers rank 2 — its consistent small-win trade
    # set has a far higher block-bootstrap p5 outcome than rank 1's
    # tail-loss-concentrated trade set with the same headline net profit,
    # which is exactly the fragility gap this feature exists to surface.
    assert scoring["robustPick"]["rank"] == 2
    assert scoring["robustPick"]["mc"]["p5ProfitPct"] > rank1["mc"]["p5ProfitPct"]


# ── Phase 4b: risk_pct/leverage search threading ────────────────────────────

def test_risk_leverage_grid_is_passed_to_run_optimization_and_overrides_oos_call(monkeypatch):
    """End-to-end: `config.riskLeverageGrid` reaches `run_optimization` (the
    per-fold train step), and the winning trial's OWN `riskLeverage` (not the
    job's flat `leverage`/`riskParams` default) is what the fold's OOS test
    call actually uses — the central correctness property of this feature,
    per its own module-docstring guarantee."""
    times = _times(400)
    monkeypatch.setattr(wf_module, "_fetch_candle_times", lambda *a, **kw: _fake_coro(times))

    optimization_calls = []

    async def fake_run_optimization(config, param_grid, job_id, **kwargs):
        optimization_calls.append(kwargs.get("risk_leverage_grid"))
        return {
            "best": {
                "params": {"fast": 10},
                "riskLeverage": {"risk_pct": 0.02, "leverage": 20},
                "loss": -2.0,
                "metrics": {"sharpeRatio": "2.00", "totalTrades": 40},
            },
            "results": [
                {"params": {"fast": 10}, "riskLeverage": {"risk_pct": 0.02, "leverage": 20},
                 "loss": -2.0, "rank": 1, "metrics": {"sharpeRatio": "2.00", "totalTrades": 40}},
            ],
        }
    monkeypatch.setattr(wf_module, "run_optimization", fake_run_optimization)

    oos_calls = []

    async def fake_run_backtest_simulation(job_id, **kwargs):
        oos_calls.append({"leverage": kwargs["leverage"], "risk_params": kwargs["risk_params"]})
        return {"jobId": job_id, "status": "completed",
                "metrics": {"sharpeRatio": "1.00"}, "tradeCount": 3}
    monkeypatch.setattr(wf_module, "run_backtest_simulation", fake_run_backtest_simulation)

    fake_db = _FakeDB({})
    monkeypatch.setattr(wf_module, "get_database", lambda: fake_db)

    config = {
        "strategyFile": "strategies/AdaptiveTrend", "exchange": "Binance Futures",
        "symbol": "BTCUSDT", "timeframe": "1h",
        "startDate": "2024-01-01T00:00:00+00:00", "endDate": "2024-01-20T00:00:00+00:00",
        "capital": 10000, "objective": "sharpe", "leverage": 10,  # job default — must NOT survive
        "riskParams": {"rrr": 2.0},  # job default risk_params — rrr must survive, risk_pct must override
        "paramGrid": {"fast": {"min": 5, "max": 15, "step": 5, "type": "int"}},
        "nFolds": 4, "trainRatio": 0.7, "mode": "rolling",
        "riskLeverageGrid": {"risk_pct": {"values": [0.01, 0.02]}, "leverage": {"values": [10, 20]}},
    }

    result = _run(run_lab_walk_forward("lab14", config, "hash14"))

    # The grid reached every fold's train step, not dropped anywhere in transit.
    assert all(g == config["riskLeverageGrid"] for g in optimization_calls)
    assert len(optimization_calls) == 4  # one per fold

    # Every fold's OOS test call used the winning trial's OWN risk/leverage
    # (20x / risk_pct=0.02), never the job's flat default (10x).
    assert all(c["leverage"] == 20 for c in oos_calls)
    assert all(c["risk_params"]["risk_pct"] == 0.02 for c in oos_calls)
    # The job's own risk_params (rrr) survives the override untouched.
    assert all(c["risk_params"]["rrr"] == 2.0 for c in oos_calls)

    for f in result["folds"]:
        assert f["bestRiskLeverage"] == {"risk_pct": 0.02, "leverage": 20}
    assert result["meta"]["riskLeverageGrid"] == config["riskLeverageGrid"]


def test_no_risk_leverage_grid_means_zero_behavior_change(monkeypatch):
    """The central guarantee: a run that doesn't set `riskLeverageGrid` must
    behave identically to before this feature existed — job-level leverage/
    riskParams reach every OOS call unchanged, `bestRiskLeverage` is None."""
    fake_db = _install_fakes(monkeypatch, is_sharpe=2.0, oos_sharpe=1.0)

    config = {
        "strategyFile": "strategies/AdaptiveTrend", "exchange": "Binance Futures",
        "symbol": "BTCUSDT", "timeframe": "1h",
        "startDate": "2024-01-01T00:00:00+00:00", "endDate": "2024-01-20T00:00:00+00:00",
        "capital": 10000, "leverage": 10, "objective": "sharpe",
        "paramGrid": {"fast": {"min": 5, "max": 15, "step": 5, "type": "int"}},
        "nFolds": 4, "trainRatio": 0.7, "mode": "rolling",
    }
    result = _run(run_lab_walk_forward("lab15", config, "hash15"))
    for f in result["folds"]:
        assert f["bestRiskLeverage"] is None
    assert result["meta"]["riskLeverageGrid"] is None
