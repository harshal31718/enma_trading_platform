"""Probability of Backtest Overfitting (PBO) via Combinatorially Symmetric
Cross-Validation (CSCV) — Bailey, Borwein, Lopez de Prado & Zhu (2015).

Plan 10's own scoping notes (`workspace/plan/10_monte-carlo-strategy-lab.md`) flagged two open
architectural questions before any code could be written here; both are resolved by this module's
design, not guessed at:

1. **Subsample source** — PBO does NOT reuse `walk_forward.py`'s rolling/anchored fold boundaries.
   Those exist for a different purpose (sequential re-optimization across time) and would tie PBO's
   statistical properties to an unrelated UI choice (`nFolds`). Instead, `run_lab_pbo` calls
   `optimizer.run_optimization`/`run_bayesian_optimization` DIRECTLY over the full requested date
   range (no fold splitting at all) to get N candidates, each backtested over the WHOLE range once,
   then partitions that single shared date range into `n_blocks` (S, must be even) contiguous,
   equal-candle-count blocks — PBO's own independent scheme, exactly as CSCV requires.

2. **Per-trial trade-level data** — confirmed by reading `optimizer.py`: every combo `run_optimization`/
   `run_bayesian_optimization` scores already gets its own full backtest, and `run_backtest_simulation`
   already bulk-persists that combo's trades to `backtestTrades` under `{job_id}_c{idx:04d}` (grid) /
   `{job_id}_t{idx:04d}` (bayesian) — no new persistence path was needed. The one real gap: the
   returned trial dict didn't carry that job_id (lost once `_finalize_optimization` re-sorts by loss),
   so a caller couldn't reconstruct which trades belonged to which trial after the fact. Fixed at the
   source (this session): both search functions now include `"jobId": combo_job_id` in every scored
   trial dict — a small, additive, backward-compatible field.

**Why this avoids the "3,500 extra backtests" cost the scoping notes flagged for the naive
approach**: only the initial N candidates are ever backtested (identical cost to a plain, non-walk-
forward optimization run). Every one of CSCV's `C(S, S/2)` combinatorial train/test splits is scored
by slicing each candidate's ALREADY-fetched trade list by block membership and recomputing a
trade-level statistic in memory (numpy) — zero additional `run_backtest_simulation` calls.

**Scoring statistic**: the same trade-level Sharpe-like proxy (`mean(pnl/capital) / std(pnl/capital)`)
already established for Deflated Sharpe Ratio (Phase 3e) and the walk-forward stitched-OOS aggregate
— deliberately NOT each candidate's own annualized Sharpe from its full-range metrics, which can't be
recomputed from an arbitrary trade subset without re-running a backtest. Documented, consistent
choice, not an assumption.

**Honesty guards, same stance as DSR/Phase 4a**: a block-combination where the in-sample-selected
candidate has too few OOS trades to compute a stable statistic doesn't get a fabricated logit value —
it's excluded and counted (`nSkipped`). If every combination is skipped, `pbo` is `None` with
`insufficientData: true` rather than a confident-looking fake number.
"""
import itertools
import math
from datetime import datetime, timezone
from typing import Any

import numpy as np

from config.mongo import get_database
from config.timescale import get_pool
from services.optimizer import (
    OBJECTIVE_REGISTRY,
    OptimizerConfig,
    run_optimization,
    run_bayesian_optimization,
)
from services.monte_carlo import returns_from_trades

MIN_CANDIDATES = 2  # CSCV is meaningless with fewer than 2 candidates to rank
DEFAULT_N_BLOCKS = 8  # C(8,4)=70 combinations — the paper's own common choice
MAX_N_BLOCKS = 12  # C(12,6)=924 — pure in-memory numpy math, no I/O; kept conservative
                    # rather than the paper's occasional S=16 (C(16,8)=12,870) since nothing
                    # in this codebase has needed a larger S yet and a smaller cap is easier
                    # to reason about — raise later if a real use case needs it.
MIN_TRADES_PER_SIDE = 2  # a train or test side with fewer trades than this can't produce a
                          # meaningful mean/std ratio for a candidate


async def _fetch_candle_times(exchange: str, symbol: str, timeframe: str, start_date: str, end_date: str) -> list:
    """Ordered candle timestamps for the range — same query `walk_forward.py`'s own
    `_fetch_candle_times` runs; duplicated here (not imported) to keep this module's import graph
    independent of `walk_forward.py`, since PBO is deliberately NOT a walk-forward feature."""
    start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT time FROM candles
            WHERE exchange = $1 AND symbol = $2 AND timeframe = $3
            AND time >= $4 AND time < $5
            ORDER BY time ASC
            """,
            exchange, symbol, timeframe, start_dt, end_dt,
        )
    return [r["time"] for r in rows]


def _block_boundaries(times: list, n_blocks: int) -> list[tuple]:
    """Split ordered candle timestamps into `n_blocks` contiguous, roughly equal-sized closed
    intervals `[start, end]` (inclusive both ends — trade assignment below uses `entryAt` against
    these directly, unlike `walk_forward._split_folds`'s exclusive-upper-bound fold convention,
    since here every candle must belong to exactly one block with no gap)."""
    n = len(times)
    block_size = n // n_blocks
    boundaries = []
    for i in range(n_blocks):
        start_idx = i * block_size
        end_idx = (i + 1) * block_size if i < n_blocks - 1 else n
        boundaries.append((times[start_idx], times[end_idx - 1]))
    return boundaries


def _assign_block(entry_at, boundaries: list[tuple]) -> int | None:
    """`entry_at` is `backtestTrades.entryAt`, persisted as an ISO string
    (`backtest_runner.py`'s `time_t.isoformat()`) — parsed back to a
    tz-aware datetime here to compare against `boundaries` (tz-aware
    datetimes straight from TimescaleDB, the same source `time_t` itself
    came from before being stringified)."""
    try:
        entry_dt = datetime.fromisoformat(entry_at)
    except (TypeError, ValueError):
        return None
    for i, (start, end) in enumerate(boundaries):
        if start <= entry_dt <= end:
            return i
    return None


def _stat_from_returns(returns: np.ndarray) -> float | None:
    """Trade-level Sharpe-like proxy — see module docstring for why this statistic, not the
    full-run annualized Sharpe. `None` (not 0.0) when there isn't enough data to trust the ratio —
    a real zero score and 'can't compute a score' must never be conflated."""
    if len(returns) < MIN_TRADES_PER_SIDE:
        return None
    std = float(np.std(returns))
    if std <= 0:
        return None
    return float(np.mean(returns)) / std


def compute_pbo(candidate_block_returns: list[list[np.ndarray]]) -> dict[str, Any]:
    """Pure CSCV combinatorics — no DB access, no job state.

    `candidate_block_returns[c][b]` is candidate `c`'s additive returns array for block `b`
    (empty array if that candidate had no trades in that block). `n_blocks = len(candidate_block_returns[0])`
    for every candidate (callers must pass equal-length block lists).
    """
    n_candidates = len(candidate_block_returns)
    n_blocks = len(candidate_block_returns[0]) if candidate_block_returns else 0
    half = n_blocks // 2
    all_blocks = list(range(n_blocks))
    total_combinations = math.comb(n_blocks, half)

    logits: list[float] = []
    skipped = 0

    for train_blocks in itertools.combinations(all_blocks, half):
        train_set = set(train_blocks)
        test_blocks = [b for b in all_blocks if b not in train_set]

        is_stats: list[float | None] = []
        oos_stats: list[float | None] = []
        for c in range(n_candidates):
            train_returns = np.concatenate([candidate_block_returns[c][b] for b in train_blocks]) \
                if train_blocks else np.array([], dtype=np.float64)
            test_returns = np.concatenate([candidate_block_returns[c][b] for b in test_blocks]) \
                if test_blocks else np.array([], dtype=np.float64)
            is_stats.append(_stat_from_returns(train_returns))
            oos_stats.append(_stat_from_returns(test_returns))

        valid_is = [(c, v) for c, v in enumerate(is_stats) if v is not None]
        if not valid_is:
            skipped += 1
            continue

        n_star = max(valid_is, key=lambda t: t[1])[0]

        # OOS rank among ALL candidates — ASCENDING order (rank 1 = worst performer, rank N =
        # best), matching the CSCV paper's own convention exactly. This direction matters: the
        # relative rank omega = rank/(N+1) feeds `logit = ln(omega / (1-omega))`, and PBO is
        # defined as P(logit <= 0) — that only means "the IS-selected candidate performed at/
        # below the OOS median" (the actual overfitting signal) if rank 1 is the WORST performer.
        # Getting this backwards would silently invert the whole statistic (a candidate that
        # performs BEST out-of-sample would count as "overfit"). A candidate with no computable
        # OOS statistic ranks worst (sorts to the front, tied among any other None-valued
        # candidates) rather than being excluded — "no OOS signal" is itself informative for
        # ranking purposes, not a reason to pretend the candidate doesn't exist.
        ranked_ascending = sorted(
            range(n_candidates),
            key=lambda c: (oos_stats[c] is not None, oos_stats[c] if oos_stats[c] is not None else 0.0),
        )
        rank_of_n_star = ranked_ascending.index(n_star) + 1
        omega = rank_of_n_star / (n_candidates + 1)
        if not (0.0 < omega < 1.0):
            skipped += 1
            continue
        logits.append(math.log(omega / (1.0 - omega)))

    if not logits:
        return {
            "pbo": None,
            "nBlocks": n_blocks,
            "nCombinations": total_combinations,
            "nEvaluated": 0,
            "nSkipped": skipped,
            "insufficientData": True,
            "logitDistribution": [],
        }

    pbo = sum(1 for l in logits if l <= 0) / len(logits)
    return {
        "pbo": pbo,
        "nBlocks": n_blocks,
        "nCombinations": total_combinations,
        "nEvaluated": len(logits),
        "nSkipped": skipped,
        "insufficientData": False,
        "logitDistribution": logits,
    }


async def run_lab_pbo(lab_id: str, config: dict, config_hash: str) -> dict[str, Any]:
    """Job-based PBO run for the Strategy Lab (Plan 10, the final unshipped item). Persists the
    full result to `labResults` itself (engine sole-writer of `results`/`status`, same ownership
    rule as `monte_carlo.run_lab_simulation`/`walk_forward.run_lab_walk_forward`). Called from
    `routers/simulate.py`'s `POST /simulate/pbo`.
    """
    db = get_database()
    now = datetime.now(timezone.utc)

    objective = config.get("objective") or "sharpe"
    if objective not in OBJECTIVE_REGISTRY:
        raise ValueError(f"Unknown objective '{objective}'. Available: {list(OBJECTIVE_REGISTRY.keys())}")

    param_grid = config.get("paramGrid")
    if not param_grid:
        raise ValueError("paramGrid must not be empty")

    method = config.get("method") or "grid"
    if method not in ("grid", "bayesian"):
        raise ValueError(f"method must be 'grid' or 'bayesian', got '{method}'")

    n_blocks = int(config.get("nBlocks") or DEFAULT_N_BLOCKS)
    if n_blocks < 4 or n_blocks % 2 != 0:
        raise ValueError("nBlocks must be an even number >= 4")
    n_blocks = min(n_blocks, MAX_N_BLOCKS)

    exchange = config["exchange"]
    symbol = config["symbol"]
    timeframe = config["timeframe"]
    capital = float(config["capital"])
    leverage = int(config.get("leverage") or 10)
    fee_rate = float(config.get("feeRate") or 0.0005)
    risk_leverage_grid = config.get("riskLeverageGrid")
    max_combinations = int(config.get("maxCombinations") or 0)
    min_trades = int(config.get("minTrades") or 0)

    opt_config = OptimizerConfig(
        strategy_file=config["strategyFile"],
        exchange=exchange,
        symbol=symbol,
        timeframe=timeframe,
        start_date=config["startDate"],
        end_date=config["endDate"],
        capital=capital,
        leverage=leverage,
        fee_rate=fee_rate,
        slippage_pct=config.get("slippagePct"),
        funding_enabled=bool(config.get("fundingEnabled", False)),
        funding_rate=config.get("fundingRate"),
        risk_params=config.get("riskParams"),
        objective=objective,
        max_combinations=max_combinations,
        min_trades=min_trades,
    )

    job_id = f"pbo_{lab_id}"
    if method == "bayesian":
        n_trials = int(config.get("nTrials") or 50)
        seed = int(config.get("seed") or 42)
        opt_result = await run_bayesian_optimization(
            config=opt_config, param_grid=param_grid, n_trials=n_trials,
            job_id=job_id, seed=seed, risk_leverage_grid=risk_leverage_grid,
        )
    else:
        opt_result = await run_optimization(
            config=opt_config, param_grid=param_grid, job_id=job_id,
            risk_leverage_grid=risk_leverage_grid,
        )

    trials = opt_result.get("results", [])
    # `_finalize_optimization` already sanitizes non-finite loss to `None` (Phase 3d/3b's own
    # JSON-safety fix) — an errored/ineligible combo is excluded here the same way
    # `walk_forward._eligible_trials` excludes them, and for the same reason (no business being
    # ranked as a PBO candidate).
    eligible = [t for t in trials if t.get("loss") is not None]

    if len(eligible) < MIN_CANDIDATES:
        raise ValueError(
            f"PBO needs at least {MIN_CANDIDATES} eligible candidates (finite loss), got {len(eligible)}"
        )

    times = await _fetch_candle_times(exchange, symbol, timeframe, config["startDate"], config["endDate"])
    if len(times) < n_blocks * MIN_TRADES_PER_SIDE:
        raise ValueError(
            f"Date range has too few candles ({len(times)}) for {n_blocks} blocks"
        )
    boundaries = _block_boundaries(times, n_blocks)

    candidate_block_returns: list[list[np.ndarray]] = []
    candidate_meta: list[dict] = []
    for trial in eligible:
        combo_job_id = trial.get("jobId")
        trades: list[dict] = []
        if combo_job_id:
            cursor = db.backtestTrades.find({"jobId": combo_job_id})
            trades = await cursor.to_list(length=100_000)

        block_trades: list[list[dict]] = [[] for _ in range(n_blocks)]
        unassigned = 0
        for t in trades:
            entry_at = t.get("entryAt")
            if entry_at is None:
                unassigned += 1
                continue
            b = _assign_block(entry_at, boundaries)
            if b is None:
                unassigned += 1
                continue
            block_trades[b].append(t)

        block_returns = [returns_from_trades(bt, capital) for bt in block_trades]
        candidate_block_returns.append(block_returns)
        candidate_meta.append({
            "rank": trial.get("rank"),
            "params": trial.get("params"),
            "riskLeverage": trial.get("riskLeverage"),
            "metrics": trial.get("metrics", {}),
            "totalTrades": len(trades),
            "unassignedTrades": unassigned,
        })

    cscv = compute_pbo(candidate_block_returns)

    results = {
        "method": method,
        "objective": objective,
        "nCandidates": len(eligible),
        "candidates": candidate_meta,
        "pbo": cscv["pbo"],
        "nBlocks": cscv["nBlocks"],
        "nCombinations": cscv["nCombinations"],
        "nEvaluated": cscv["nEvaluated"],
        "nSkipped": cscv["nSkipped"],
        "insufficientData": cscv["insufficientData"],
        "logitDistribution": cscv["logitDistribution"],
        "meta": {
            "paramGrid": param_grid,
            "riskLeverageGrid": risk_leverage_grid,
            "maxCombinations": max_combinations,
            "strategyFile": config["strategyFile"],
            "symbol": symbol,
            "timeframe": timeframe,
        },
    }

    await db.labResults.update_one(
        {"labId": lab_id},
        {"$set": {"status": "completed", "results": results, "completedAt": now, "updatedAt": now}},
        upsert=True,
    )

    return results
