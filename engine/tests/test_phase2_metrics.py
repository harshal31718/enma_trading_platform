"""Tests for Phase 2 metric registry (A-007 / A-008 / A-012).

Pure-function tests of every statistic class plus a registry integration test.
"""
import math
import numpy as np
import pytest
from datetime import datetime, timezone, timedelta
from services.metrics import (
    MetricContext,
    Statistic,
    default_registry,
    # Individual stats for targeted tests
    CAGRStat,
    SQNStat,
    ExpectancyRatioStat,
    MaxDrawdownDurationStat,
    ByExitReasonStat,
    WinRateStat,
    ProfitFactorStat,
    CalmarStat,
)


def _mk_ctx(trades=None, balances=None, **kw):
    """Tiny context factory — defaults make most stats return a defined value."""
    n = kw.pop("n_bars", 100)
    if balances is None:
        balances = np.linspace(10000.0, 11000.0, n)
    if trades is None:
        trades = [
            {"pnl": "100.0", "exitReason": "take_profit", "_entry_dt": datetime(2024,1,1, tzinfo=timezone.utc), "_exit_dt": datetime(2024,1,2, tzinfo=timezone.utc)},
            {"pnl": "-50.0", "exitReason": "stop_loss", "_entry_dt": datetime(2024,1,3, tzinfo=timezone.utc), "_exit_dt": datetime(2024,1,4, tzinfo=timezone.utc)},
        ]
    candles = np.zeros((n, 6))
    candles[:, 2] = np.linspace(100.0, 110.0, n)   # close
    candles[:, 3] = candles[:, 2] + 1.0              # high
    candles[:, 4] = candles[:, 2] - 1.0              # low
    candles[:, 0] = np.linspace(0, 1e9, n)           # timestamp_ms
    candles[-1, 0] = 1e9 + (365 * 24 * 3600 * 1000)  # 1 year span
    return MetricContext(
        trades=trades,
        balances=balances,
        equity_timestamps=["t"] * n,
        candles_np=candles,
        capital=10000.0,
        timeframe="1h",
        annual_factor=24 * 365,
        warmup_period=0,
        total_fees=10.0,
        total_funding=0.0,
        liquidations=0,
        leverage=3,
    )


# ── A-007 new metric tests ──────────────────────────────────────────────────

def test_cagr_annualised_return():
    # equity doubles in 1 year → CAGR ≈ 100%
    ctx = _mk_ctx(balances=np.linspace(10000.0, 20000.0, 100))
    out = CAGRStat().compute(ctx)
    assert 95.0 < float(out) < 105.0


def test_cagr_handles_loss():
    ctx = _mk_ctx(balances=np.linspace(10000.0, 5000.0, 100))
    out = CAGRStat().compute(ctx)
    assert float(out) < 0


def test_sqn_van_tharp():
    # 4 trades: 3 wins of 100, 1 loss of 50
    trades = [{"pnl": "100.0"} for _ in range(3)] + [{"pnl": "-50.0"}]
    ctx = _mk_ctx(trades=trades)
    out = SQNStat().compute(ctx)
    # mean = 62.5, std (population) ≈ 64.95, N = 4
    # SQN = sqrt(4) * 62.5 / 64.95 ≈ 1.92
    assert 1.85 < float(out) < 2.0


def test_sqn_handles_no_trades():
    ctx = _mk_ctx(trades=[])
    out = SQNStat().compute(ctx)
    assert out == "0.00"


def test_expectancy_ratio_edge_per_unit_loss():
    # 5 wins of 100, 5 losses of 100 → zero edge
    trades = [{"pnl": "100.0"} for _ in range(5)] + [{"pnl": "-100.0"} for _ in range(5)]
    ctx = _mk_ctx(trades=trades)
    out = ExpectancyRatioStat().compute(ctx)
    assert float(out) == 0.00


def test_expectancy_ratio_positive_edge():
    # 7 wins of 100, 3 losses of 50 → edge exists
    trades = [{"pnl": "100.0"} for _ in range(7)] + [{"pnl": "-50.0"} for _ in range(3)]
    ctx = _mk_ctx(trades=trades)
    out = ExpectancyRatioStat().compute(ctx)
    assert float(out) > 0


def test_max_drawdown_duration_candles():
    # Drawdown from bar 30 to bar 60 (30 candles underwater)
    balances = np.array([100.0] * 30 + [90.0] * 30 + [100.0] * 30, dtype=np.float64)
    ctx = _mk_ctx(balances=balances)
    out = MaxDrawdownDurationStat().compute(ctx)
    assert out == 30


def test_max_drawdown_duration_no_drawdown():
    balances = np.array([100.0, 101.0, 102.0, 103.0], dtype=np.float64)
    ctx = _mk_ctx(balances=balances)
    out = MaxDrawdownDurationStat().compute(ctx)
    assert out == 0


# ── A-008 breakdown tables ──────────────────────────────────────────────────

def test_by_exit_reason_groups():
    trades = [
        {"pnl": "100.0", "exitReason": "take_profit"},
        {"pnl": "200.0", "exitReason": "take_profit"},
        {"pnl": "-50.0", "exitReason": "stop_loss"},
        {"pnl": "-30.0", "exitReason": "stop_loss"},
        {"pnl": "-100.0", "exitReason": "liquidation"},
    ]
    ctx = _mk_ctx(trades=trades)
    out = ByExitReasonStat().compute(ctx)
    assert "take_profit" in out
    assert "stop_loss" in out
    assert "liquidation" in out
    assert out["take_profit"]["totalTrades"] == 2
    assert out["take_profit"]["netProfit"] == "300.00"
    assert out["stop_loss"]["totalTrades"] == 2
    assert out["stop_loss"]["netProfit"] == "-80.00"
    assert out["liquidation"]["totalTrades"] == 1
    assert out["liquidation"]["netProfit"] == "-100.00"


# ── A-012 registry integration ──────────────────────────────────────────────

def test_registry_has_all_new_metrics():
    reg = default_registry()
    names = set(reg.names())
    for required in (
        "cagrPct", "sqn", "expectancyRatio",
        "maxDrawdownDurationCandles", "byExitReason",
    ):
        assert required in names, f"missing metric: {required}"


def test_registry_compute_all_returns_all_keys():
    ctx = _mk_ctx()
    out = default_registry().compute_all(ctx)
    assert "cagrPct" in out
    assert "sqn" in out
    assert "byExitReason" in out
    # Existing legacy keys also present
    assert "totalTrades" in out
    assert "sharpeRatio" in out


def test_registry_doesnt_crash_on_empty_trades():
    ctx = _mk_ctx(trades=[])
    out = default_registry().compute_all(ctx)
    # Every key should be present, no exception
    assert out["totalTrades"] == 0
    assert out["sqn"] == "0.00"
    assert out["byExitReason"] == {}