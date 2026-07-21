"""Single source of truth for the engine's candle-array column layout.

Every candle/OHLCV numpy array in this codebase uses the nonstandard layout
``[timestamp, open, close, high, low, volume]`` — note *close* precedes
*high*/*low* (Jesse-style), unlike Binance's own kline order
(``[ts, open, high, low, close, volume, ...]``) or the TimescaleDB `candles`
schema (`open, high, low, close, volume`). Every fetcher/consumer must import
these constants instead of hardcoding the column index — a copy-pasted
literal is exactly how a remap mistake stays silent (Plan 8 Step 8.4, ENG-15).

`engine/indicators/base.py` re-exports these under the same names for
backward compatibility with existing `from ..base import OPEN, CLOSE, ...`
imports inside the indicator adapters — this module is the canonical
definition, not a duplicate.
"""

import numpy as np

TIMESTAMP, OPEN, CLOSE, HIGH, LOW, VOLUME = 0, 1, 2, 3, 4, 5
NUM_COLUMNS = 6


def build_candle_array(timestamps, opens, highs, lows, closes, volumes) -> np.ndarray:
    """Stack six named OHLCV sequences into the engine's canonical candle
    array shape/order. A single shared builder means a remap mistake breaks
    every caller's tests identically, instead of each fetcher independently
    hand-rolling its own `np.column_stack([...])` column order (Plan 8 Step
    8.4, ENG-15) — the args are named for open/high/low/close explicitly so
    the call site itself states the source order, not just the target order.
    """
    return np.column_stack([timestamps, opens, closes, highs, lows, volumes]).astype(np.float64)
