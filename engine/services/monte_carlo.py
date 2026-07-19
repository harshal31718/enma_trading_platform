"""Monte Carlo robustness simulation (Plan 10 §3.3 methodology, QNT-7/QNT-14).

Vectorized block-bootstrap replacing the previous O(n_runs * n_trades) pure-
Python i.i.d. loop. Preserves the existing response contract (`ruinProbability`,
`drawdownDistribution`) so the current synchronous caller
(`routers/leverage_sensitivity.py`) and `SimulationResults.jsx` keep working
unchanged; adds extra fields for the future job-based Strategy Lab (Plan 10
Phases 1+) to consume without another contract break.

`run_lab_simulation()` (Plan 10 Phase 1) is the job-based sibling: same
bootstrap core, but config-driven (mode/runs/blockLen/ruinThreshold/seed),
persists the full result to the `labResults` collection itself (engine is
sole writer of `results`/`status`, matching the `backtestResults` ownership
rule), and returns downsampled percentile equity bands for the future fan
chart. Called from `routers/simulate.py`, not `leverage_sensitivity.py`.

`compute_mc_stats()` (Plan 10 Phase 4a) is the Mongo-free extraction of
`run_lab_simulation`'s bootstrap core — takes a returns array directly
instead of reading trades from `db.backtestTrades`, so it can be called
synchronously per-candidate. Used by `walk_forward.py`'s MC-scored trial
selection (OOS-evaluating a fold's top-K candidates instead of only the
raw-loss winner, then ranking by MC-p5 outcome). `run_lab_simulation` is
now a thin DB-read/write wrapper around it — behavior unchanged.

Methodology fixes vs the prior implementation:
- Block bootstrap (circular, block length ~sqrt(N)) instead of i.i.d.
  resampling — i.i.d. shuffling destroys win/loss clustering and understates
  tail drawdown risk (QNT-7).
- `scale_out` legs excluded from the resampling pool (QNT-14) — they are
  partial exits of a round trip, not independent trades; resampling them as
  such double-counts and skews the trade-return distribution.
- Equity-path compounding is now consistently ADDITIVE: each trade's return
  is `pnl / capital` (a fraction of FIXED starting capital, not of current
  equity), so paths must sum, not multiplicatively compound, that fraction
  — the previous code computed an additive-style return but applied it
  multiplicatively (`equity *= (1 + r)`), silently mixing the two conventions.
- Vectorized via numpy: ~100x over the previous per-run Python loop, per
  Plan 10 §3.3 ("10k runs x 2k trades in well under 1s").
"""
import hashlib
from datetime import datetime, timezone
from typing import Any

import numpy as np

from config.mongo import get_database

DEFAULT_RUN_COUNT = 5_000
MAX_RUN_COUNT = 20_000  # Plan 10 §3.3 — tail metrics stabilize by 10k, more is waste
RUIN_THRESHOLD_PCT = 30.0  # preserved from the prior implementation's contract
DRAWDOWN_BUCKETS = (10.0, 20.0, 30.0, 40.0, 50.0)
EXCEEDANCE_BUCKETS = tuple(range(5, 55, 5))  # 5..50 step 5, finer than the legacy 5-bucket dist
EQUITY_BAND_MAX_POINTS = 500  # Plan 10 §3.2 / §5.7 — downsampled band storage cap

_DEFAULT_DIST = [
    {"drawdownPct": f"{k:.2f}", "probability": "0.000"} for k in DRAWDOWN_BUCKETS
]


def _block_bootstrap_indices(rng: np.random.Generator, n_runs: int, n_trades: int, block_len: int) -> np.ndarray:
    """Circular block bootstrap index matrix, shape (n_runs, n_trades).

    Each run is built from consecutive blocks of `block_len` trades starting
    at a random offset (wrapping around the trade sequence), preserving
    local win/loss clustering that pure i.i.d. resampling destroys.
    """
    n_blocks = -(-n_trades // block_len)  # ceil
    starts = rng.integers(0, n_trades, size=(n_runs, n_blocks))
    offsets = np.arange(block_len)
    # (n_runs, n_blocks, block_len) -> (n_runs, n_blocks * block_len), wrapped
    idx = (starts[:, :, None] + offsets[None, None, :]) % n_trades
    idx = idx.reshape(n_runs, n_blocks * block_len)
    return idx[:, :n_trades]


async def run_monte_carlo_simulation(job_id: str, n_runs: int = DEFAULT_RUN_COUNT) -> dict[str, Any]:
    db = get_database()

    # Equity-based return (pnl as a fraction of STARTING capital, not ROE) —
    # pnlPct in backtestTrades is leverage-amplified return-on-margin and
    # unsuitable for equity-path compounding.
    parent = await db.backtestResults.find_one({"jobId": job_id}, {"capital": 1})
    capital = float(parent.get("capital", 10000.0)) if parent else 10000.0

    cursor = db.backtestTrades.find({"jobId": job_id})
    trades = await cursor.to_list(length=100_000)

    if not trades:
        return {"ruinProbability": "0.000", "drawdownDistribution": _DEFAULT_DIST}

    # QNT-14: scale_out legs are partial exits of a round trip, not
    # independent trades — excluded from the resampling pool.
    round_trips = [t for t in trades if t.get("exitReason") != "scale_out"]

    returns = []
    for t in round_trips:
        try:
            returns.append(float(t.get("pnl", 0.0)) / capital)
        except (ValueError, TypeError):
            continue

    if not returns:
        return {"ruinProbability": "0.000", "drawdownDistribution": _DEFAULT_DIST}

    returns_arr = np.array(returns, dtype=np.float64)
    n_trades = len(returns_arr)

    seed = int(hashlib.md5(job_id.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)

    block_len = max(5, round(np.sqrt(n_trades)))
    idx = _block_bootstrap_indices(rng, n_runs, n_trades, block_len)
    resampled = returns_arr[idx]  # (n_runs, n_trades)

    # Additive compounding: each return is relative to FIXED starting capital.
    equity = 1.0 + np.cumsum(resampled, axis=1)
    peak = np.maximum.accumulate(np.maximum(equity, 1.0), axis=1)
    drawdown = (peak - equity) / peak
    max_dd_per_run = drawdown.max(axis=1)  # (n_runs,)

    ruin_prob = float(np.mean(max_dd_per_run >= (RUIN_THRESHOLD_PCT / 100.0)))
    dist = [
        {
            "drawdownPct": f"{threshold:.2f}",
            "probability": f"{float(np.mean(max_dd_per_run >= threshold / 100.0)):.3f}",
        }
        for threshold in DRAWDOWN_BUCKETS
    ]

    final_equity = equity[:, -1]
    percentiles = {
        p: float(np.percentile(final_equity, p)) for p in (5, 25, 50, 75, 95)
    }

    return {
        "ruinProbability": f"{ruin_prob:.3f}",
        "drawdownDistribution": dist,
        # Extra fields (Plan 10 Phase 1+ consumers) — additive, current UI
        # ignores unknown keys.
        "meta": {
            "nRuns": n_runs,
            "nTrades": n_trades,
            "blockLength": block_len,
            "method": "block_bootstrap",
            "scaleOutLegsExcluded": len(trades) - len(round_trips),
        },
        "finalEquityPercentiles": {str(p): v for p, v in percentiles.items()},
        "maxDrawdownPercentiles": {
            str(p): float(np.percentile(max_dd_per_run, p)) for p in (5, 25, 50, 75, 95)
        },
    }


def _iid_bootstrap_indices(rng: np.random.Generator, n_runs: int, n_trades: int) -> np.ndarray:
    """Classic i.i.d. resample-with-replacement — the labeled alternative to
    the default block bootstrap (Plan 10 §2.1 mode 2 / §3.3 "expose as a
    labeled alternative, not the default")."""
    return rng.integers(0, n_trades, size=(n_runs, n_trades))


def _downsample_indices(n_points: int, max_points: int) -> np.ndarray:
    if n_points <= max_points:
        return np.arange(n_points)
    return np.unique(np.linspace(0, n_points - 1, max_points).astype(int))


def _seed_from_key(key: str) -> int:
    return int(hashlib.md5(key.encode()).hexdigest()[:8], 16)


def returns_from_trades(trades: list[dict], capital: float) -> np.ndarray:
    """Additive per-trade return array from raw `backtestTrades` docs —
    `pnl / capital` (fixed starting capital), `scale_out` legs excluded
    (QNT-14). Shared by `run_lab_simulation` and `walk_forward.py`'s
    per-candidate MC scoring (Plan 10 Phase 4a) so the resampling-pool
    convention has exactly one implementation.
    """
    round_trips = [t for t in trades if t.get("exitReason") != "scale_out"]
    returns = []
    for t in round_trips:
        try:
            returns.append(float(t.get("pnl", 0.0)) / capital)
        except (ValueError, TypeError):
            continue
    return np.array(returns, dtype=np.float64)


def compute_mc_stats(
    returns: np.ndarray,
    mode: str,
    n_runs: int,
    block_len: int | None,
    ruin_threshold_pct: float,
    seed: int,
    include_equity_bands: bool = True,
) -> dict[str, Any]:
    """Pure bootstrap core — no DB access, no job/simId state.

    `returns` is an additive per-trade return array (`pnl / capital`, fixed
    starting capital, `scale_out` legs already excluded by the caller —
    QNT-14). `block_len=None` resolves to `max(5, round(sqrt(n_trades)))`,
    same default `run_lab_simulation` has always used. `include_equity_bands`
    defaults `True` to preserve `run_lab_simulation`'s exact existing output
    shape; callers scoring many candidates (e.g. `walk_forward.py`'s top-K
    MC ranking) should pass `False` to avoid persisting a full downsampled
    band series per candidate (BSON-bloat risk at topK x nFolds scale).
    """
    n_trades = len(returns)
    rng = np.random.default_rng(seed)

    resolved_block_len = int(block_len) if block_len else max(5, round(np.sqrt(n_trades)))

    if mode == "iid":
        idx = _iid_bootstrap_indices(rng, n_runs, n_trades)
    else:
        idx = _block_bootstrap_indices(rng, n_runs, n_trades, resolved_block_len)

    resampled = returns[idx]  # (n_runs, n_trades)

    equity = 1.0 + np.cumsum(resampled, axis=1)
    peak = np.maximum.accumulate(np.maximum(equity, 1.0), axis=1)
    drawdown = (peak - equity) / peak
    max_dd_per_run = drawdown.max(axis=1)

    ruin_prob = float(np.mean(max_dd_per_run >= (ruin_threshold_pct / 100.0)))
    exceedance = [
        {
            "drawdownPct": f"{threshold:.2f}",
            "probability": f"{float(np.mean(max_dd_per_run >= threshold / 100.0)):.3f}",
        }
        for threshold in EXCEEDANCE_BUCKETS
    ]

    final_equity = equity[:, -1]
    final_equity_pct = {str(p): float(np.percentile(final_equity, p)) for p in (5, 25, 50, 75, 95)}
    max_dd_pct = {str(p): float(np.percentile(max_dd_per_run, p)) for p in (5, 25, 50, 75, 95)}

    results: dict[str, Any] = {
        "ruinProbability": f"{ruin_prob:.3f}",
        "drawdownExceedance": exceedance,
        "finalEquityPercentiles": final_equity_pct,
        "maxDrawdownPercentiles": max_dd_pct,
        "meta": {
            "nRuns": n_runs,
            "nTrades": n_trades,
            "blockLength": resolved_block_len if mode == "block" else None,
            "mode": mode,
            "seed": seed,
        },
    }

    if include_equity_bands:
        band_idx = _downsample_indices(n_trades, EQUITY_BAND_MAX_POINTS)
        results["equityBands"] = {
            "tradeIndices": [int(i) for i in band_idx],
            **{
                f"p{p}": [float(v) for v in np.percentile(equity[:, band_idx], p, axis=0)]
                for p in (5, 25, 50, 75, 95)
            },
        }

    return results


async def run_lab_simulation(sim_id: str, source_job_id: str, config: dict, config_hash: str) -> dict[str, Any]:
    """Job-based Monte Carlo robustness run for the Strategy Lab (Plan 10 Phase 1).

    Persists the full result to `labResults` itself (engine is sole writer of
    `results`/`status`, mirroring `backtestResults`) — the router that calls
    this does not write on success, only on exception (same pattern as
    `routers/backtest.py`). Reproducibility: the seed defaults to a
    deterministic hash of `sourceJobId:configHash` (not `simId`) so any
    re-submission of an identical config against the same source backtest —
    regardless of what labId it lands under — reproduces the same draw
    sequence; an explicit `config.seed` always wins.
    """
    db = get_database()

    mode = config.get("mode") or "block"
    if mode not in ("block", "iid"):
        raise ValueError(f"invalid mode '{mode}' — must be 'block' or 'iid'")

    n_runs = int(config.get("runs") or DEFAULT_RUN_COUNT)
    n_runs = max(1, min(n_runs, MAX_RUN_COUNT))

    ruin_threshold_pct = float(config.get("ruinThresholdPct") or RUIN_THRESHOLD_PCT)

    seed = config.get("seed")
    seed = int(seed) if seed is not None else _seed_from_key(f"{source_job_id}:{config_hash}")

    parent = await db.backtestResults.find_one({"jobId": source_job_id}, {"capital": 1})
    capital = float(parent.get("capital", 10000.0)) if parent else 10000.0

    cursor = db.backtestTrades.find({"jobId": source_job_id})
    trades = await cursor.to_list(length=100_000)

    returns_arr = returns_from_trades(trades, capital)
    scale_out_count = sum(1 for t in trades if t.get("exitReason") == "scale_out")

    now = datetime.now(timezone.utc)

    if len(returns_arr) == 0:
        results = {
            "ruinProbability": "0.000",
            "drawdownExceedance": [
                {"drawdownPct": f"{k:.2f}", "probability": "0.000"} for k in EXCEEDANCE_BUCKETS
            ],
            "finalEquityPercentiles": {},
            "maxDrawdownPercentiles": {},
            "equityBands": {"tradeIndices": [], "p5": [], "p25": [], "p50": [], "p75": [], "p95": []},
            "meta": {"nRuns": n_runs, "nTrades": 0, "mode": mode, "seed": seed, "scaleOutLegsExcluded": len(trades)},
        }
        await db.labResults.update_one(
            {"labId": sim_id},
            {"$set": {"status": "completed", "results": results, "completedAt": now, "updatedAt": now}},
            upsert=True,
        )
        return results

    block_len_cfg = config.get("blockLen")
    block_len = int(block_len_cfg) if block_len_cfg else None

    results = compute_mc_stats(
        returns_arr,
        mode=mode,
        n_runs=n_runs,
        block_len=block_len,
        ruin_threshold_pct=ruin_threshold_pct,
        seed=seed,
        include_equity_bands=True,
    )
    results["meta"]["scaleOutLegsExcluded"] = scale_out_count

    await db.labResults.update_one(
        {"labId": sim_id},
        {"$set": {"status": "completed", "results": results, "completedAt": now, "updatedAt": now}},
        upsert=True,
    )

    return results
