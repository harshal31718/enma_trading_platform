# EMA — Exponential Moving Average

**Function:** `ta.ema(candles, period=9, sequential=False)`  
**Returns:** `float` (latest) | `np.ndarray` (sequential)  
**Input:** Close price  
**Backend:** TA-Lib (`EMA`), pandas-ta (`ema`)

## Description

Exponential moving average of the close price. Applies exponentially decreasing weights
so recent prices have more influence than older ones. Common use: trend direction and crossover signals.

## Parameters

| Param | Default | Range | Notes |
|-------|---------|-------|-------|
| `period` | 9 | 2+ | Lookback window. Larger = smoother, more lag. |
| `sequential` | False | — | `True` returns the full NaN-padded series. |

## Usage in Strategies

| Strategy | Usage |
|----------|-------|
| `MicroScalper` | Fast(9)/Slow(21) crossover, flip_position SAR |
| `AdaptiveTrend` | Trend EMA(200) regime + Fast(21)/Slow(55) trigger |
| `MicroMacroRSIDivergence` | Smoothed-RSI confirmation via synthetic candle trick |

## Notes

- `MicroMacroRSIDivergence` feeds the RSI series into a synthetic candle array and calls
  `ta.ema` on it to get a smoothed RSI — this is the only non-close use of `ema`.
- Do not confuse with `sma` — `ema` is more reactive to recent price changes.
