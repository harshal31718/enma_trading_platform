"""Walk-forward analysis (Plan 10 Phase 3a — job-based, absorbing Plan 18's design).

Pure orchestration layer over two already-shipped, already-tested primitives:
`services.optimizer.run_optimization` (train) and
`services.backtest_runner.run_backtest_simulation` (test) — no new simulation
math, per Plan 18's own framing ("no new sim math"). Splits a date range into
sequential, non-overlapping folds by CANDLE COUNT (not calendar days, so
folds are balanced regardless of gaps/weekends), optimizes on each fold's
train window, evaluates the winning params out-of-sample on that fold's test
window, and reports the in-sample-vs-out-of-sample degradation ratio per fold
— the headline "is this overfit" signal.

Persists to `labResults` (type='optimization'), engine sole-writer of
`results`/`status`, mirroring `monte_carlo.run_lab_simulation`'s ownership
rule exactly. Called from `routers/simulate.py`'s `POST /simulate/optimize`.

Scope decisions (Phase 3a, documented — not silently dropped):
- Grid search only (`services.optimizer`'s existing `_build_param_grid`).
  Optuna/TPE (Plan 19's design) is Phase 3b — the search loop is swappable
  without touching this file's fold/stitch logic (Plan 19 itself notes S8
  "swaps only the search loop").
- Phase 3e: Deflated Sharpe Ratio IS now computed per fold (`services.stats.
  deflated_sharpe_ratio`, numerically verified against published reference
  quantiles + a round-trip CDF/inverse-CDF check — see `tests/test_stats.py`
  — now that this session has real pytest access, unlike the four prior
  sessions that deferred this exact item for lack of it). Trade-level (not
  the paper's per-period formulation): SR-like statistic per trial is
  `sqn / sqrt(totalTrades)` (SQN is already a trade-level Sharpe-like
  statistic, `sqn = sqrt(N)*mean(pnl)/std(pnl)`, so dividing out `sqrt(N)`
  recovers `mean(pnl)/std(pnl)` with no new per-trial metric needed), skew/
  kurtosis are the winning combo's own trade-PnL skew/kurtosis
  (`metrics.SkewnessStat`/`KurtosisStat`, new this session, golden-master
  verified additive-only). Attached as `fold.dsr` (0.5 + `insufficientData:
  true` when there isn't enough data to say anything, never a fabricated
  confident number).
- **PBO (Probability of Backtest Overfitting) is still NOT computed.**
  Canonical PBO (CSCV — Bailey, Borwein, López de Prado & Zhu 2015) needs
  EVERY trial's out-of-sample performance across multiple train/test
  subsample combinations, not just the fold winner's. This architecture
  deliberately only OOS-evaluates each fold's winning combo (Phase 3d's own
  documented reason: "no per-trial OOS value exists to plot honestly") —
  computing real PBO would mean OOS-evaluating every trial in every fold,
  multiplying the walk-forward job's backtest count by the grid/trial size.
  That is real, separate, not-small scope, not attempted this session.
  Faking PBO from data that doesn't support it (e.g. from the per-fold
  degradation ratio alone) would misrepresent what the number means —
  deferred rather than guessed at, same stance Phase 3a took on DSR itself.
- Phase 3b: the per-fold train step now accepts `method: "grid" | "bayesian"`
  (default `"grid"`, back-compat) — dispatches to
  `optimizer.run_bayesian_optimization` (TPE search, `nTrials` trials per
  fold) instead of `optimizer.run_optimization` (grid). Per Plan 19's own
  sequencing note ("make S8 selectable as the fold optimizer") — no other
  fold/stitch logic changes; both optimizer functions return the identical
  ranked-results shape.
- Phase 3d: each fold's `trials` key carries every combo `run_optimization`
  scored on that fold's train window (params/loss/rank/metrics — the same
  list it already builds and persists to `optimizationResults`, just no
  longer discarded down to `best` alone). This is what unblocks a real
  trials table / IS-vs-OOS scatter / param heatmap in the UI, and is the
  raw material DSR/PBO would eventually resample over — those statistics
  themselves are still deferred per the point above.
- The stitched OOS aggregate is a TRADE-LEVEL approximation (mirrors
  `monte_carlo.py`'s own pnl/capital-additive convention, scale_out legs
  excluded per QNT-14), not the candle-level Sharpe `run_backtest_simulation`
  computes per-fold — folds have calendar gaps (their train windows), so a
  true candle-level stitched equity curve isn't well-defined the way a
  single contiguous backtest's is. Each fold's own `oosMetrics` still carries
  the real candle-level Sharpe/Sortino/etc. for that fold standalone.
"""
import logging
import math
from datetime import datetime, timezone
from typing import Any

import numpy as np

from config.mongo import get_database
from config.timescale import get_pool
from services.optimizer import (
    OBJECTIVE_REGISTRY,
    OptimizerConfig,
    _safe_float_metric,
    run_optimization,
    run_bayesian_optimization,
)
from services.backtest_runner import run_backtest_simulation
from services.stats import deflated_sharpe_ratio
from utils.timeframes import to_timedelta

logger = logging.getLogger(__name__)

MIN_FOLD_CANDLES = 20  # reject folds whose train or test slice would be too small to trust
DEFAULT_N_FOLDS = 4
DEFAULT_TRAIN_RATIO = 0.7


async def _fetch_candle_times(exchange: str, symbol: str, timeframe: str, start_date: str, end_date: str) -> list:
    """Ordered candle timestamps for the range — the index space fold
    boundaries are computed over (Plan 18: "by candle count, not calendar
    days, so folds are balanced")."""
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


def _split_folds(times: list, n_folds: int, train_ratio: float, mode: str, timeframe: str = "1h") -> list[dict]:
    """Non-overlapping fold split. Returns a list of dicts with ISO
    trainStart/trainEnd/testStart/testEnd — `*End` values are the FIRST
    timestamp of the following slice (exclusive upper bound), matching this
    codebase's `time < end` candle-query convention throughout
    (`backtest_runner.py`, `candle_manager.py`) so a fold's train/test windows
    never double-count a boundary candle.

    Conservation property (verified in `test_walk_forward.py`): fold BLOCKS
    are contiguous (no gap between one fold's window and the next), and
    within each fold `[trainStart, trainEnd) + [testStart, testEnd)` exactly
    partitions that fold's block with no overlap. Test windows across
    different folds never overlap and are chronologically ordered, but are
    NOT themselves contiguous — the gap between fold i's test window and
    fold i+1's is fold i+1's own train slice (a candle is either training
    data or OOS test data for its own fold, never both).
    """
    n = len(times)
    if n_folds < 1 or n < 2:
        return []

    fold_size = n // n_folds
    if fold_size < MIN_FOLD_CANDLES:
        return []  # range too short for this many folds — caller surfaces this as "no folds"

    tf_delta = to_timedelta(timeframe)
    folds = []
    for i in range(n_folds):
        fold_start_idx = i * fold_size
        fold_end_idx = (i + 1) * fold_size if i < n_folds - 1 else n
        fold_times = times[fold_start_idx:fold_end_idx]
        if len(fold_times) < 2:
            continue

        split_idx = max(1, int(round(len(fold_times) * train_ratio)))
        split_idx = min(split_idx, len(fold_times) - 1)  # always leave >=1 test candle

        test_slice = fold_times[split_idx:]
        if len(test_slice) < 2:
            continue

        if mode == "anchored":
            # Expanding train: everything from the very first candle in the
            # whole range up to this fold's test start.
            train_slice = times[0:fold_start_idx + split_idx]
        else:
            # Rolling: fixed-width train, confined to this fold's own window.
            train_slice = fold_times[:split_idx]

        if len(train_slice) < MIN_FOLD_CANDLES:
            continue

        # testEnd: the next fold's test start if there is one (exclusive
        # boundary, matching `time < end`); for the last fold, one bar past
        # the last actual test candle so that candle isn't excluded by the
        # same exclusive-upper-bound convention.
        if i < n_folds - 1 and fold_end_idx < n:
            test_end = times[fold_end_idx]
        else:
            test_end = test_slice[-1] + tf_delta

        folds.append({
            "trainStart": train_slice[0].isoformat(),
            "trainEnd": test_slice[0].isoformat(),  # exclusive — first test candle
            "testStart": test_slice[0].isoformat(),
            "testEnd": test_end.isoformat(),
        })

    return folds


def _json_safe_trials(trials: list[dict]) -> list[dict]:
    """`optimizer.run_optimization`'s `results` list is designed for internal
    ranking, not JSON transport — an errored/ineligible combo carries
    `loss=float("inf")` (optimizer.py's own error path), and Python's `json`
    module rejects inf/-inf/nan outright (`ValueError: Out of range float
    values are not JSON compliant`). Only `best` (already filtered to a
    finite loss) reached the router before Phase 3d; persisting every trial
    means every trial's loss now needs to survive serialization."""
    safe = []
    for t in trials:
        loss = t.get("loss")
        if loss is not None and not math.isfinite(loss):
            t = {**t, "loss": None}
        safe.append(t)
    return safe


def _safe_float(metrics: dict, key: str) -> float | None:
    if not metrics:
        return None
    try:
        return _safe_float_metric(metrics, key, default=float("nan"))
    except Exception:
        return None


def _trade_level_sharpe(metrics: dict) -> float | None:
    """`sqn / sqrt(totalTrades)` recovers `mean(pnl)/std(pnl)` (SQN is
    `sqrt(N)*mean(pnl)/std(pnl)`) — a trade-level, un-annualized Sharpe-like
    statistic, with no new per-trial metric needed (see this module's own
    header comment on why trade-level, not period-level, is the deliberate
    choice for Phase 3e's DSR)."""
    n = _safe_float(metrics, "totalTrades")
    sqn = _safe_float(metrics, "sqn")
    if n is None or sqn is None or math.isnan(n) or math.isnan(sqn) or n < 2:
        return None
    return sqn / math.sqrt(n)


def _compute_fold_dsr(trial_results: list[dict], best_metrics: dict) -> dict:
    """Deflated Sharpe Ratio for this fold's winning combo, deflated against
    the pool of every trial `run_optimization`/`run_bayesian_optimization`
    scored on this fold's train window. See this module's header comment and
    `services/stats.py` for the formula + numerical verification."""
    sr_trials = []
    for t in trial_results:
        m = t.get("metrics")
        if not m:
            continue
        sr = _trade_level_sharpe(m)
        if sr is not None:
            sr_trials.append(sr)

    sr_selected = _trade_level_sharpe(best_metrics)
    n_obs = _safe_float(best_metrics, "totalTrades")
    skew = _safe_float(best_metrics, "skewness")
    kurtosis = _safe_float(best_metrics, "kurtosis")

    if sr_selected is None or n_obs is None or math.isnan(n_obs):
        return {"dsr": 0.5, "expectedMaxSharpe": None, "nTrials": len(sr_trials), "insufficientData": True}

    skew = 0.0 if skew is None or math.isnan(skew) else skew
    kurtosis = 3.0 if kurtosis is None or math.isnan(kurtosis) else kurtosis

    return deflated_sharpe_ratio(
        sr_trials=sr_trials, sr_selected=sr_selected,
        n_observations=int(n_obs), skew=skew, kurtosis=kurtosis,
    )


def _aggregate_stitched_oos(trades: list[dict], capital: float) -> dict[str, Any]:
    """Trade-level aggregate over all folds' OOS trades, concatenated in
    fold order. Additive pnl/capital convention (QNT-7/QNT-14, matches
    `monte_carlo.py`) — NOT the candle-level Sharpe a single contiguous
    backtest reports; see this module's own docstring for why."""
    round_trips = [t for t in trades if t.get("exitReason") != "scale_out"]
    if not round_trips:
        return {"totalTrades": 0, "netProfitPct": "0.00", "winRate": "0.00", "tradeSharpeApprox": "0.00"}

    returns = []
    wins = 0
    for t in round_trips:
        try:
            pnl = float(t.get("pnl", 0.0))
        except (ValueError, TypeError):
            continue
        returns.append(pnl / capital)
        if pnl > 0:
            wins += 1

    if not returns:
        return {"totalTrades": 0, "netProfitPct": "0.00", "winRate": "0.00", "tradeSharpeApprox": "0.00"}

    arr = np.array(returns, dtype=np.float64)
    std = float(np.std(arr))
    # Trade-level (not annualized-candle) Sharpe approximation — deliberately
    # labeled, see module docstring.
    trade_sharpe = (float(np.mean(arr)) / std) if std > 0 else 0.0

    return {
        "totalTrades": len(round_trips),
        "netProfitPct": f"{float(np.sum(arr)) * 100:.2f}",
        "winRate": f"{(wins / len(round_trips)):.2f}",
        "tradeSharpeApprox": f"{trade_sharpe:.2f}",
    }


async def run_lab_walk_forward(lab_id: str, config: dict, config_hash: str) -> dict[str, Any]:
    """Job-based walk-forward run for the Strategy Lab optimizer tab (Plan 10
    Phase 3a). Persists the full result to `labResults` itself — the router
    calling this does not write on success, only on exception (same
    asymmetry as `monte_carlo.run_lab_simulation` / `backtest.py`)."""
    db = get_database()
    now = datetime.now(timezone.utc)

    objective = config.get("objective") or "sharpe"
    if objective not in OBJECTIVE_REGISTRY:
        raise ValueError(f"Unknown objective '{objective}'. Available: {list(OBJECTIVE_REGISTRY.keys())}")

    param_grid = config.get("paramGrid")
    if not param_grid:
        raise ValueError("paramGrid must not be empty")

    mode = config.get("mode") or "rolling"
    if mode not in ("rolling", "anchored"):
        raise ValueError(f"mode must be 'rolling' or 'anchored', got '{mode}'")

    method = config.get("method") or "grid"
    if method not in ("grid", "bayesian"):
        raise ValueError(f"method must be 'grid' or 'bayesian', got '{method}'")
    n_trials = int(config.get("nTrials") or 50)  # bayesian only
    base_seed = int(config.get("seed") or 42)  # bayesian only — TPE sampler seed, per fold below

    n_folds = int(config.get("nFolds") or DEFAULT_N_FOLDS)
    train_ratio = float(config.get("trainRatio") or DEFAULT_TRAIN_RATIO)
    min_trades = int(config.get("minTrades") or 0)
    max_combinations = int(config.get("maxCombinations") or 0)

    exchange = config["exchange"]
    symbol = config["symbol"]
    timeframe = config["timeframe"]
    capital = float(config["capital"])
    leverage = int(config.get("leverage") or 10)
    fee_rate = float(config.get("feeRate") or 0.0005)

    times = await _fetch_candle_times(exchange, symbol, timeframe, config["startDate"], config["endDate"])
    folds = _split_folds(times, n_folds, train_ratio, mode, timeframe=timeframe)

    if not folds:
        raise ValueError(
            f"Date range too short for {n_folds} folds at train_ratio={train_ratio} "
            f"(need >= {MIN_FOLD_CANDLES} candles per train/test slice per fold)"
        )

    fold_results = []
    test_job_ids = []

    for i, fold in enumerate(folds):
        train_config = OptimizerConfig(
            strategy_file=config["strategyFile"],
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            start_date=fold["trainStart"],
            end_date=fold["trainEnd"],
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

        fold_job_id = f"wf_{lab_id}_fold{i}_train"
        if method == "bayesian":
            train_result = await run_bayesian_optimization(
                config=train_config,
                param_grid=param_grid,
                n_trials=n_trials,
                job_id=fold_job_id,
                seed=base_seed + i,  # distinct-but-deterministic per fold, same stance as monte_carlo.py
            )
        else:
            train_result = await run_optimization(
                config=train_config,
                param_grid=param_grid,
                job_id=fold_job_id,
            )
        best = train_result.get("best")

        best_loss = best.get("loss") if best else None
        # `optimizer.py`'s shared tail now sanitizes a non-finite loss to
        # `None` (JSON-safety pass, same fix class as this file's own
        # `_json_safe_trials`) — `None` must short-circuit before
        # `math.isfinite`, which raises TypeError on a non-float.
        if not best or best_loss is None or not math.isfinite(best_loss):
            fold_results.append({
                "fold": i,
                "trainRange": [fold["trainStart"], fold["trainEnd"]],
                "testRange": [fold["testStart"], fold["testEnd"]],
                "skipped": True,
                "reason": "no eligible parameter combination on the train window",
                "trials": _json_safe_trials(train_result.get("results", [])),
                "dsr": {"dsr": 0.5, "expectedMaxSharpe": None, "nTrials": 0, "insufficientData": True},
            })
            continue

        best_params = best["params"]
        is_metrics = best.get("metrics", {})
        trials = _json_safe_trials(train_result.get("results", []))
        dsr = _compute_fold_dsr(train_result.get("results", []), is_metrics)

        test_job_id = f"wf_{lab_id}_fold{i}_test"
        test_result = await run_backtest_simulation(
            job_id=test_job_id,
            strategy_file=config["strategyFile"],
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            start_date=fold["testStart"],
            end_date=fold["testEnd"],
            capital=capital,
            leverage=leverage,
            fee_rate=fee_rate,
            slippage_pct=config.get("slippagePct"),
            funding_enabled=bool(config.get("fundingEnabled", False)),
            funding_rate=config.get("fundingRate"),
            alpha_params=best_params,
            risk_params=config.get("riskParams"),
        )
        oos_metrics = test_result.get("metrics", {})
        test_job_ids.append(test_job_id)

        is_sharpe = _safe_float(is_metrics, "sharpeRatio")
        oos_sharpe = _safe_float(oos_metrics, "sharpeRatio")
        degradation = None
        if (
            is_sharpe is not None and oos_sharpe is not None
            and not math.isnan(is_sharpe) and not math.isnan(oos_sharpe)
            and is_sharpe != 0.0
        ):
            degradation = oos_sharpe / is_sharpe

        fold_results.append({
            "fold": i,
            "trainRange": [fold["trainStart"], fold["trainEnd"]],
            "testRange": [fold["testStart"], fold["testEnd"]],
            "bestParams": best_params,
            "isMetrics": is_metrics,
            "oosMetrics": oos_metrics,
            "oosTradeCount": test_result.get("tradeCount", 0),
            "degradationRatio": degradation,
            "trials": trials,
            "dsr": dsr,
        })

    # Stitched OOS aggregate — read back the persisted trades for each fold's
    # test job (backtestTrades is jobId-scoped, same read pattern
    # monte_carlo.py already uses for its own source backtest).
    all_oos_trades = []
    for job_id in test_job_ids:
        cursor = db.backtestTrades.find({"jobId": job_id})
        all_oos_trades.extend(await cursor.to_list(length=100_000))

    stitched = _aggregate_stitched_oos(all_oos_trades, capital)

    valid_degradations = [
        f["degradationRatio"] for f in fold_results
        if not f.get("skipped") and f.get("degradationRatio") is not None
    ]
    avg_degradation = float(np.mean(valid_degradations)) if valid_degradations else None

    min_trades_warning = None
    if min_trades > 0 and stitched["totalTrades"] < min_trades:
        min_trades_warning = (
            f"Stitched OOS trade count ({stitched['totalTrades']}) is below the "
            f"min-trades filter ({min_trades}) — treat the aggregate as low-confidence."
        )

    results = {
        "mode": mode,
        "method": method,
        "nTrials": n_trials if method == "bayesian" else None,
        "seed": base_seed if method == "bayesian" else None,
        "nFoldsRequested": n_folds,
        "nFoldsBuilt": len(folds),
        "trainRatio": train_ratio,
        "objective": objective,
        "minTrades": min_trades,
        "folds": fold_results,
        "stitchedOOS": stitched,
        "avgDegradationRatio": avg_degradation,
        "minTradesWarning": min_trades_warning,
        "meta": {
            "paramGrid": param_grid,
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
