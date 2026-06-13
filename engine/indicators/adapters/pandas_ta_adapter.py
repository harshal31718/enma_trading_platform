"""pandas-ta implementation of :class:`IndicatorProvider` — a pure-Python
fallback for environments where the TA-Lib C library is unavailable.

Selected via ``ENMA_INDICATOR_LIBRARY=pandas_ta`` or automatically when TA-Lib
fails to import (see ``config.py``). pandas-ta is an *optional* dependency: it
is imported guarded so that merely importing this module never requires it —
construction raises :class:`ImportError` when it is missing.

Numeric note: pandas-ta and TA-Lib agree to within rounding for most
indicators, but their smoothing conventions differ slightly for a few (e.g.
ATR/ADX seeding). Treat this backend as a functional fallback, not a
bit-for-bit replacement — see DECISIONS.md #12.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import CLOSE, HIGH, LOW, OPEN, VOLUME, IndicatorProvider

try:  # Optional dependency — and pandas-ta has historically fragile imports.
    import pandas_ta_classic as _pta  # noqa: F401  (registers the DataFrame `.ta` accessor)
except Exception:  # pragma: no cover - e.g. numpy-version incompatibilities
    _pta = None


def _frame(candles: np.ndarray) -> pd.DataFrame:
    """Build the lower-cased OHLCV DataFrame pandas-ta expects from the engine's
    ``[ts, open, close, high, low, volume]`` candle array."""
    return pd.DataFrame(
        {
            "open": candles[:, OPEN].astype(float),
            "high": candles[:, HIGH].astype(float),
            "low": candles[:, LOW].astype(float),
            "close": candles[:, CLOSE].astype(float),
            "volume": candles[:, VOLUME].astype(float),
        }
    )


def _out(series, sequential: bool):
    arr = np.asarray(series, dtype=float)
    return arr if sequential else float(arr[-1])


def _triple(col_a, col_b, col_c, sequential: bool):
    if sequential:
        return (
            np.asarray(col_a, dtype=float),
            np.asarray(col_b, dtype=float),
            np.asarray(col_c, dtype=float),
        )
    return float(col_a.iloc[-1]), float(col_b.iloc[-1]), float(col_c.iloc[-1])


class PandasTaIndicatorProvider(IndicatorProvider):
    name = "pandas-ta"

    def __init__(self) -> None:
        if _pta is None:
            raise ImportError(
                "pandas-ta-classic is not installed (or failed to import). Run "
                "`pip install pandas-ta-classic`, or use the default TA-Lib backend "
                "(ENMA_INDICATOR_LIBRARY=talib)."
            )

    def ema(self, candles, period=9, sequential=False):
        return _out(_frame(candles).ta.ema(length=period), sequential)

    def sma(self, candles, period=20, sequential=False):
        return _out(_frame(candles).ta.sma(length=period), sequential)

    def rsi(self, candles, period=14, sequential=False):
        return _out(_frame(candles).ta.rsi(length=period), sequential)

    def atr(self, candles, period=14, sequential=False):
        return _out(_frame(candles).ta.atr(length=period), sequential)

    def donchian(self, candles, period=20, sequential=False):
        # Columns returned in order: lower (DCL), middle (DCM), upper (DCU).
        df = _frame(candles).ta.donchian(lower_length=period, upper_length=period)
        lower, middle, upper = df.iloc[:, 0], df.iloc[:, 1], df.iloc[:, 2]
        return _triple(upper, middle, lower, sequential)

    def macd(self, candles, fast=12, slow=26, signal=9, sequential=False):
        # Columns: MACD (line), MACDh (histogram), MACDs (signal).
        df = _frame(candles).ta.macd(fast=fast, slow=slow, signal=signal)
        line, hist, sig = df.iloc[:, 0], df.iloc[:, 1], df.iloc[:, 2]
        return _triple(line, sig, hist, sequential)

    def bollinger_bands(self, candles, period=20, std=2.0, sequential=False):
        # Columns: BBL (lower), BBM (middle), BBU (upper), BBB, BBP.
        df = _frame(candles).ta.bbands(length=period, std=std)
        lower, middle, upper = df.iloc[:, 0], df.iloc[:, 1], df.iloc[:, 2]
        return _triple(upper, middle, lower, sequential)

    def adx(self, candles, period=14, sequential=False):
        # Columns: ADX, DMP (+DI), DMN (−DI) — we expose ADX only, like TA-Lib.
        df = _frame(candles).ta.adx(length=period)
        return _out(df.iloc[:, 0], sequential)

    def stochastic(self, candles, period=14, smooth_k=3, smooth_d=3, sequential=False):
        # Columns: STOCHk (%K), STOCHd (%D).
        df = _frame(candles).ta.stoch(k=period, d=smooth_d, smooth_k=smooth_k)
        k, d = df.iloc[:, 0], df.iloc[:, 1]
        if sequential:
            return np.asarray(k, dtype=float), np.asarray(d, dtype=float)
        return float(k.iloc[-1]), float(d.iloc[-1])
