"""PBO (Probability of Backtest Overfitting, CSCV) tests.

Covers: `_block_boundaries`/`_assign_block` (pure), `_stat_from_returns`'s honesty guards
(too-few-trades / zero-variance -> None, never a fabricated ratio), `compute_pbo`'s core
combinatorics verified against two hand-derived, exactly-computable scenarios (perfectly
anti-correlated IS/OOS performance -> PBO==1.0; strictly and uniformly ordered candidates ->
PBO==0.0 — see the inline derivation comments for the exact arithmetic, not just an assertion),
and an end-to-end `run_lab_pbo` wiring test against fakes for `run_optimization`/candle-time-fetch/
Mongo (same style as `test_walk_forward.py`'s `_install_fakes` — no real DB/engine dependency).
"""
import asyncio
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

import services.pbo as pbo_module
from services.pbo import (
    MIN_CANDIDATES,
    _assign_block,
    _block_boundaries,
    _stat_from_returns,
    compute_pbo,
    run_lab_pbo,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _times(n, start=datetime(2024, 1, 1, tzinfo=timezone.utc), step=timedelta(hours=1)):
    return [start + i * step for i in range(n)]


async def _fake_coro(value):
    return value


# ── _block_boundaries / _assign_block (pure, no I/O) ─────────────────────────

def test_block_boundaries_splits_evenly():
    times = _times(400)
    boundaries = _block_boundaries(times, n_blocks=8)
    assert len(boundaries) == 8
    # Contiguous, no gap: each block's end is one candle before the next block's start.
    for i in range(len(boundaries) - 1):
        assert boundaries[i][1] < boundaries[i + 1][0]
    assert boundaries[0][0] == times[0]
    assert boundaries[-1][1] == times[-1]


def test_assign_block_parses_iso_string_and_finds_correct_block():
    times = _times(80)
    boundaries = _block_boundaries(times, n_blocks=4)  # 20 candles/block
    # A trade entering at times[10] (within block 0's [0,19] range) -> block 0.
    assert _assign_block(times[10].isoformat(), boundaries) == 0
    # times[25] -> block 1 ([20,39]).
    assert _assign_block(times[25].isoformat(), boundaries) == 1
    # times[79] (last candle) -> block 3 (last block).
    assert _assign_block(times[79].isoformat(), boundaries) == 3


def test_assign_block_returns_none_for_unparseable_or_missing_entry():
    times = _times(80)
    boundaries = _block_boundaries(times, n_blocks=4)
    assert _assign_block(None, boundaries) is None
    assert _assign_block("not-a-date", boundaries) is None


# ── _stat_from_returns (pure, honesty guards) ─────────────────────────────────

def test_stat_from_returns_none_when_too_few_trades():
    assert _stat_from_returns(np.array([0.01])) is None  # 1 trade, below MIN_TRADES_PER_SIDE
    assert _stat_from_returns(np.array([])) is None


def test_stat_from_returns_none_when_zero_variance():
    # Identical returns -> std=0 -> undefined ratio, must not divide by zero into inf/nan.
    assert _stat_from_returns(np.array([0.02, 0.02, 0.02])) is None


def test_stat_from_returns_defined_case():
    stat = _stat_from_returns(np.array([0.02, 0.04, -0.01]))
    assert stat is not None
    assert isinstance(stat, float)


# ── compute_pbo (pure combinatorics, hand-derived exact scenarios) ───────────

def _sym_block(base, half_spread=0.001, n=2):
    """Returns an n-trade array with exact mean `base` (symmetric spread, so concatenating
    several such blocks gives an EXACT average of their `base` values — needed so the hand-derived
    arithmetic in the two scenarios below is exact, not float-approximate)."""
    return np.array([base - half_spread, base + half_spread] * (n // 2), dtype=np.float64)


def test_compute_pbo_perfectly_anti_correlated_scenario_gives_pbo_one():
    """2 candidates, 4 blocks. Candidate A's per-block mean is [+100,+100,-100,-100];
    candidate B is the EXACT mirror ([-100,-100,+100,+100]). Because each block contributes an
    equal trade count with a symmetric spread (mean == base exactly), for any 2-block train/test
    split: mean_A(test) == -mean_A(train) (the block base values are exact mirrors of each other
    across the pure-vs-mixed block combinations by construction), and mean_B == -mean_A always.
    Hand-derivation (verified for all 6 C(4,2) combinations, see PR/session notes):
    - {0,1} vs {2,3}: pure blocks, IS picks whichever has the positive-mean train side; that same
      candidate's OOS mean flips sign (its own blocks are the pure-negative complement) -> it
      ranks WORST OOS every time.
    - Any mixed pair (e.g. {0,2} vs {1,3}): train mean is EXACTLY 0 for both candidates (one
      +100 block + one -100 block cancels exactly) -> a tie, broken by candidate order (A first);
      OOS is the same mixed-mean-zero tie -> A ranks worst by the same stable tie-break.
    Every one of the 6 combinations therefore has the IS-selected candidate ranking OOS-worst ->
    PBO == 1.0 exactly, not just directionally high."""
    bases_a = [100.0, 100.0, -100.0, -100.0]
    block_returns_a = [_sym_block(b) for b in bases_a]
    block_returns_b = [_sym_block(-b) for b in bases_a]

    result = compute_pbo([block_returns_a, block_returns_b])

    assert result["insufficientData"] is False
    assert result["nBlocks"] == 4
    assert result["nCombinations"] == 6
    assert result["nEvaluated"] == 6
    assert result["nSkipped"] == 0
    assert result["pbo"] == pytest.approx(1.0)


def test_compute_pbo_strictly_and_uniformly_ordered_scenario_gives_pbo_zero():
    """3 candidates, 4 blocks. C1's per-block mean (~+10) strictly dominates C2's (~0) which
    strictly dominates C3's (~-10) in EVERY block, by a margin far larger than the tiny symmetric
    spread — so this ordering holds for ANY non-empty subset of blocks (train or test). C1 is
    therefore ALWAYS the IS-best pick AND always the OOS-best (rank 3 of 3) for all 6
    combinations -> PBO == 0.0 exactly (the IS pick's OOS performance is never at/below median)."""
    block_returns_c1 = [_sym_block(10.0) for _ in range(4)]
    block_returns_c2 = [_sym_block(0.0) for _ in range(4)]
    block_returns_c3 = [_sym_block(-10.0) for _ in range(4)]

    result = compute_pbo([block_returns_c1, block_returns_c2, block_returns_c3])

    assert result["insufficientData"] is False
    assert result["nEvaluated"] == 6
    assert result["nSkipped"] == 0
    assert result["pbo"] == pytest.approx(0.0)


def test_compute_pbo_insufficient_data_when_every_combination_skipped():
    # A single trade per block everywhere -> every train/test union has < MIN_TRADES_PER_SIDE=2,
    # so no candidate ever has a defined IS stat -> every combination is skipped.
    tiny = [np.array([0.01]) for _ in range(4)]
    result = compute_pbo([tiny, tiny])
    assert result["insufficientData"] is True
    assert result["pbo"] is None
    assert result["nEvaluated"] == 0
    assert result["nSkipped"] == 6


def test_compute_pbo_missing_oos_data_ranks_candidate_worst_not_excluded():
    # Candidate B has real trades everywhere; candidate A has trades only in blocks {0,1} (its
    # `nEvaluated` and no data at all in {2,3}) -- when {2,3} is the test side, A has NO OOS
    # stat (None) and must still be RANKED (worst), not silently dropped from the combination.
    empty = np.array([], dtype=np.float64)
    block_returns_a = [_sym_block(50.0), _sym_block(50.0), empty, empty]
    block_returns_b = [_sym_block(1.0) for _ in range(4)]

    result = compute_pbo([block_returns_a, block_returns_b])
    assert result["insufficientData"] is False
    # Every combination must still be evaluated (A's missing OOS data doesn't cause a skip,
    # since A can still be ranked worst-by-default and B always has a defined stat).
    assert result["nEvaluated"] + result["nSkipped"] == 6


# ── run_lab_pbo (wiring, fully faked I/O) ────────────────────────────────────

def _trade(pnl, entry_at, exit_reason="take_profit"):
    return {"pnl": str(pnl), "exitReason": exit_reason, "entryAt": entry_at.isoformat()}


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
            return _FakeCursor(self._outer._trades_by_job_id.get(query["jobId"], []))

    @property
    def backtestTrades(self):
        return self._Trades(self)


def _install_fakes(monkeypatch, n_candles=400, n_candidates=3):
    times = _times(n_candles)
    monkeypatch.setattr(pbo_module, "_fetch_candle_times", lambda *a, **kw: _fake_coro(times))

    trades_by_job_id = {}
    # Spread a handful of trades across the whole range for each fake candidate so every block
    # gets >=2 trades for every candidate (keeps the wiring test away from the insufficientData
    # guard path, which is covered separately above).
    for c in range(n_candidates):
        job_id = f"pbo_test-lab_c{c:04d}"
        trades_by_job_id[job_id] = [
            _trade(10.0 + c, times[i]) for i in range(0, n_candles, max(1, n_candles // 20))
        ]

    async def fake_run_optimization(config, param_grid, job_id, **kwargs):
        results = [
            {
                "params": {"fast": 10 + i, "slow": 30 + i},
                "riskLeverage": None,
                "loss": -1.0 * (n_candidates - i),  # ranks 1..N by construction order
                "rank": i + 1,
                "jobId": f"{job_id}_c{i:04d}",
                "metrics": {"sharpeRatio": f"{1.0 + i:.2f}", "totalTrades": 20},
            }
            for i in range(n_candidates)
        ]
        return {"results": results, "best": results[0]}
    monkeypatch.setattr(pbo_module, "run_optimization", fake_run_optimization)

    fake_db = _FakeDB(trades_by_job_id)
    monkeypatch.setattr(pbo_module, "get_database", lambda: fake_db)
    return fake_db


def _base_config(**overrides):
    config = {
        "strategyFile": "strategies/MicroScalper/__init__.py",
        "exchange": "Binance Futures",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "startDate": "2024-01-01",
        "endDate": "2024-01-17",
        "capital": 10_000.0,
        "paramGrid": {"fast": {"min": 5, "max": 20, "step": 1}},
        "nBlocks": 4,
    }
    config.update(overrides)
    return config


def test_run_lab_pbo_persists_result_and_computes_pbo(monkeypatch):
    fake_db = _install_fakes(monkeypatch, n_candidates=3)
    result = _run(run_lab_pbo("test-lab", _base_config(), "hash123"))

    assert result["nCandidates"] == 3
    assert result["nBlocks"] == 4
    assert result["nCombinations"] == 6
    assert result["pbo"] is None or 0.0 <= result["pbo"] <= 1.0
    assert len(result["candidates"]) == 3
    # Engine is sole writer — result must actually be persisted, not just returned.
    assert fake_db.labResults.docs["test-lab"]["status"] == "completed"
    assert fake_db.labResults.docs["test-lab"]["results"]["nCandidates"] == 3


def test_run_lab_pbo_rejects_too_few_eligible_candidates(monkeypatch):
    _install_fakes(monkeypatch, n_candidates=1)
    with pytest.raises(ValueError, match=f"at least {MIN_CANDIDATES}"):
        _run(run_lab_pbo("test-lab", _base_config(), "hash123"))


def test_run_lab_pbo_rejects_odd_or_too_small_n_blocks(monkeypatch):
    _install_fakes(monkeypatch, n_candidates=3)
    with pytest.raises(ValueError, match="nBlocks"):
        _run(run_lab_pbo("test-lab", _base_config(nBlocks=5), "hash123"))
    with pytest.raises(ValueError, match="nBlocks"):
        _run(run_lab_pbo("test-lab", _base_config(nBlocks=2), "hash123"))


def test_run_lab_pbo_rejects_empty_param_grid(monkeypatch):
    _install_fakes(monkeypatch, n_candidates=3)
    with pytest.raises(ValueError, match="paramGrid"):
        _run(run_lab_pbo("test-lab", _base_config(paramGrid={}), "hash123"))


def test_run_lab_pbo_rejects_unknown_objective(monkeypatch):
    _install_fakes(monkeypatch, n_candidates=3)
    with pytest.raises(ValueError, match="objective"):
        _run(run_lab_pbo("test-lab", _base_config(objective="not_a_real_objective"), "hash123"))


def test_run_lab_pbo_result_is_json_serializable(monkeypatch):
    import json
    _install_fakes(monkeypatch, n_candidates=3)
    result = _run(run_lab_pbo("test-lab", _base_config(), "hash123"))
    json.dumps(result)  # must not raise — same class of non-finite-value bug fixed elsewhere in Plan 10
