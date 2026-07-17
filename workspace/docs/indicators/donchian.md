# Donchian — Donchian Channel

**Function:** `ta.donchian(candles, period=20, sequential=False)`  
**Returns:** `(upper, middle, lower)` — floats or `(ndarray, ndarray, ndarray)`  
**Input:** High (upper), Low (lower), Middle = (upper+lower)/2  
**Backend:** TA-Lib (`MAX`/`MIN`), pandas-ta

## Description

Plots the highest high and lowest low over the last `period` bars. The middle band
is the arithmetic midpoint. Classic breakout indicator: price breaking above upper band
signals bullish momentum; below lower band signals bearish.

## Parameters

| Param | Default | Range | Notes |
|-------|---------|-------|-------|
| `period` | 20 | 5–100 | Lookback. Larger = wider channel, fewer breakouts. |
| `sequential` | False | — | `True` returns tuple of three ndarrays. |

## Return Values

- `upper`: Highest high over `period` bars  
- `middle`: `(upper + lower) / 2`  
- `lower`: Lowest low over `period` bars

## Usage in Strategies

Not used by any current strategy. (`DonchianBreakout` was removed 2026-06-14 — see `workspace/docs/state/DEPRECATED.md`.)

## Notes

- Classic usage: entry on break above `upper` (long) or below `lower` (short); exit when price returns to `middle`.
- To avoid lookahead, call `ta.donchian(self.candles[:-1], ...)` using the **previous-bar** channel.
- Bollinger Bands cover a related concept (volatility-adjusted bands) but have different semantics.
