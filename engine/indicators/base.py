"""
Abstract indicator interface for the Enma engine.

Strategies never import a concrete indicator library (TA-Lib, pandas-ta, …).
They use the convenience functions re-exported from ``engine.indicators``
(``ta.ema(self.candles, period=…)``, ``ta.atr(...)``, …), which delegate to
whichever :class:`IndicatorProvider` is currently active. Swapping the backing
library is a single configuration change (see ``engine/indicators/config.py``)
and requires **no** strategy-code changes.

Candle format
-------------
Every method takes ``candles`` as the engine's native OHLCV numpy array, whose
columns are ``[timestamp, open, close, high, low, volume]`` — note that *close*
precedes *high*/*low*, matching the Jesse-style layout used throughout the
engine — and a ``sequential`` flag:

* ``sequential=False`` (default) → the latest value as a ``float`` (or a tuple
  of floats for multi-line indicators such as MACD or Bollinger Bands).
* ``sequential=True`` → the full ``numpy.ndarray`` series (or a tuple of
  arrays), NaN-padded at the front exactly as the underlying library returns it.

Column indices are named here once so adapters never hardcode them.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional, Tuple, Union

import numpy as np

logger = logging.getLogger(__name__)

# Column layout of the engine's candle array: [ts, open, close, high, low, vol].
OPEN, CLOSE, HIGH, LOW, VOLUME = 1, 2, 3, 4, 5

# Return types: a latest scalar OR the full series — single / pair / triple.
Single = Union[float, np.ndarray]
Pair = Union[Tuple[float, float], Tuple[np.ndarray, np.ndarray]]
Triple = Union[
    Tuple[float, float, float],
    Tuple[np.ndarray, np.ndarray, np.ndarray],
]


class IndicatorProvider(ABC):
    """Contract every indicator backend implements.

    Concrete providers (``TalibIndicatorProvider``, ``PandasTaIndicatorProvider``)
    translate these calls into their underlying library while honouring the
    engine's candle layout and ``sequential`` semantics.
    """

    #: Human-readable backend name, surfaced in logs.
    name: str = "abstract"

    @abstractmethod
    def ema(self, candles: np.ndarray, period: int = 9, sequential: bool = False) -> Single:
        """Exponential Moving Average of close."""
        raise NotImplementedError

    @abstractmethod
    def sma(self, candles: np.ndarray, period: int = 20, sequential: bool = False) -> Single:
        """Simple Moving Average of close."""
        raise NotImplementedError

    @abstractmethod
    def rsi(self, candles: np.ndarray, period: int = 14, sequential: bool = False) -> Single:
        """Relative Strength Index."""
        raise NotImplementedError

    @abstractmethod
    def atr(self, candles: np.ndarray, period: int = 14, sequential: bool = False) -> Single:
        """Average True Range."""
        raise NotImplementedError

    @abstractmethod
    def donchian(self, candles: np.ndarray, period: int = 20, sequential: bool = False) -> Triple:
        """Donchian channel → ``(upper, middle, lower)``."""
        raise NotImplementedError

    @abstractmethod
    def macd(self, candles: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9,
             sequential: bool = False) -> Triple:
        """MACD → ``(macd_line, signal_line, histogram)``."""
        raise NotImplementedError

    @abstractmethod
    def bollinger_bands(self, candles: np.ndarray, period: int = 20, std: float = 2.0,
                        sequential: bool = False) -> Triple:
        """Bollinger Bands → ``(upper, middle, lower)``."""
        raise NotImplementedError

    @abstractmethod
    def adx(self, candles: np.ndarray, period: int = 14, sequential: bool = False) -> Single:
        """Average Directional Index (trend strength, 0–100)."""
        raise NotImplementedError

    @abstractmethod
    def stochastic(self, candles: np.ndarray, period: int = 14, smooth_k: int = 3,
                   smooth_d: int = 3, sequential: bool = False) -> Pair:
        """Stochastic oscillator → ``(%K, %D)``."""
        raise NotImplementedError


# ──────────────────────────────────────────────────────────────────────────
# Active-provider singleton + convenience functions
# ──────────────────────────────────────────────────────────────────────────

_provider: Optional[IndicatorProvider] = None


def set_indicator_provider(provider: IndicatorProvider) -> None:
    """Install ``provider`` as the active indicator backend.

    Called once at startup, and swappable at runtime (handy for tests that
    compare backends)."""
    global _provider
    _provider = provider
    logger.info("Indicator provider set to: %s", getattr(provider, "name", type(provider).__name__))


def get_indicators() -> IndicatorProvider:
    """Return the active provider, lazily initialising the configured default on
    first use so a bare ``import engine.indicators as ta; ta.ema(...)`` works
    without any explicit setup."""
    global _provider
    if _provider is None:
        from .config import get_indicator_provider
        set_indicator_provider(get_indicator_provider())
    return _provider  # type: ignore[return-value]


# Module-level convenience functions — the engine's stable public API. Their
# signatures are intentionally identical to the original flat module so every
# existing ``ta.<name>(...)`` call site keeps working unchanged.

def ema(candles: np.ndarray, period: int = 9, sequential: bool = False) -> Single:
    return get_indicators().ema(candles, period, sequential)


def sma(candles: np.ndarray, period: int = 20, sequential: bool = False) -> Single:
    return get_indicators().sma(candles, period, sequential)


def rsi(candles: np.ndarray, period: int = 14, sequential: bool = False) -> Single:
    return get_indicators().rsi(candles, period, sequential)


def atr(candles: np.ndarray, period: int = 14, sequential: bool = False) -> Single:
    return get_indicators().atr(candles, period, sequential)


def donchian(candles: np.ndarray, period: int = 20, sequential: bool = False) -> Triple:
    return get_indicators().donchian(candles, period, sequential)


def macd(candles: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9,
         sequential: bool = False) -> Triple:
    return get_indicators().macd(candles, fast, slow, signal, sequential)


def bollinger_bands(candles: np.ndarray, period: int = 20, std: float = 2.0,
                    sequential: bool = False) -> Triple:
    return get_indicators().bollinger_bands(candles, period, std, sequential)


def adx(candles: np.ndarray, period: int = 14, sequential: bool = False) -> Single:
    return get_indicators().adx(candles, period, sequential)


def stochastic(candles: np.ndarray, period: int = 14, smooth_k: int = 3, smooth_d: int = 3,
               sequential: bool = False) -> Pair:
    return get_indicators().stochastic(candles, period, smooth_k, smooth_d, sequential)
