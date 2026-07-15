"""Monte Carlo robustness simulation (Plan 10 §3.3 methodology, QNT-7/QNT-14).

Vectorized block-bootstrap replacing the previous O(n_runs * n_trades) pure-
Python i.i.d. loop. Preserves the existing response contract (`ruinProbability`,
`drawdownDistribution`) so the current synchronous caller
(`routers/leverage_sensitivity.py`) and `SimulationResults.jsx` keep working
unchanged; adds extra fields for the future job-based Strategy Lab (Plan 10
Phases 1+) to consume without another contract break.

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
from typing import Any

import numpy as np

from config.mongo import get_database

DEFAULT_RUN_COUNT = 5_000
RUIN_THRESHOLD_PCT = 30.0  # preserved from the prior implementation's contract
DRAWDOWN_BUCKETS = (10.0, 20.0, 30.0, 40.0, 50.0)

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
