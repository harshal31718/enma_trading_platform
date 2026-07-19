"""Parameter optimization run mode (A-006).

Runs ``run_backtest_simulation`` over a grid of parameter combinations,
scores each by a chosen objective function, and returns the ranked results.

Usage::

    from services.optimizer import run_optimization, OptimizerConfig

    result = await run_optimization(
        config=OptimizerConfig(
            strategy_file="strategies/MyStrategy",
            exchange="Binance Futures",
            symbol="BTCUSDT",
            timeframe="1h",
            start_date="2024-01-01",
            end_date="2024-12-31",
            capital=10000,
            leverage=10,
            fee_rate=0.0005,
            objective="sharpe",
        ),
        param_grid={
            "fast_period": {"min": 5, "max": 30, "step": 5, "type": "int"},
            "slow_period": {"min": 20, "max": 100, "step": 10, "type": "int"},
            "atr_multiplier": {"min": 1.0, "max": 4.0, "num": 4, "type": "float"},
        },
        max_combinations=50,
    )
"""

import itertools
import json
import logging
import math
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np

from config.mongo import get_database
from services.backtest_runner import run_backtest_simulation

logger = logging.getLogger(__name__)

# ── Objective functions ──────────────────────────────────────────────────────

OBJECTIVE_REGISTRY: dict[str, Callable[[dict], float]] = {}


def _register_objective(name: str):
    def decorator(fn):
        OBJECTIVE_REGISTRY[name] = fn
        return fn
    return decorator


def _safe_float_metric(metrics: dict, key: str, default: float = 0.0) -> float:
    """Parse a metric value that may be stored as a str or numeric."""
    val = metrics.get(key, default)
    if isinstance(val, str):
        try:
            return float(val)
        except (ValueError, TypeError):
            return default
    return float(val)


@_register_objective("sharpe")
def _obj_sharpe(metrics: dict) -> float:
    return -_safe_float_metric(metrics, "sharpeRatio")


@_register_objective("sortino")
def _obj_sortino(metrics: dict) -> float:
    return -_safe_float_metric(metrics, "sortinoRatio")


@_register_objective("calmar")
def _obj_calmar(metrics: dict) -> float:
    return -_safe_float_metric(metrics, "calmarRatio")


@_register_objective("profit")
def _obj_profit(metrics: dict) -> float:
    return -_safe_float_metric(metrics, "netProfit", default=0.0)


@_register_objective("profit_pct")
def _obj_profit_pct(metrics: dict) -> float:
    return -_safe_float_metric(metrics, "netProfitPct", default=0.0)


@_register_objective("drawdown")
def _obj_drawdown(metrics: dict) -> float:
    return _safe_float_metric(metrics, "maxDrawdown", default=100.0)


@_register_objective("sqn")
def _obj_sqn(metrics: dict) -> float:
    return -_safe_float_metric(metrics, "sqn")


@_register_objective("multi")
def _obj_multi(metrics: dict) -> float:
    """Composite: maximize Sharpe + Sortino + profit factor, minimize drawdown."""
    sharpe = _safe_float_metric(metrics, "sharpeRatio")
    sortino = _safe_float_metric(metrics, "sortinoRatio")
    profit_factor = _safe_float_metric(metrics, "profitFactor", default=1.0)
    dd = _safe_float_metric(metrics, "maxDrawdown", default=100.0)
    return -(sharpe + sortino + profit_factor) + abs(dd) * 0.5


def list_objectives() -> list[str]:
    return list(OBJECTIVE_REGISTRY.keys())


# ── Config ───────────────────────────────────────────────────────────────────

@dataclass
class OptimizerConfig:
    """Base configuration for an optimization run (shared across combinations)."""

    strategy_file: str
    exchange: str
    symbol: str
    timeframe: str
    start_date: str
    end_date: str
    capital: float
    leverage: int
    fee_rate: float = 0.0005
    slippage_pct: float | None = None
    funding_enabled: bool = False
    funding_rate: float | None = None
    risk_params: dict | None = None
    objective: str = "sharpe"
    max_combinations: int = 0  # 0 = all combinations
    min_trades: int = 0  # 0 = off (backward compatible); Plan 10 Phase 3 honesty-layer
    # filter — excludes lucky-few-trades combos from being selected as `best`
    # (still reported in `results`, just ineligible for the top pick).


# ── Grid generation ──────────────────────────────────────────────────────────

def _expand_param_range(spec: dict) -> list:
    """Generate candidate values for one parameter from its grid spec.

    Supported spec keys:
        type: "int" | "float" | "categorical"
        min, max: range bounds (for int/float)
        step: step size (int types)
        num: number of steps including endpoints (float types)
        values: explicit list (categorical types)
    """
    ptype = spec.get("type", "int")

    if ptype == "categorical" or "values" in spec:
        return list(spec["values"])

    min_v = spec["min"]
    max_v = spec["max"]

    if ptype == "int":
        step = spec.get("step", 1)
        return list(range(min_v, max_v + 1, step))
    else:
        num = spec.get("num", 10)
        vals = np.linspace(float(min_v), float(max_v), int(num))
        return [round(float(v), 6) for v in vals]


def _decode_combo_index(idx: int, value_lists: list[list]) -> tuple:
    """Decode a linear index into the combo tuple `itertools.product` would
    have produced at that position (last list varies fastest — mixed-radix
    decomposition), WITHOUT materializing the product. See `_build_param_grid`
    for why this matters: a strategy with several wide-range params can have
    a total combo count in the trillions."""
    combo = []
    for values in reversed(value_lists):
        idx, r = divmod(idx, len(values))
        combo.append(values[r])
    combo.reverse()
    return tuple(combo)


def _build_param_grid(
    param_grid: dict[str, dict],
    max_combinations: int = 0,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Generate all (or a random subset of) parameter combinations.

    Guards against materializing an astronomically large cartesian product:
    a strategy with, say, 8 params each expanded to ~300 values has a total
    combo count in the hundreds of trillions — `list(itertools.product(...))`
    on that tries to allocate a list of that size and hangs/OOMs the entire
    engine process (found via live UI testing, Plan 10 Phase 3e session —
    checking several AdaptiveTrend params in the Optimizer wizard with
    default-width ranges reproducibly froze the container). When the grid is
    larger than `max_combinations`, sample indices directly (`random.sample`
    on a `range` object is O(k), does not materialize the range) and decode
    each one straight to its combo (`_decode_combo_index`) — the full
    product is only ever materialized when it's already small enough to be
    safe (`total <= max_combinations`, or `max_combinations == 0` i.e. "run
    the whole grid," which callers are expected to bound themselves for that
    case, same as before this fix)."""
    expanded = {}
    for key, spec in param_grid.items():
        expanded[key] = _expand_param_range(spec)

    keys = list(expanded.keys())
    value_lists = [expanded[k] for k in keys]

    total = 1
    for values in value_lists:
        total *= len(values)

    if max_combinations > 0 and total > max_combinations:
        rng = random.Random(seed)
        indices = sorted(rng.sample(range(total), max_combinations))
        all_combos = [_decode_combo_index(i, value_lists) for i in indices]
    else:
        all_combos = list(itertools.product(*value_lists))

    return [dict(zip(keys, combo)) for combo in all_combos]


# ── Optimization runner ──────────────────────────────────────────────────────

async def run_optimization(
    config: OptimizerConfig,
    param_grid: dict[str, dict],
    job_id: str | None = None,
    progress_callback: Callable[[int, int, dict], None] | None = None,
) -> dict:
    """Run parameter optimization over a grid of combinations.

    Returns the ranked results dict with keys:
        jobId: str
        status: str
        objective: str
        totalCombinations: int
        results: list[dict]  — each with params, metrics, rank, loss
        best: dict           — the single best result
    """
    if job_id is None:
        job_id = f"opt_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{config.strategy_file.split('/')[-1]}"

    objective_fn = OBJECTIVE_REGISTRY.get(config.objective)
    if objective_fn is None:
        raise ValueError(
            f"Unknown objective '{config.objective}'. "
            f"Available: {list_objectives()}"
        )

    combinations = _build_param_grid(param_grid, config.max_combinations)
    total = len(combinations)

    if total == 0:
        return {
            "jobId": job_id,
            "status": "completed",
            "method": "grid",
            "objective": config.objective,
            "totalCombinations": 0,
            "results": [],
        }

    logger.info(
        "[Optimizer] %s: running %d combinations (objective=%s)",
        job_id, total, config.objective,
    )

    scored: list[dict] = []
    completed = 0
    errors = 0

    for idx, alpha_params in enumerate(combinations):
        combo_job_id = f"{job_id}_c{idx:04d}"
        try:
            bt_result = await run_backtest_simulation(
                job_id=combo_job_id,
                strategy_file=config.strategy_file,
                exchange=config.exchange,
                symbol=config.symbol,
                timeframe=config.timeframe,
                start_date=config.start_date,
                end_date=config.end_date,
                capital=config.capital,
                leverage=config.leverage,
                fee_rate=config.fee_rate,
                slippage_pct=config.slippage_pct,
                funding_enabled=config.funding_enabled,
                funding_rate=config.funding_rate,
                alpha_params=alpha_params,
                risk_params=config.risk_params,
            )

            metrics = bt_result.get("metrics", {})
            loss = objective_fn(metrics)

            scored.append({
                "params": dict(alpha_params),
                "loss": loss,
                "rank": 0,
                "metrics": {
                    k: metrics[k]
                    for k in ("totalTrades", "winRate", "netProfit", "netProfitPct",
                              "maxDrawdown", "sharpeRatio", "sortinoRatio", "calmarRatio",
                              "profitFactor", "sqn", "expectancy", "cagrPct",
                              "maxConsecutiveWins", "maxConsecutiveLosses",
                              "skewness", "kurtosis")
                    if k in metrics
                },
            })
            trade_count = bt_result.get("tradeCount", 0)
            net_profit = metrics.get("netProfit", "0.00")
            logger.info(
                "[Optimizer] %s combo %d/%d: loss=%.4f trades=%d netPnl=%s",
                job_id, idx + 1, total, loss, trade_count, net_profit,
            )

        except Exception as e:
            errors += 1
            logger.warning(
                "[Optimizer] %s combo %d/%d failed: %s",
                job_id, idx + 1, total, e,
            )
            scored.append({
                "params": dict(alpha_params),
                "loss": float("inf"),
                "rank": 0,
                "error": str(e),
            })

        completed += 1

        if progress_callback:
            progress_callback(completed, total, {
                "best_loss": min(s["loss"] for s in scored if math.isfinite(s["loss"])) if any(math.isfinite(s["loss"]) for s in scored) else None,
                "errors": errors,
            })

        # Brief yield so the event loop stays responsive
        if idx % 5 == 0:
            await asyncio.sleep(0)

    return await _finalize_optimization(
        job_id=job_id, config=config, param_grid=param_grid,
        scored=scored, total=total, errors=errors, method="grid",
    )


# ── Bayesian (Optuna TPE) search ───────────────────────────────────────────
# Plan 19's design, absorbed into Plan 10 Phase 3b: same objective registry,
# same per-trial `run_backtest_simulation` call as grid search — only the
# search loop differs (TPE proposes each next trial's params instead of
# `itertools.product` enumerating all of them up front).

def _suggest_params(trial, param_grid: dict[str, dict]) -> dict[str, Any]:
    """Map one optuna trial onto the same `param_grid` spec `_expand_param_range`
    consumes for grid search — no new client contract (Plan 19 §Search-space
    mapping): `{min,max,step,type:int}` -> suggest_int, `{min,max,type:float}`
    -> suggest_float, `values`/categorical -> suggest_categorical."""
    params: dict[str, Any] = {}
    for name, spec in param_grid.items():
        ptype = spec.get("type", "int")
        if ptype == "categorical" or "values" in spec:
            params[name] = trial.suggest_categorical(name, list(spec["values"]))
        elif ptype == "int":
            step = spec.get("step", 1)
            params[name] = trial.suggest_int(name, int(spec["min"]), int(spec["max"]), step=step)
        else:
            params[name] = trial.suggest_float(name, float(spec["min"]), float(spec["max"]))
    return params


async def run_bayesian_optimization(
    config: OptimizerConfig,
    param_grid: dict[str, dict],
    n_trials: int,
    job_id: str | None = None,
    seed: int = 42,
    progress_callback: Callable[[int, int, dict], None] | None = None,
) -> dict:
    """TPE-sampled search over `param_grid`, same return shape as
    `run_optimization` (grid) so callers (walk_forward.py, the router) don't
    branch on method. Uses optuna's ask/tell API rather than
    `study.optimize(...)` — `study.optimize`'s callback is synchronous, and
    each trial needs to `await run_backtest_simulation(...)` (Plan 19's own
    documented risk: "ask/tell is cleaner for async").
    """
    import optuna
    from optuna.samplers import TPESampler

    if job_id is None:
        job_id = f"opt_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{config.strategy_file.split('/')[-1]}"

    objective_fn = OBJECTIVE_REGISTRY.get(config.objective)
    if objective_fn is None:
        raise ValueError(
            f"Unknown objective '{config.objective}'. "
            f"Available: {list_objectives()}"
        )

    if n_trials <= 0 or not param_grid:
        return {
            "jobId": job_id,
            "status": "completed",
            "method": "bayesian",
            "objective": config.objective,
            "totalCombinations": 0,
            "results": [],
        }

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction="minimize", sampler=TPESampler(seed=seed))

    logger.info(
        "[Optimizer] %s: running %d bayesian trials (objective=%s, seed=%d)",
        job_id, n_trials, config.objective, seed,
    )

    scored: list[dict] = []
    completed = 0
    errors = 0

    for idx in range(n_trials):
        trial = study.ask()
        alpha_params = _suggest_params(trial, param_grid)
        combo_job_id = f"{job_id}_t{idx:04d}"
        try:
            bt_result = await run_backtest_simulation(
                job_id=combo_job_id,
                strategy_file=config.strategy_file,
                exchange=config.exchange,
                symbol=config.symbol,
                timeframe=config.timeframe,
                start_date=config.start_date,
                end_date=config.end_date,
                capital=config.capital,
                leverage=config.leverage,
                fee_rate=config.fee_rate,
                slippage_pct=config.slippage_pct,
                funding_enabled=config.funding_enabled,
                funding_rate=config.funding_rate,
                alpha_params=alpha_params,
                risk_params=config.risk_params,
            )

            metrics = bt_result.get("metrics", {})
            loss = objective_fn(metrics)
            study.tell(trial, loss)

            scored.append({
                "params": dict(alpha_params),
                "loss": loss,
                "rank": 0,
                "metrics": {
                    k: metrics[k]
                    for k in ("totalTrades", "winRate", "netProfit", "netProfitPct",
                              "maxDrawdown", "sharpeRatio", "sortinoRatio", "calmarRatio",
                              "profitFactor", "sqn", "expectancy", "cagrPct",
                              "maxConsecutiveWins", "maxConsecutiveLosses",
                              "skewness", "kurtosis")
                    if k in metrics
                },
            })
            trade_count = bt_result.get("tradeCount", 0)
            net_profit = metrics.get("netProfit", "0.00")
            logger.info(
                "[Optimizer] %s trial %d/%d: loss=%.4f trades=%d netPnl=%s",
                job_id, idx + 1, n_trials, loss, trade_count, net_profit,
            )

        except Exception as e:
            errors += 1
            logger.warning(
                "[Optimizer] %s trial %d/%d failed: %s",
                job_id, idx + 1, n_trials, e,
            )
            # optuna requires every asked trial to be told something finite —
            # unlike grid's plain list append, tell() would raise on inf/nan.
            fail_loss = 1e18
            study.tell(trial, fail_loss)
            scored.append({
                "params": dict(alpha_params),
                "loss": float("inf"),
                "rank": 0,
                "error": str(e),
            })

        completed += 1

        if progress_callback:
            progress_callback(completed, n_trials, {
                "best_loss": min(s["loss"] for s in scored if math.isfinite(s["loss"])) if any(math.isfinite(s["loss"]) for s in scored) else None,
                "errors": errors,
            })

        if idx % 5 == 0:
            await asyncio.sleep(0)

    return await _finalize_optimization(
        job_id=job_id, config=config, param_grid=param_grid,
        scored=scored, total=n_trials, errors=errors, method="bayesian",
    )


# ── Shared ranking / eligibility / persistence tail ────────────────────────

async def _finalize_optimization(
    job_id: str,
    config: OptimizerConfig,
    param_grid: dict[str, dict],
    scored: list[dict],
    total: int,
    errors: int,
    method: str,
) -> dict:
    """Rank, apply the min-trades honesty filter, persist, and shape the
    result dict — identical for grid and bayesian search so callers never
    branch on `method` (Plan 19: "Return the same ranked-results shape ...
    so the UI is unchanged")."""
    scored.sort(key=lambda s: s["loss"])
    for rank, entry in enumerate(scored, start=1):
        entry["rank"] = rank

    if config.min_trades > 0:
        eligible = [
            s for s in scored
            if math.isfinite(s.get("loss", float("inf")))
            and _safe_float_metric(s.get("metrics", {}), "totalTrades", 0) >= config.min_trades
        ]
    else:
        eligible = scored

    best = eligible[0] if eligible else None

    # JSON-safety pass (applied only to the transport/persistence copies, not
    # to `scored`/`eligible` above — ranking and the min-trades filter both
    # need the real numeric loss). An errored/ineligible combo carries
    # `loss=float("inf")` by design (this module's own error path); Python's
    # `json` module rejects inf/-inf/nan outright
    # (`ValueError: Out of range float values are not JSON compliant`), which
    # crashed `GET /optimize/run`'s raw response the same way it crashed
    # walk_forward.py's per-fold trials before that was fixed in Phase 3d —
    # this closes the same gap at its source so every caller gets it for free.
    json_safe_results = [
        {**s, "loss": None} if not math.isfinite(s.get("loss", 0.0)) else s
        for s in scored
    ]
    json_safe_best = (
        {**best, "loss": None} if best is not None and not math.isfinite(best.get("loss", 0.0)) else best
    )

    result = {
        "jobId": job_id,
        "status": "completed",
        "method": method,
        "objective": config.objective,
        "totalCombinations": total,
        "errorCount": errors,
        "minTrades": config.min_trades,
        "eligibleCount": len(eligible),
        "paramGrid": param_grid,
        "config": {
            "strategyFile": config.strategy_file,
            "exchange": config.exchange,
            "symbol": config.symbol,
            "timeframe": config.timeframe,
            "startDate": config.start_date,
            "endDate": config.end_date,
            "capital": config.capital,
            "leverage": config.leverage,
        },
        "results": json_safe_results,
        "best": json_safe_best,
    }

    try:
        db = get_database()
        await db.backtestResults.update_one(
            {"jobId": job_id},
            {
                "$set": {
                    "jobId": job_id,
                    "strategyName": config.strategy_file.split("/")[-1],
                    "status": "completed",
                    "type": "optimization",
                    "method": method,
                    "objective": config.objective,
                    "totalCombinations": total,
                    "errorCount": errors,
                    "best": json_safe_best,
                    "updatedAt": datetime.now(timezone.utc),
                },
                "$setOnInsert": {"createdAt": datetime.now(timezone.utc)},
            },
            upsert=True,
        )
        # Store full results in a separate collection to keep the main doc small
        await db.optimizationResults.replace_one(
            {"jobId": job_id},
            {
                "jobId": job_id,
                "method": method,
                "objective": config.objective,
                "paramGrid": param_grid,
                "config": result["config"],
                "results": json_safe_results,
                "best": json_safe_best,
                "createdAt": datetime.now(timezone.utc),
            },
            upsert=True,
        )
    except Exception as e:
        logger.error("[Optimizer] %s: failed to persist results: %s", job_id, e)

    logger.info(
        "[Optimizer] %s: done (%s) — %d/%d ok, %d errors. Best loss=%.4f",
        job_id, method, total - errors, total, errors,
        best["loss"] if best else float("inf"),
    )

    return result


# ── Import asyncio at module level for the sleep call ────────────────────────
import asyncio
