"""Job-based Monte Carlo lab simulation tests (Plan 10 Phase 1).

Covers: config-driven mode/runs/blockLen/ruinThreshold/seed handling,
deterministic seeding derived from sourceJobId+configHash (reproducible
regardless of simId), the iid-vs-block mode distinction, empty-trades
default, and that `labResults` is written with status='completed' + results
(engine sole-writer contract, mirroring backtestResults).

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_lab_simulation.py
"""
import asyncio

import pytest

import services.monte_carlo as mc_module
from services.monte_carlo import run_lab_simulation


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length=None):
        return self._docs


class _FakeLabResults:
    def __init__(self):
        self.docs = {}

    async def update_one(self, query, update, upsert=False):
        lab_id = query["labId"]
        doc = self.docs.setdefault(lab_id, {})
        doc.update(update["$set"])


class _FakeDB:
    def __init__(self, capital, trades):
        self._capital = capital
        self._trades = trades
        self.labResults = _FakeLabResults()

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
    return fake_db


def _trade(pnl, exit_reason="take_profit"):
    return {"pnl": str(pnl), "exitReason": exit_reason}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_empty_trades_writes_default_completed_doc(monkeypatch):
    fake_db = _install_fake_db(monkeypatch, capital=10_000.0, trades=[])
    result = _run(run_lab_simulation("sim1", "job1", config={}, config_hash="h1"))
    assert result["ruinProbability"] == "0.000"
    assert fake_db.labResults.docs["sim1"]["status"] == "completed"
    assert fake_db.labResults.docs["sim1"]["results"] == result


def test_rejects_invalid_mode(monkeypatch):
    _install_fake_db(monkeypatch, capital=10_000.0, trades=[_trade(100)])
    with pytest.raises(ValueError, match="invalid mode"):
        _run(run_lab_simulation("sim2", "job2", config={"mode": "bogus"}, config_hash="h2"))


def test_deterministic_seed_from_source_and_confighash_not_simid(monkeypatch):
    trades = [_trade(p) for p in (120, -80, 50, -30, 200, -100, 40, -60, 90, -20)]
    _install_fake_db(monkeypatch, capital=10_000.0, trades=trades)

    result_a = _run(run_lab_simulation("sim-a", "stable-job", config={"runs": 1000}, config_hash="same-hash"))
    result_b = _run(run_lab_simulation("sim-b", "stable-job", config={"runs": 1000}, config_hash="same-hash"))

    # Different simId, same sourceJobId+configHash -> identical draw sequence.
    assert result_a["equityBands"] == result_b["equityBands"]
    assert result_a["ruinProbability"] == result_b["ruinProbability"]


def test_explicit_seed_overrides_derived_seed(monkeypatch):
    trades = [_trade(p) for p in (120, -80, 50, -30, 200, -100, 40, -60, 90, -20)]
    _install_fake_db(monkeypatch, capital=10_000.0, trades=trades)

    result_a = _run(run_lab_simulation("sim-a", "job", config={"runs": 500, "seed": 7}, config_hash="hash-x"))
    result_b = _run(run_lab_simulation("sim-b", "job", config={"runs": 500, "seed": 7}, config_hash="hash-y"))

    assert result_a["meta"]["seed"] == 7
    assert result_b["meta"]["seed"] == 7
    assert result_a["equityBands"] == result_b["equityBands"]


def test_iid_mode_differs_from_block_mode(monkeypatch):
    trades = [_trade(p) for p in ([-500, 300, -400, 200, -600, 100, -300, 150] * 5)]
    _install_fake_db(monkeypatch, capital=10_000.0, trades=trades)

    block_result = _run(run_lab_simulation("sim-block", "job", config={"mode": "block", "seed": 99, "runs": 2000}, config_hash="h"))
    iid_result = _run(run_lab_simulation("sim-iid", "job", config={"mode": "iid", "seed": 99, "runs": 2000}, config_hash="h"))

    assert block_result["meta"]["mode"] == "block"
    assert iid_result["meta"]["mode"] == "iid"
    assert iid_result["meta"]["blockLength"] is None
    assert block_result["equityBands"] != iid_result["equityBands"]


def test_runs_are_clamped_to_documented_cap(monkeypatch):
    trades = [_trade(p) for p in (100, -50, 40, -30)]
    _install_fake_db(monkeypatch, capital=10_000.0, trades=trades)

    result = _run(run_lab_simulation("sim3", "job3", config={"runs": 50_000}, config_hash="h3"))
    assert result["meta"]["nRuns"] == mc_module.MAX_RUN_COUNT


def test_equity_bands_downsampled_and_ordered(monkeypatch):
    trades = [_trade(p) for p in ([-500, 300, -400, 200, -600, 100, -300, 150] * 100)]  # 800 trades
    _install_fake_db(monkeypatch, capital=10_000.0, trades=trades)

    result = _run(run_lab_simulation("sim4", "job4", config={"runs": 500}, config_hash="h4"))
    bands = result["equityBands"]
    assert len(bands["tradeIndices"]) <= mc_module.EQUITY_BAND_MAX_POINTS
    assert len(bands["p50"]) == len(bands["tradeIndices"])
    for i in range(len(bands["p50"])):
        assert bands["p5"][i] <= bands["p25"][i] <= bands["p50"][i] <= bands["p75"][i] <= bands["p95"][i]


def test_writes_completed_status_to_labresults(monkeypatch):
    fake_db = _install_fake_db(monkeypatch, capital=10_000.0, trades=[_trade(100), _trade(-50)])
    _run(run_lab_simulation("sim5", "job5", config={"runs": 200}, config_hash="h5"))
    assert fake_db.labResults.docs["sim5"]["status"] == "completed"
    assert "results" in fake_db.labResults.docs["sim5"]
    assert "completedAt" in fake_db.labResults.docs["sim5"]
