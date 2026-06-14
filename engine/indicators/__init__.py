"""Pluggable technical-indicator layer for the Enma engine.

Public API is unchanged from the original flat module — strategies keep doing::

    import engine.indicators as ta
    fast = ta.ema(self.candles, period=9)
    atr_series = ta.atr(self.candles, period=14, sequential=True)

Underneath, every call now routes through a swappable
:class:`IndicatorProvider`: TA-Lib by default, pandas-ta as a drop-in fallback.
Switch backends with the ``ENMA_INDICATOR_LIBRARY`` env var (see ``config.py``);
no strategy code changes. Add an indicator by declaring it on
``IndicatorProvider`` (``base.py``) and implementing it in both adapters.
"""

from .adapters import PandasTaIndicatorProvider, TalibIndicatorProvider
from .base import (
    IndicatorProvider,
    adx,
    atr,
    bollinger_bands,
    donchian,
    ema,
    get_indicators,
    macd,
    mfi,
    obv,
    pivot_high,
    pivot_low,
    rsi,
    set_indicator_provider,
    sma,
    stochastic,
)
from .config import IndicatorLibrary, get_indicator_provider

# Eagerly install the configured backend so the first indicator call has a
# provider ready and any misconfiguration fails at startup — not mid-backtest.
# Idempotent: get_indicators() also lazy-initialises if this is ever skipped.
set_indicator_provider(get_indicator_provider())

__all__ = [
    # Provider framework
    "IndicatorProvider",
    "TalibIndicatorProvider",
    "PandasTaIndicatorProvider",
    "IndicatorLibrary",
    "set_indicator_provider",
    "get_indicators",
    "get_indicator_provider",
    # Convenience functions (stable public API)
    "ema",
    "sma",
    "rsi",
    "atr",
    "donchian",
    "macd",
    "bollinger_bands",
    "adx",
    "stochastic",
    "mfi",
    "obv",
    "pivot_high",
    "pivot_low",
]
