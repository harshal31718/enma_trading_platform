"""Tests for Phase 2 backtest curves (A-009 / A-010 / A-011)."""
import math
import numpy as np
import pytest
from services.curves import (
    underwater_curve_with_timestamps,
    returns_histogram,
    mfe_mae_scatter,
    rolling_curve,
    _downsample,
    timeframe_to_seconds,
)


def test_downsample_smaller_input_passthrough():
    arr = np.arange(50)
    out = _downsample(arr, 100)
    assert len(out) == 50
    assert out[0] == 0
    assert out[-1] == 49


def test_downsample_larger_input_evenly_spaced():
    arr = np.arange(1000)
    out = _downsample(arr, 100)
    assert len(out) == 100
    # First and last must be at endpoints
    assert out[0] == 0
    assert out[-1] == 999


# ── A-009 underwater curve ──────────────────────────────────────────────────

def test_underwater_curve_basic():
    # equity rises then drops then recovers — under water between bars 3-7
    balances = np.array([100.0, 101.0, 102.0, 99.0, 95.0, 92.0, 96.0, 104.0], dtype=np.float64)
    ts = [f"t{i}" for i in range(len(balances))]
    out = underwater_curve_with_timestamps(ts, balances)
    assert len(out) == len(balances)
    # First three bars are at or above peak → drawdownPct should be 0.00
    assert out[0]["drawdownPct"] == "0.00"
    assert out[1]["drawdownPct"] == "0.00"
    # Bar 5 (index 5, balance 92) is deepest drawdown from peak 102
    assert float(out[5]["drawdownPct"]) < -9.0
    # Last bar returns to 104 > peak 102 → 0.00
    assert out[-1]["drawdownPct"] == "0.00"
    # All entries carry timestamps
    assert all("timestamp" in e for e in out)


def test_underwater_curve_empty_balances():
    out = underwater_curve_with_timestamps([], np.array([]))
    assert out == []


# ── A-010 returns histogram + MFE/MAE scatter ──────────────────────────────

def test_returns_histogram_with_trades():
    trades = [
        {"pnl": "-200.0"},   # -2%
        {"pnl": "-75.0"},    # -0.75%
        {"pnl": "10.0"},     # +0.1%
        {"pnl": "350.0"},    # +3.5%
        {"pnl": "700.0"},    # +7%
    ]
    out = returns_histogram(trades, capital=10000.0)
    # 11 buckets by default
    assert len(out) == 11
    total = sum(b["count"] for b in out)
    assert total == 5
    # All counts should sum back to len(trades)
    bucket_with_pnl = max(out, key=lambda b: b["count"])
    assert bucket_with_pnl["count"] >= 1


def test_returns_histogram_empty_trades():
    out = returns_histogram([], capital=10000.0)
    # Empty input → all buckets present with count=0
    assert len(out) == 11
    assert all(b["count"] == 0 for b in out)


def test_mfe_mae_scatter_basic():
    trades = [
        {"pnl": "100.0", "_mfe": 50.0, "_mae": -25.0, "entryPrice": "1000", "exitReason": "tp"},
        {"pnl": "-50.0", "_mfe": 10.0, "_mae": -60.0, "entryPrice": "1000", "exitReason": "sl"},
    ]
    out = mfe_mae_scatter(trades, capital=10000.0)
    assert len(out) == 2
    # MFE/MAE are percentages of entry price
    # Trade 1: mfe = 50/1000 = 5%, mae = 25/1000 = 2.5%
    assert out[0]["mfePct"] == "5.00"
    assert out[0]["maePct"] == "2.50"
    assert out[0]["exitReason"] == "tp"
    # Trade 2: mfe = 10/1000 = 1%, mae = 60/1000 = 6%
    assert out[1]["mfePct"] == "1.00"
    assert out[1]["maePct"] == "6.00"


# ── A-011 rolling Sharpe / volatility ────────────────────────────────────────

def test_rolling_curve_basic():
    # Steady uptrend → positive Sharpe after window fills
    n = 100
    balances = np.linspace(10000.0, 12000.0, n)
    out = rolling_curve(balances, timeframe_seconds=3600.0, annual_factor=24*365, window_candles=20)
    assert len(out) > 0
    # Steady positive returns → Sharpe positive after warmup
    last = float(out[-1]["sharpe"])
    assert last > 0
    # Volatility should be small (constant return series)
    assert float(out[-1]["volatility"]) >= 0


def test_rolling_curve_handles_constant_balances():
    balances = np.full(100, 10000.0)
    out = rolling_curve(balances, timeframe_seconds=3600.0, annual_factor=24*365, window_candles=10)
    # All returns are 0 → Sharpe = 0, vol = 0
    assert all(e["sharpe"] == "0.00" for e in out)
    assert all(e["volatility"] == "0.0000" for e in out)


def test_rolling_curve_too_short_returns_empty():
    out = rolling_curve(np.array([10000.0]), timeframe_seconds=3600.0, annual_factor=24*365)
    assert out == []


# ── Timeframe helper ─────────────────────────────────────────────────────────

def test_timeframe_to_seconds_basic():
    assert timeframe_to_seconds("1m") == 60
    assert timeframe_to_seconds("1h") == 3600
    assert timeframe_to_seconds("1d") == 86400
    assert timeframe_to_seconds("1w") == 604800
    # Default for unknown
    assert timeframe_to_seconds("unknown") == 3600