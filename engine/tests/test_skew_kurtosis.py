"""SkewnessStat/KurtosisStat tests (Plan 10 Phase 3e — feeds DSR).

Hand-computed expected values for small arrays so a wiring mistake (e.g.
excess vs raw kurtosis, sample vs population std) is caught immediately
rather than only showing up downstream in a DSR number nobody can eyeball.
"""
import numpy as np
import pytest

from services.metrics import KurtosisStat, MetricContext, SkewnessStat

_YEAR_MS = 365.25 * 24 * 3600 * 1000.0


def _ctx(trades):
    balances = np.array([1000.0], dtype=np.float64)
    candles_np = np.array([[0.0, 100.0, 100.0, 100.0, 100.0, 100.0]], dtype=np.float64)
    return MetricContext(
        trades=trades,
        balances=balances,
        equity_timestamps=[""],
        candles_np=candles_np,
        capital=1000.0,
        timeframe="1d",
        annual_factor=365.0,
        warmup_period=0,
        total_fees=0.0,
        total_funding=0.0,
        liquidations=0,
        leverage=1,
    )


def _trade(pnl):
    return {"pnl": str(pnl)}


def test_skewness_zero_for_symmetric_pnls():
    trades = [_trade(p) for p in (-10, -5, 0, 5, 10)]
    assert float(SkewnessStat().compute(_ctx(trades))) == pytest.approx(0.0, abs=1e-6)


def test_skewness_positive_for_right_tailed_pnls():
    # A few small losses, one huge win — classic positive-skew trade profile.
    trades = [_trade(p) for p in (-1, -1, -1, -1, 20)]
    skew = float(SkewnessStat().compute(_ctx(trades)))
    assert skew > 0


def test_skewness_negative_for_left_tailed_pnls():
    trades = [_trade(p) for p in (1, 1, 1, 1, -20)]
    skew = float(SkewnessStat().compute(_ctx(trades)))
    assert skew < 0


def test_skewness_zero_below_min_trade_count():
    assert SkewnessStat().compute(_ctx([_trade(1), _trade(2)])) == "0.00"


def test_skewness_zero_when_all_pnls_identical():
    trades = [_trade(5) for _ in range(5)]
    assert SkewnessStat().compute(_ctx(trades)) == "0.00"


def test_kurtosis_normal_default_below_min_trade_count():
    # 3.0 (not 0.0) is the "no information" default — matches the raw-kurtosis
    # convention this stat uses (normal distribution => kurtosis == 3).
    assert KurtosisStat().compute(_ctx([_trade(1), _trade(2), _trade(3)])) == "3.00"


def test_kurtosis_uniform_pnls_below_normal():
    # A uniform-ish spread has lower kurtosis (thinner tails) than normal.
    trades = [_trade(p) for p in (-2, -1, 0, 1, 2)]
    kurt = float(KurtosisStat().compute(_ctx(trades)))
    assert kurt < 3.0


def test_kurtosis_fat_tailed_pnls_above_normal():
    # Mostly near-zero with rare huge outliers -> heavy tails -> kurtosis > 3.
    trades = [_trade(p) for p in (0.1, -0.1, 0.05, -0.05, 0.1, -0.1, 50, -50)]
    kurt = float(KurtosisStat().compute(_ctx(trades)))
    assert kurt > 3.0


def test_kurtosis_hand_computed_known_array():
    # pnls = [-3,-1,1,3]; mean=0, population std = sqrt((9+1+1+9)/4) = sqrt(5)
    # raw kurtosis = mean((x/std)^4) = mean([81,1,1,81]/25) = mean([3.24,0.04,0.04,3.24]) = 1.64
    trades = [_trade(p) for p in (-3, -1, 1, 3)]
    kurt = float(KurtosisStat().compute(_ctx(trades)))
    assert kurt == pytest.approx(1.64, abs=1e-3)
