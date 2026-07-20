"""Recursive-formula / warmup-insufficiency analysis (Plan 17).

Detects indicators whose LATEST value depends on how much history was loaded
(recursive formulas like EMA/RSI/SuperTrend, seeded from the start of
whatever window they're given). Distinct from the lookahead sentinel
(scripts/lookahead_sentinel.py): lookahead = future leak, this = insufficient
past. Relevant because live re-runs prepare() on a rolling <=500-candle
window (workstream #1, P7) — if a strategy's recursive indicators haven't
converged by warmup=500, live drifts silently from backtest.

Method (ported from freqtrade's optimize/analysis/recursive.py):
  1. Pick a fixed anchor index T (the last candle in the loaded range).
  2. Baseline: prepare() over the FULL available history up to T; record
     every prepare()-computed indicator column's value AT T.
  3. Varied warmups: for each w in WARMUPS, prepare() over only the last w
     candles ending at T; record the same columns' value at T again.
  4. pct_change = (partial - full) / full * 100 per column per w. No fixed
     pass/fail threshold on drift itself (freqtrade's own stance — report the
     magnitude, let the user judge) EXCEPT at w=500 (the live rolling-window
     size), which is flagged as an operational "live-vs-backtest drift risk"
     above TOL_PCT.

Indicator columns are discovered generically, not per-strategy: after
prepare() runs, any float ndarray on the strategy instance whose length
equals the candles window's length is treated as a sequential indicator
series (matches this codebase's own `self._*_seq` / `self._rsi` / `self._ph`
etc. naming — there's no single shared convention across the 5 seeded
strategies, so this reads the actual computed state rather than guessing
names). Integer/bool arrays (loop-index bookkeeping, boolean cross signals)
are excluded — they aren't the kind of "recursive value" this tool targets.

REQUIRES TA-Lib + TimescaleDB — run INSIDE the engine container:

    docker compose exec engine python -m scripts.recursive
    docker compose exec engine python -m scripts.recursive --only BestSupertrend
    docker compose exec engine python -m scripts.recursive --symbol ETHUSDT --timeframe 1h

Exit 0 = no column drifts beyond TOL_PCT at the live rolling-window size
(w=500) for any seeded strategy. Exit 1 = at least one does — bump that
strategy's live warmup replay length (a live_bot_manager.py knob).
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# See scripts/golden_master.py's identical comment — Plan 6 Step 6.6 (ENG-12).
from core.engine_alias import install_engine_alias  # noqa: E402
install_engine_alias()

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import numpy as np

STRATEGIES = [
    "MicroScalper",
    "AdaptiveTrend",
    "BestSupertrend",
    "MicroMacroRSIDivergence",
    "MultiDivergence",
]

DEFAULT_CONFIG = {
    "exchange": "Binance Futures",
    "symbol": "BTCUSDT",
    "timeframe": "1h",
    "start_date": "2024-01-01",
    "end_date": "2025-01-01",
}

# Freqtrade's own varied-warmup sweep, plus the strategy's own MIN_WARMUP_CANDLES
# is implicitly covered since 200 is already >= every seeded strategy's default.
WARMUPS = [200, 400, 500, 1000, 2000]

# live_bot_manager.py's rolling re-prepare window cap (workstream #1, P7) — the
# operationally important warmup size: does the live path actually converge?
LIVE_ROLLING_WINDOW = 500

TOL_PCT = 0.01  # percent — freqtrade reports any variance, we additionally flag this at w=500
EPS = 1e-9       # near-zero baseline guard (avoid inflated/undefined pct_change)


def _extract_indicator_columns(strategy, n: int) -> dict[str, np.ndarray]:
    """Every float ndarray on `strategy` whose length equals `n` — the
    prepare()-computed sequential indicator series, discovered generically
    (see module docstring for why there's no shared naming convention to
    rely on instead)."""
    cols = {}
    for name, val in vars(strategy).items():
        if (
            isinstance(val, np.ndarray)
            and val.ndim == 1
            and val.shape[0] == n
            and np.issubdtype(val.dtype, np.floating)
        ):
            cols[name] = val
    return cols


def _pct_change(full_val: float, partial_val: float) -> float | None:
    """None means 'report as —' (near-zero baseline, or both NaN — not a
    meaningful comparison either way). freqtrade's own near-zero guard."""
    if full_val is None or partial_val is None:
        return None
    full_nan, partial_nan = np.isnan(full_val), np.isnan(partial_val)
    if full_nan and partial_nan:
        return None
    if full_nan or partial_nan:
        return float("inf")  # one side has data, the other doesn't — maximal drift
    if abs(full_val) < EPS:
        return None
    return (partial_val - full_val) / full_val * 100.0


def _new_strategy(strategy_class, cfg: dict):
    strategy = strategy_class()
    strategy.exchange = cfg["exchange"]
    strategy.symbol = cfg["symbol"]
    strategy.timeframe = cfg["timeframe"]
    strategy.is_backtesting = True
    return strategy


def _prepare_at_anchor(
    strategy, candles: np.ndarray, anchor: int, warmup: int | None,
) -> dict[str, float]:
    """Run prepare() over a window ending at `anchor` (inclusive) with at
    most `warmup` preceding candles (None = full available history up to the
    anchor). Returns each discovered column's value at the window's last row
    — which is always the anchor candle, by construction of the slice."""
    if warmup is None:
        window = candles[: anchor + 1]
    else:
        start = max(0, anchor + 1 - warmup)
        window = candles[start: anchor + 1]
    strategy.prepare(window)
    cols = _extract_indicator_columns(strategy, len(window))
    return {name: float(arr[-1]) for name, arr in cols.items()}


def analyze(
    strategy_class, cfg: dict, candles: np.ndarray, warmups: list[int] = WARMUPS,
) -> dict:
    """Pure function (no DB/async) — the actual recursive-drift computation.
    Kept separate from `main()`'s DB/CLI plumbing so it's directly unit-
    testable (see tests/test_recursive.py)."""
    anchor = len(candles) - 1
    baseline_strategy = _new_strategy(strategy_class, cfg)
    baseline = _prepare_at_anchor(baseline_strategy, candles, anchor, None)

    columns: dict[str, dict[int, float | None]] = {col: {} for col in baseline}
    for w in warmups:
        if w > anchor + 1:
            continue  # not enough history loaded to even attempt this warmup
        s = _new_strategy(strategy_class, cfg)
        partial = _prepare_at_anchor(s, candles, anchor, w)
        for col, full_val in baseline.items():
            columns[col][w] = _pct_change(full_val, partial.get(col))

    return {"anchor_index": anchor, "n_candles": len(candles), "columns": columns}


def _print_report(name: str, report: dict, warmups: list[int] = WARMUPS) -> list[tuple[str, float]]:
    print(f"\n[recursive] {name} (anchor={report['anchor_index']}, n={report['n_candles']} candles)")
    drift_at_live_window: list[tuple[str, float]] = []
    for col, by_w in sorted(report["columns"].items()):
        cells = [
            f"w={w}: {'—' if by_w.get(w) is None else f'{by_w[w]:+.4f}%'}"
            for w in warmups
        ]
        print(f"  {col:28s} " + "  ".join(cells))
        pct_live = by_w.get(LIVE_ROLLING_WINDOW)
        if pct_live is not None and abs(pct_live) > TOL_PCT:
            drift_at_live_window.append((col, pct_live))

    if drift_at_live_window:
        print(
            f"  [recursive] {name}: LIVE-VS-BACKTEST DRIFT RISK at w={LIVE_ROLLING_WINDOW} "
            f"(> {TOL_PCT}% tol): "
            + ", ".join(f"{c} ({p:+.4f}%)" for c, p in drift_at_live_window)
        )
    else:
        print(f"  [recursive] {name}: no column drifts beyond {TOL_PCT}% at w={LIVE_ROLLING_WINDOW}")
    return drift_at_live_window


async def _load_candles(exchange: str, symbol: str, timeframe: str, start_date: str, end_date: str) -> np.ndarray:
    from config.timescale import get_pool
    from services.candle_manager import ensure_candles_available

    await ensure_candles_available(
        job_id="recursive_analysis", exchange=exchange, symbol=symbol, timeframe=timeframe,
        start_date=start_date, end_date=end_date,
    )

    start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT time, open, close, high, low, volume
            FROM candles
            WHERE exchange = $1 AND symbol = $2 AND timeframe = $3 AND time >= $4 AND time < $5
            ORDER BY time ASC
            """,
            exchange, symbol, timeframe, start_dt, end_dt,
        )
    if not rows:
        return np.empty((0, 6), dtype=np.float64)
    return np.column_stack([
        [r["time"].timestamp() * 1000 for r in rows],
        [r["open"]   for r in rows],
        [r["close"]  for r in rows],
        [r["high"]   for r in rows],
        [r["low"]    for r in rows],
        [r["volume"] for r in rows],
    ]).astype(np.float64)


async def main() -> int:
    p = argparse.ArgumentParser(description="Recursive-formula / warmup-insufficiency analysis")
    p.add_argument("--symbol")
    p.add_argument("--timeframe")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--only", help="comma-separated subset of strategies")
    args = p.parse_args()

    cfg = dict(DEFAULT_CONFIG)
    if args.symbol:
        cfg["symbol"] = args.symbol
    if args.timeframe:
        cfg["timeframe"] = args.timeframe
    if args.start:
        cfg["start_date"] = args.start
    if args.end:
        cfg["end_date"] = args.end
    strategies = (
        [s.strip() for s in args.only.split(",") if s.strip()] if args.only else STRATEGIES
    )

    from config.timescale import init_pool, close_pool

    await init_pool()
    try:
        candles = await _load_candles(
            cfg["exchange"], cfg["symbol"], cfg["timeframe"], cfg["start_date"], cfg["end_date"],
        )
        if len(candles) < max(WARMUPS) + 10:
            print(
                f"[recursive] WARNING: only {len(candles)} candles loaded — warmups above "
                f"~{len(candles)} will be skipped for lack of history"
            )

        any_drift: dict[str, list[tuple[str, float]]] = {}
        for name in strategies:
            module = importlib.import_module(f"strategies.{name}")
            strategy_class = getattr(module, name)
            report = analyze(strategy_class, cfg, candles)
            drifting = _print_report(name, report)
            if drifting:
                any_drift[name] = drifting
    finally:
        await close_pool()

    if any_drift:
        print(f"\n[recursive] RECURSIVE-FORMULA WARMUP DRIFT FOUND: {any_drift}")
        return 1
    print(
        "\n[recursive] RECURSIVE-FORMULA ANALYSIS OK — no live-vs-backtest drift risk found "
        f"at w={LIVE_ROLLING_WINDOW} for any analyzed strategy"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
