"""TA-Lib implementation of :class:`IndicatorProvider` — the engine default.

This is a faithful move of the engine's original flat indicator functions into
the pluggable-provider shape; behaviour (including ``sequential`` return values)
is unchanged. The two indicators the original module lacked — ``adx`` and
``stochastic`` — are added here to complete the interface.

TA-Lib is imported lazily/guarded so that merely importing this module never
fails: construction raises :class:`ImportError` when the C library is missing,
which the configuration factory catches to fall back to pandas-ta.
"""

from __future__ import annotations

import numpy as np
from ..base import CLOSE, HIGH, LOW, VOLUME, IndicatorProvider, pivots_from_candles

try:  # TA-Lib is the primary backend (built inside the engine Docker image).
    import talib as _talib
except ImportError:  # pragma: no cover - only on a host without the C library
    _talib = None


class TalibIndicatorProvider(IndicatorProvider):
    name = "TA-Lib"

    def __init__(self) -> None:
        if _talib is None:
            raise ImportError(
                "TA-Lib is not installed. It is built inside the engine Docker "
                "image (see engine/CLAUDE.md). Set ENMA_INDICATOR_LIBRARY=pandas_ta "
                "to use the pure-Python fallback instead."
            )

    def ema(self, candles, period=9, sequential=False):
        close = candles[:, CLOSE].astype(float)
        result = _talib.EMA(close, timeperiod=period)
        return result if sequential else float(result[-1])

    def sma(self, candles, period=20, sequential=False):
        close = candles[:, CLOSE].astype(float)
        try:
            result = _talib.SMA(close, timeperiod=period)
        except Exception:
            # Return NaNs when period is larger than data length or other errors
            if sequential:
                return np.full(close.shape, np.nan, dtype=float)
            return np.nan
        return result if sequential else float(result[-1])

    def rsi(self, candles, period=14, sequential=False):
        close = candles[:, CLOSE].astype(float)
        result = _talib.RSI(close, timeperiod=period)
        return result if sequential else float(result[-1])

    def atr(self, candles, period=14, sequential=False):
        high = candles[:, HIGH].astype(float)
        low = candles[:, LOW].astype(float)
        close = candles[:, CLOSE].astype(float)
        result = _talib.ATR(high, low, close, timeperiod=period)
        return result if sequential else float(result[-1])

    def donchian(self, candles, period=20, sequential=False):
        high = candles[:, HIGH].astype(float)
        low = candles[:, LOW].astype(float)
        upper = _talib.MAX(high, timeperiod=period)
        lower = _talib.MIN(low, timeperiod=period)
        middle = (upper + lower) / 2
        if sequential:
            return upper, middle, lower
        return float(upper[-1]), float(middle[-1]), float(lower[-1])

    def macd(self, candles, fast=12, slow=26, signal=9, sequential=False):
        close = candles[:, CLOSE].astype(float)
        macd_line, signal_line, histogram = _talib.MACD(
            close, fastperiod=fast, slowperiod=slow, signalperiod=signal
        )
        if sequential:
            return macd_line, signal_line, histogram
        return float(macd_line[-1]), float(signal_line[-1]), float(histogram[-1])

    def bollinger_bands(self, candles, period=20, std=2.0, sequential=False):
        close = candles[:, CLOSE].astype(float)
        upper, middle, lower = _talib.BBANDS(
            close, timeperiod=period, nbdevup=std, nbdevdn=std
        )
        if sequential:
            return upper, middle, lower
        return float(upper[-1]), float(middle[-1]), float(lower[-1])

    def adx(self, candles, period=14, sequential=False):
        high = candles[:, HIGH].astype(float)
        low = candles[:, LOW].astype(float)
        close = candles[:, CLOSE].astype(float)
        result = _talib.ADX(high, low, close, timeperiod=period)
        return result if sequential else float(result[-1])

    def stochastic(self, candles, period=14, smooth_k=3, smooth_d=3, sequential=False):
        high = candles[:, HIGH].astype(float)
        low = candles[:, LOW].astype(float)
        close = candles[:, CLOSE].astype(float)
        k, d = _talib.STOCH(
            high, low, close,
            fastk_period=period, slowk_period=smooth_k, slowd_period=smooth_d,
        )
        if sequential:
            return k, d
        return float(k[-1]), float(d[-1])

    # Pivots are pure price geometry (no TA-Lib equivalent), so both backends
    # delegate to the shared helper — see engine/indicators/base.py.
    def pivot_high(self, candles, left=10, right=10, source="high", sequential=False):
        return pivots_from_candles(candles, left, right, source, True, sequential)

    def pivot_low(self, candles, left=10, right=10, source="low", sequential=False):
        return pivots_from_candles(candles, left, right, source, False, sequential)

    def mfi(self, candles, period=14, sequential=False):
        high = candles[:, HIGH].astype(float)
        low = candles[:, LOW].astype(float)
        close = candles[:, CLOSE].astype(float)
        volume = candles[:, VOLUME].astype(float)
        result = _talib.MFI(high, low, close, volume, timeperiod=period)
        return result if sequential else float(result[-1])

    def obv(self, candles, sequential=False):
        close = candles[:, CLOSE].astype(float)
        volume = candles[:, VOLUME].astype(float)
        result = _talib.OBV(close, volume)
        return result if sequential else float(result[-1])
