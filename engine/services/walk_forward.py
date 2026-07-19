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
- **Phase 4a: MC-scored trial selection** (opt-in, `config.mcScoring`,
  default `False` — zero behavior change for every existing run). Plan 10
  §2.3 calls this "the piece that makes the name 'Monte Carlo optimiser'
  accurate": instead of OOS-evaluating only each fold's raw-loss winner,
  OOS-evaluate its top-`mcTopK` (default 3, capped `MAX_MC_TOP_K`=10)
  min-trades-*eligible* trials and rank them by Monte Carlo p5 profit
  outcome (`services.monte_carlo.compute_mc_stats`, extracted this session
  as a Mongo-free pure function) instead of the raw point-estimate loss —
  the fold's `robustPick` can differ from its `rawPick` (`bestParams`),
  demonstrating the fragility gap a point metric hides. Deliberate
  subtlety: candidates come from `trials` filtered through `_eligible_trials`
  (finite loss + `totalTrades >= minTrades`), NOT `trials[:topK]` by raw
  `rank` — `fold.trials` carries every scored combo's rank *before* the
  min-trades honesty filter `optimizer._finalize_optimization` applies to
  pick `best`, so a naive top-K-by-rank read would silently reintroduce the
  exact lucky-few-trades problem `minTrades` exists to suppress, and could
  disagree with `bestParams`. `eligible[0]` is always identical to the
  fold's own raw-loss winner (its OOS result is reused, not re-run, to
  avoid a duplicate backtest). A candidate with too few OOS trades
  (`< MIN_MC_OOS_TRADES`=10 — below this a block bootstrap degenerates to
  1-2 blocks, so the "distribution" is really just which single block got
  picked) gets `insufficientData: True` rather than a fabricated percentile,
  same honesty stance as DSR's own `insufficientData` guard. Per-candidate
  MC output omits `equityBands` (`include_equity_bands=False`) — storing a
  full downsampled band series for up to `topK`(10) x `nFolds`(12) = 120
  candidates risked real `labResults` document bloat; only the small
  scalar percentiles are kept. The extra top-K OOS backtests are NOT added
  to `test_job_ids`/the stitched-OOS aggregate — that aggregate's meaning
  ("what actually would have been traded, stitched across each fold's raw
  pick") stays identical regardless of `mcScoring`. Phase 4b's
  robust-pick copy-to-backtest UI action and the backtest-page MC summary
  auto-enqueue strip shipped separately (client-only, no engine change).
- **Phase 4b: risk_pct/leverage search** (opt-in, `config.riskLeverageGrid`,
  default `None` — zero behavior change for every existing run). 2026-07-19
  decision, after scoping both real options: a SEPARATE grid (keys
  `risk_pct`/`leverage`) cartesian-multiplied against the strategy's own
  `param_grid` inside `optimizer._build_combined_grid`/`_suggest_params` —
  NOT tagged/prefixed keys merged into the same dict, because
  `run_backtest_simulation` validates every `alpha_params` key strictly
  against the strategy's own `PARAMS` schema and would error on an unknown
  `risk_pct` key rather than ignore it. Searched independently per fold —
  which turned out to require no new per-fold logic at all, since each
  fold already runs its own independent `run_optimization`/
  `run_bayesian_optimization` call; the combined grid is just what's handed
  to it. The combinatorial-explosion risk this decision flagged (a 3-param
  strategy grid capped at 200, multiplied by 3x3 risk/leverage values,
  becomes 1,800 combos with no existing guardrail catching it) is closed by
  `_build_combined_grid` computing the TRUE combined total across every
  dimension and sampling over THAT combined index space — the exact same
  guardrail class as `_build_param_grid`'s own OOM-prevention fix, just
  extended to cover the extra dimensions. A fold's winning trial's own
  `riskLeverage` (not the job's flat default) is used for that trial's OOS
  evaluation (`_override_bt_common`) — including inside `_mc_score_fold`'s
  extra top-K candidates, each evaluated at ITS OWN searched risk/leverage,
  not the job-wide fallback.
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
from services.monte_carlo import compute_mc_stats, returns_from_trades, _seed_from_key
from utils.timeframes import to_timedelta

logger = logging.getLogger(__name__)

MIN_FOLD_CANDLES = 20  # reject folds whose train or test slice would be too small to trust
DEFAULT_N_FOLDS = 4
DEFAULT_TRAIN_RATIO = 0.7

# Phase 4a — MC-scored trial selection guardrails
DEFAULT_MC_TOP_K = 3
MAX_MC_TOP_K = 10  # real-cost multiplier on backtest count (each extra candidate = 1 more
                    # full OOS backtest per fold) — same guardrail stance as
                    # MAX_MAX_COMBINATIONS/MAX_N_TRIALS. Server-side (labConfig.js) clamps too;
                    # engine re-clamps defensively rather than trusting the caller.
MC_SCORING_RUNS = 2_000  # internal ranking signal, not the user-facing detailed MC report
                          # (that already exists standalone with its own `runs` knob) — called
                          # up to topK x nFolds times per job, kept small deliberately.
MIN_MC_OOS_TRADES = 10   # below this a block bootstrap (block_len ~sqrt(N)) degenerates to
                          # 1-2 blocks — the "distribution" would just reflect which single
                          # block got picked, not genuine resampling variance. Same honesty
                          # stance as DSR's own `insufficientData` guard.


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


def _override_bt_common(bt_common: dict, risk_leverage: dict | None) -> dict:
    """Phase 4b (risk_pct/leverage search, 2026-07-19 decision: separate grid
    multiplied against the strategy grid, searched independently per fold —
    which is already this file's existing per-fold-independent-optimization
    behavior, no new per-fold logic needed for that half of the decision).

    A fold's winning trial (or an MC-scored candidate) may carry its own
    `riskLeverage` sub-dict (`optimizer.py`'s `_build_combined_grid`/
    `_suggest_params` output) distinct from the job's job-wide `leverage`/
    `risk_params` in `bt_common`. This returns a shallow-copied `bt_common`
    with `leverage`/`risk_params` overridden to match — so the OOS
    evaluation of a trial that searched a different risk_pct/leverage
    actually uses THAT trial's winning values, not the job's flat default.
    A `None`/empty `risk_leverage` returns `bt_common` unchanged (by value,
    not reference — callers may still merge further kwargs into the result)."""
    if not risk_leverage:
        return dict(bt_common)
    out = dict(bt_common)
    if "leverage" in risk_leverage:
        out["leverage"] = int(risk_leverage["leverage"])
    if "risk_pct" in risk_leverage:
        out["risk_params"] = {**(bt_common.get("risk_params") or {}), "risk_pct": risk_leverage["risk_pct"]}
    return out


def _eligible_trials(trials: list[dict], min_trades: int) -> list[dict]:
    """Reconstructs `optimizer._finalize_optimization`'s own `eligible` filter
    (finite loss + `totalTrades >= min_trades`) against `fold.trials` —
    required because that list carries every scored combo's `rank`, assigned
    BEFORE the min-trades honesty filter is applied there (`best` is
    `eligible[0]`, not `results[0]`). `eligible[0]` here is always identical
    to the fold's own `bestParams` winner. Deliberately filters out
    non-finite-loss (errored) entries even when `min_trades<=0` — unlike
    `optimizer.py`'s literal `eligible = scored` in that branch, which
    technically leaves error entries in the list (they never actually
    surface as `best` there since ascending sort puts them last, but they
    have no business being OOS-evaluated as a "top candidate" here)."""
    if min_trades <= 0:
        return [t for t in trials if t.get("loss") is not None]
    eligible = []
    for t in trials:
        if t.get("loss") is None:
            continue
        if _safe_float_metric(t.get("metrics") or {}, "totalTrades", 0) >= min_trades:
            eligible.append(t)
    return eligible


async def _mc_score_fold(
    lab_id: str,
    fold_index: int,
    fold: dict,
    eligible: list[dict],
    top_k: int,
    bt_common: dict,
    capital: float,
    best_oos: dict,
) -> dict | None:
    """OOS-evaluate the fold's top-`top_k` eligible trials and rank them by
    Monte Carlo p5 profit outcome instead of the raw point-estimate loss —
    Plan 10 §2.3, "the piece that makes the name 'Monte Carlo optimiser'
    accurate." `eligible[0]` is always the fold's existing raw-loss winner;
    its OOS result (`best_oos`) is reused rather than re-run. Returns `None`
    when there are no eligible candidates (mirrors the fold's own `skipped`
    case, which the caller already handles before this is invoked)."""
    candidates = eligible[:top_k]
    if not candidates:
        return None

    db = get_database()
    scored = []

    for i, candidate in enumerate(candidates):
        rank = candidate["rank"]
        if i == 0:
            test_job_id = best_oos["testJobId"]
            oos_metrics = best_oos["metrics"]
            oos_trade_count = best_oos["tradeCount"]
        else:
            test_job_id = f"wf_{lab_id}_fold{fold_index}_test_k{rank}"
            # Phase 4b: each candidate may have searched its own risk_pct/
            # leverage — reuse THAT candidate's values for its OOS
            # evaluation, not the job's flat `bt_common` default.
            candidate_bt_common = _override_bt_common(bt_common, candidate.get("riskLeverage"))
            test_result = await run_backtest_simulation(
                job_id=test_job_id,
                start_date=fold["testStart"],
                end_date=fold["testEnd"],
                alpha_params=candidate["params"],
                **candidate_bt_common,
            )
            oos_metrics = test_result.get("metrics", {})
            oos_trade_count = test_result.get("tradeCount", 0)

        entry: dict[str, Any] = {
            "rank": rank,
            "params": candidate["params"],
            "riskLeverage": candidate.get("riskLeverage"),
            "oosMetrics": oos_metrics,
            "oosTradeCount": oos_trade_count,
            "mc": None,
            "fragilityGap": None,
            "insufficientData": True,
        }

        if oos_trade_count >= MIN_MC_OOS_TRADES:
            cursor = db.backtestTrades.find({"jobId": test_job_id})
            trades = await cursor.to_list(length=100_000)
            returns = returns_from_trades(trades, capital)
            if len(returns) >= MIN_MC_OOS_TRADES:
                seed = _seed_from_key(f"{lab_id}:fold{fold_index}:k{rank}")
                mc = compute_mc_stats(
                    returns,
                    mode="block",
                    n_runs=MC_SCORING_RUNS,
                    block_len=None,
                    ruin_threshold_pct=30.0,
                    seed=seed,
                    include_equity_bands=False,
                )
                p5_profit_pct = (mc["finalEquityPercentiles"]["5"] - 1.0) * 100
                point_profit_pct = _safe_float(oos_metrics, "netProfitPct")
                mc["p5ProfitPct"] = p5_profit_pct
                entry["mc"] = mc
                entry["fragilityGap"] = (
                    point_profit_pct - p5_profit_pct
                    if point_profit_pct is not None and not math.isnan(point_profit_pct)
                    else None
                )
                entry["insufficientData"] = False

        scored.append(entry)

    valid = [c for c in scored if not c["insufficientData"]]
    robust_pick = max(valid, key=lambda c: c["mc"]["p5ProfitPct"]) if valid else None

    return {
        "enabled": True,
        "topK": len(candidates),
        "runsPerCandidate": MC_SCORING_RUNS,
        "candidates": scored,
        "robustPick": robust_pick,
        "rawPick": scored[0],
    }


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

    # Phase 4b (risk_pct/leverage search) — opt-in, `None`/absent = zero
    # behavior change for every existing run. A separate grid (keys
    # `risk_pct`/`leverage`) cartesian-multiplied against `param_grid`
    # inside `optimizer._build_combined_grid`/`_suggest_params`, not merged
    # into it — see that function's own docstring for why. Searched
    # independently per fold (2026-07-19 decision) — which is simply this
    # loop's own existing per-fold-independent-optimization behavior; no
    # special-casing needed for that half of the decision.
    risk_leverage_grid = config.get("riskLeverageGrid")

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

    # Phase 4a — opt-in, default False = zero behavior change for every
    # existing run. Re-clamped here even though labConfig.js already clamps
    # server-side (defense in depth, same stance as every other guardrail
    # in this file).
    mc_scoring_enabled = bool(config.get("mcScoring", False))
    mc_top_k = min(int(config.get("mcTopK") or DEFAULT_MC_TOP_K), MAX_MC_TOP_K) if mc_scoring_enabled else 1

    exchange = config["exchange"]
    symbol = config["symbol"]
    timeframe = config["timeframe"]
    capital = float(config["capital"])
    leverage = int(config.get("leverage") or 10)
    fee_rate = float(config.get("feeRate") or 0.0005)

    # Shared OOS backtest kwargs (fold-invariant) — used both by the existing
    # single-winner OOS call below and, when mcScoring is enabled, by
    # `_mc_score_fold`'s extra top-K candidates.
    bt_common = {
        "strategy_file": config["strategyFile"],
        "exchange": exchange,
        "symbol": symbol,
        "timeframe": timeframe,
        "capital": capital,
        "leverage": leverage,
        "fee_rate": fee_rate,
        "slippage_pct": config.get("slippagePct"),
        "funding_enabled": bool(config.get("fundingEnabled", False)),
        "funding_rate": config.get("fundingRate"),
        "risk_params": config.get("riskParams"),
    }

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
                risk_leverage_grid=risk_leverage_grid,
            )
        else:
            train_result = await run_optimization(
                config=train_config,
                param_grid=param_grid,
                job_id=fold_job_id,
                risk_leverage_grid=risk_leverage_grid,
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
        best_risk_leverage = best.get("riskLeverage")
        is_metrics = best.get("metrics", {})
        trials = _json_safe_trials(train_result.get("results", []))
        dsr = _compute_fold_dsr(train_result.get("results", []), is_metrics)

        test_job_id = f"wf_{lab_id}_fold{i}_test"
        # Phase 4b: use the winning trial's OWN risk_pct/leverage (if this
        # run searched them) for its OOS evaluation, not the job's flat
        # `bt_common` default — a trial that won because a wider leverage
        # amplified in-sample returns must be OOS-tested at that SAME
        # leverage, not silently re-evaluated at the job's default.
        best_bt_common = _override_bt_common(bt_common, best_risk_leverage)
        test_result = await run_backtest_simulation(
            job_id=test_job_id,
            start_date=fold["testStart"],
            end_date=fold["testEnd"],
            alpha_params=best_params,
            **best_bt_common,
        )
        oos_metrics = test_result.get("metrics", {})
        oos_trade_count = test_result.get("tradeCount", 0)
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

        fold_result = {
            "fold": i,
            "trainRange": [fold["trainStart"], fold["trainEnd"]],
            "testRange": [fold["testStart"], fold["testEnd"]],
            "bestParams": best_params,
            "bestRiskLeverage": best_risk_leverage,
            "isMetrics": is_metrics,
            "oosMetrics": oos_metrics,
            "oosTradeCount": oos_trade_count,
            "degradationRatio": degradation,
            "trials": trials,
            "dsr": dsr,
        }

        if mc_scoring_enabled:
            eligible = _eligible_trials(trials, min_trades)
            mc_scoring_block = await _mc_score_fold(
                lab_id=lab_id,
                fold_index=i,
                fold=fold,
                eligible=eligible,
                top_k=mc_top_k,
                bt_common=bt_common,
                capital=capital,
                best_oos={"testJobId": test_job_id, "metrics": oos_metrics, "tradeCount": oos_trade_count},
            )
            if mc_scoring_block is not None:
                fold_result["mcScoring"] = mc_scoring_block

        fold_results.append(fold_result)

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
