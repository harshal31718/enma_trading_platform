"""Selects which :class:`IndicatorProvider` backs the engine's indicators.

Default is TA-Lib. Override with the ``ENMA_INDICATOR_LIBRARY`` env var
(``talib`` | ``pandas_ta``). If the chosen backend can't be loaded and
``ENMA_INDICATOR_FALLBACK`` is truthy (the default), the other backend is
tried — so a host missing the TA-Lib C library degrades to pandas-ta instead
of crashing the engine.
"""

from __future__ import annotations

import logging
import os
from enum import Enum

from .adapters import PandasTaIndicatorProvider, TalibIndicatorProvider
from .base import IndicatorProvider

logger = logging.getLogger(__name__)


class IndicatorLibrary(str, Enum):
    TALIB = "talib"
    PANDAS_TA = "pandas_ta"


_BUILDERS = {
    IndicatorLibrary.TALIB: TalibIndicatorProvider,
    IndicatorLibrary.PANDAS_TA: PandasTaIndicatorProvider,
}


def _configured_library() -> IndicatorLibrary:
    raw = os.getenv("ENMA_INDICATOR_LIBRARY", IndicatorLibrary.TALIB.value).strip().lower()
    try:
        return IndicatorLibrary(raw)
    except ValueError:
        logger.warning(
            "Unknown ENMA_INDICATOR_LIBRARY=%r; using %s.", raw, IndicatorLibrary.TALIB.value
        )
        return IndicatorLibrary.TALIB


def _fallback_enabled() -> bool:
    return os.getenv("ENMA_INDICATOR_FALLBACK", "true").strip().lower() in ("1", "true", "yes", "on")


def get_indicator_provider() -> IndicatorProvider:
    """Build the configured indicator provider, with optional auto-fallback."""
    primary = _configured_library()
    try:
        return _BUILDERS[primary]()
    except ImportError as exc:
        if not _fallback_enabled():
            raise
        secondary = (
            IndicatorLibrary.PANDAS_TA
            if primary == IndicatorLibrary.TALIB
            else IndicatorLibrary.TALIB
        )
        logger.warning(
            "Indicator backend '%s' unavailable (%s); falling back to '%s'.",
            primary.value, exc, secondary.value,
        )
        try:
            return _BUILDERS[secondary]()
        except ImportError as exc2:
            raise RuntimeError(
                "No indicator backend available: neither TA-Lib nor pandas-ta-classic "
                "could be loaded. Install one (TA-Lib is built in the engine "
                "Docker image; `pip install pandas-ta-classic` provides the fallback)."
            ) from exc2
