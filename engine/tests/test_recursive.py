"""Plan 17 (recursive-formula / warmup-insufficiency analysis) self-test.

`scripts/recursive.py`'s own verification gate: EMA(50) (recursive — seeded
from wherever its window starts) must show measurable drift at a small
warmup and converge by ~5x its period; SMA(50) (non-recursive — a pure
rolling window) must be exactly stable at any warmup >= its period. Uses the
real `engine.indicators` TA-Lib backend (available inside the container,
same as every other engine test) over synthetic sinusoidal+trend price data
— a straight line converges too fast to exercise the seed-bias this tool
targets, per the module docstring in `recursive.py`.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_recursive.py
"""
import numpy as np
import pytest

from scripts.recursive import analyze, _pct_change, _extract_indicator_columns


def _synthetic_candles(n: int = 3000) -> np.ndarray:
    """Sinusoidal + linear trend — enough non-linearity that a short EMA
    warmup seeds from a materially different local price level than the
    long-run converged value (a straight line converges too fast to see
    this, per real-world testing while building this tool)."""
    i = np.arange(n)
    price = 100.0 + 50.0 * np.sin(2 * np.pi * i / 300.0) + 0.01 * i
    return np.column_stack([
        i * 1000.0, price, price, price, price, np.ones(n),
    ]).astype(np.float64)


class _EmaSmaStrategy:
    """Minimal stand-in for BaseStrategy — only prepare() matters for
    scripts.recursive's generic column-discovery (any float ndarray on the
    instance whose length matches the window)."""

    def __init__(self):
        self.exchange = ""
        self.symbol = ""
        self.timeframe = ""
        self.is_backtesting = False
        self._ema50 = np.array([])
        self._sma50 = np.array([])

    def prepare(self, candles: np.ndarray) -> None:
        try:
            import engine.indicators as ta
        except ImportError:
            import indicators as ta
        self._ema50 = np.asarray(ta.ema(candles, period=50, sequential=True), dtype=float)
        self._sma50 = np.asarray(ta.sma(candles, period=50, sequential=True), dtype=float)


@pytest.fixture(scope="module")
def report():
    candles = _synthetic_candles()
    return analyze(_EmaSmaStrategy, {"exchange": "", "symbol": "", "timeframe": ""}, candles,
                    warmups=[60, 200, 250, 400, 500, 1000, 2000])


def test_ema_drifts_at_small_warmup(report):
    pct_at_60 = report["columns"]["_ema50"][60]
    assert pct_at_60 is not None
    assert abs(pct_at_60) > 1.0, "EMA(50) should show material drift at w=60 (seed bias not yet decayed)"


def test_ema_converges_by_five_times_period(report):
    pct_at_250 = report["columns"]["_ema50"][250]
    assert pct_at_250 is not None
    assert abs(pct_at_250) < 0.01, "EMA(50) should have converged to within 0.01% by w=250 (~5x period)"


def test_ema_fully_converged_at_live_rolling_window(report):
    pct_at_500 = report["columns"]["_ema50"][500]
    assert pct_at_500 is not None
    assert abs(pct_at_500) < 1e-4


def test_sma_stable_at_any_warmup_ge_period(report):
    for w in (60, 200, 250, 400, 500, 1000, 2000):
        pct = report["columns"]["_sma50"][w]
        assert pct is not None
        assert abs(pct) < 1e-6, f"SMA(50) should be exactly stable at w={w}, got {pct}%"


def test_pct_change_near_zero_baseline_guard():
    assert _pct_change(0.0, 5.0) is None
    assert _pct_change(1e-12, 5.0) is None


def test_pct_change_both_nan_is_none():
    assert _pct_change(float("nan"), float("nan")) is None


def test_pct_change_one_sided_nan_is_inf():
    assert _pct_change(1.0, float("nan")) == float("inf")
    assert _pct_change(float("nan"), 1.0) == float("inf")


def test_pct_change_normal_case():
    assert _pct_change(100.0, 110.0) == pytest.approx(10.0)
    assert _pct_change(100.0, 90.0) == pytest.approx(-10.0)


def test_extract_indicator_columns_excludes_wrong_shape_and_dtype():
    class _S:
        pass
    s = _S()
    s.candles = np.zeros((10, 6))          # wrong ndim -> excluded
    s._float_seq = np.zeros(10)            # correct -> included
    s._int_idx = np.arange(10)             # int dtype -> excluded
    s._bool_flags = np.zeros(10, dtype=bool)  # bool dtype -> excluded
    s._wrong_length = np.zeros(5)          # wrong length -> excluded
    cols = _extract_indicator_columns(s, 10)
    assert set(cols.keys()) == {"_float_seq"}


def test_warmup_larger_than_available_history_is_skipped():
    candles = _synthetic_candles(n=100)
    result = analyze(_EmaSmaStrategy, {"exchange": "", "symbol": "", "timeframe": ""}, candles,
                      warmups=[60, 500, 2000])
    assert 60 in result["columns"]["_ema50"]
    assert 500 not in result["columns"]["_ema50"]
    assert 2000 not in result["columns"]["_ema50"]
