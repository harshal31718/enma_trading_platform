"""Backtest curves (A-009 / A-010 / A-011).

Each curve function takes the per-run artefacts and returns a downsampled
list of dicts suitable for MongoDB insertion.  Sampled to ``max_points`` so
the result document stays well under the 1 MB BSON limit even on multi-year
1-minute backtests (freqtrade uses 1000; Enma's equity-curve cap is also 1000
— same budget here so the four curves collectively cost the same as one).

Why dedicated module: keeps the inner backtest loop clean.  Each function is
called once at the end of the run, with the same inputs the runner already
tracks.  Easy to unit-test, easy to extend (add a curve = add one function).
"""
from __future__ import annotations

from typing import Any
import math
import numpy as np


# ── Downsample helper (shared) ────────────────────────────────────────────────

def _downsample(indices_source: np.ndarray, max_points: int) -> np.ndarray:
    """Return ``max_points`` evenly-spaced indices into ``indices_source``.

    Single source of truth for the downsampling policy.  Mirrors the
    ``np.linspace`` approach used in ``backtest_runner.py``.
    """
    n = len(indices_source)
    if n <= max_points:
        return np.arange(n, dtype=np.int32)
    return np.round(np.linspace(0, n - 1, max_points)).astype(np.int32)


# ── A-009 ★★ Underwater / drawdown curve ─────────────────────────────────────

def underwater_curve(balances: np.ndarray, max_points: int = 1000) -> list[dict]:
    """Equity below the running peak, expressed as a negative percent.

    Persistence shape (matches ``equityCurve``):
        ``[{"timestamp": "<iso>", "drawdownPct": "-3.45"}, ...]``
    """
    if balances.size == 0:
        return []
    running_max = np.maximum.accumulate(balances)
    dd = np.where(running_max > 0, (balances - running_max) / running_max, 0.0)
    # Caller passes timestamps separately; this fn only handles the percent series.
    # Timestamp alignment happens in the runner.
    idx = _downsample(dd, max_points)
    return [{"index": int(i), "drawdownPct": f"{float(dd[i]) * 100:.2f}"} for i in idx]


def underwater_curve_with_timestamps(
    equity_timestamps: list[str],
    balances: np.ndarray,
    max_points: int = 1000,
) -> list[dict]:
    """Same as ``underwater_curve`` but with timestamps inlined."""
    if balances.size == 0 or not equity_timestamps:
        return []
    running_max = np.maximum.accumulate(balances)
    dd = np.where(running_max > 0, (balances - running_max) / running_max, 0.0)
    idx = _downsample(dd, max_points)
    return [
        {"timestamp": equity_timestamps[int(i)], "drawdownPct": f"{float(dd[int(i)]) * 100:.2f}"}
        for i in idx
    ]


# ── A-010 ★★ Returns distribution + MFE/MAE scatter ─────────────────────────

# Bin edges — symmetric around zero so we can label "big loss / small loss /
# scratch / small win / big win" cleanly.  Returns expressed as % of starting
# equity.  11 buckets covers ±50% with 10% resolution.
_RET_BIN_EDGES_PCT: list[float] = [-100, -50, -25, -10, -5, -1, 1, 5, 10, 25, 50, 1000]


def returns_histogram(trades: list[dict], capital: float, bin_edges_pct: list[float] | None = None) -> list[dict]:
    """Per-trade P&L as % of starting equity, bucketed.

    Persistence shape:
        ``[{"label": "-100% to -50%", "count": 3, "lo": -100, "hi": -50}, ...]``
    """
    edges = bin_edges_pct or _RET_BIN_EDGES_PCT
    if not trades or capital <= 0:
        return [
            {"label": _bucket_label(edges[i], edges[i + 1]),
             "lo": edges[i], "hi": edges[i + 1], "count": 0}
            for i in range(len(edges) - 1)
        ]
    pnls_pct = np.array(
        [(float(t["pnl"]) / capital) * 100.0 for t in trades],
        dtype=np.float64,
    )
    counts, _ = np.histogram(pnls_pct, bins=edges)
    return [
        {
            "label": _bucket_label(edges[i], edges[i + 1]),
            "lo": float(edges[i]),
            "hi": float(edges[i + 1]),
            "count": int(counts[i]),
        }
        for i in range(len(edges) - 1)
    ]


def _bucket_label(lo: float, hi: float) -> str:
    if lo <= -999:
        return f"< {hi:g}%"
    if hi >= 999:
        return f"≥ {lo:g}%"
    return f"{lo:g}% to {hi:g}%"


def mfe_mae_scatter(trades: list[dict], capital: float, max_points: int = 5000) -> list[dict]:
    """Scatter of MFE vs MAE per trade, as % of starting equity.

    Each trade contributes one point.  Capped at ``max_points`` for storage;
    on longer runs the first ``max_points`` trades are kept (deterministic
    index ordering matters less than bounding the document size).
    """
    if not trades or capital <= 0:
        return []
    pts = []
    for t in trades[:max_points]:
        entry = float(t["entryPrice"])
        if entry <= 0:
            continue
        mfe = float(t.get("_mfe", 0.0)) / entry * 100.0
        mae = abs(float(t.get("_mae", 0.0))) / entry * 100.0
        pts.append({
            "mfePct": f"{mfe:.2f}",
            "maePct": f"{mae:.2f}",
            "exitReason": t.get("exitReason", "unknown"),
            "pnl": t.get("pnl", "0.00"),
        })
    return pts


# ── A-011 ★  Rolling Sharpe / volatility curve ───────────────────────────────

def _rolling_window_indices(n: int, window: int) -> np.ndarray:
    """Return an int array of length n where each row is the inclusive start index of its window.

    Used so the runner doesn't have to recompute windowing downstream.
    """
    starts = np.arange(n, dtype=np.int32) - (window - 1)
    return np.clip(starts, 0, n - 1)


def rolling_curve(
    balances: np.ndarray,
    timeframe_seconds: float,
    annual_factor: float,
    window_candles: int = 50,
    max_points: int = 1000,
) -> list[dict]:
    """Rolling Sharpe + rolling volatility, sampled to ``max_points``.

    Output element shape:
        ``{"index": <int>, "sharpe": "1.23", "volatility": "0.45"}``

    Volatility is the rolling std-dev of per-candle returns, annualised by
    ``sqrt(annual_factor)`` so it's directly comparable across timeframes.
    """
    n = balances.size
    if n <= 1 or window_candles < 2:
        return []

    # Per-candle returns
    prev = balances[:-1]
    curr = balances[1:]
    mask = prev > 0
    rets = np.where(mask, (curr - prev) / prev, 0.0)        # length n-1
    rets = np.concatenate([[0.0], rets])                    # length n, index aligned with balances

    starts = _rolling_window_indices(n, window_candles)
    # For each end-index i, the window covers [starts[i], i]
    end_idx = np.arange(n, dtype=np.int32)
    # Use cumulative sums to make rolling stats O(n) instead of O(n*w).
    csum  = np.concatenate([[0.0], np.cumsum(rets)])
    csum2 = np.concatenate([[0.0], np.cumsum(rets * rets)])
    window_sizes = (end_idx - starts + 1).astype(np.float64)

    sums  = csum[end_idx + 1]  - csum[starts]
    sums2 = csum2[end_idx + 1] - csum2[starts]
    means = sums / window_sizes
    var   = np.maximum(sums2 / window_sizes - means * means, 0.0)
    stds  = np.sqrt(var)
    # Sharpe of the window — only meaningful once we have >=2 returns.
    # Guard the divide so all-zero windows don't emit a RuntimeWarning.
    safe_stds = np.where(stds > 0, stds, 1.0)
    sharpes = np.where(
        stds > 0,
        (means / safe_stds) * math.sqrt(annual_factor),
        0.0,
    )
    # Annualised volatility
    vols = stds * math.sqrt(annual_factor)

    idx = _downsample(np.arange(n), max_points)
    return [
        {
            "index": int(i),
            "sharpe": f"{float(sharpes[int(i)]):.2f}",
            "volatility": f"{float(vols[int(i)]):.4f}",
        }
        for i in idx
    ]


def timeframe_to_seconds(timeframe: str) -> float:
    """Tiny helper — freqtrade-style timeframe string to seconds.

    Kept here (not in ``utils.timeframes``) because this module is the only
    caller right now; promote later if reuse emerges.
    """
    table = {
        "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
        "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600,
        "8h": 28800, "12h": 43200, "1d": 86400, "1D": 86400,
        "3d": 259200, "1w": 604800, "1W": 604800,
    }
    return float(table.get(timeframe, 3600))