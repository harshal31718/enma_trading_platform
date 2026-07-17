# SMA — Simple Moving Average

**Function:** `ta.sma(candles, period=20, sequential=False)`  
**Returns:** `float` (latest) | `np.ndarray` (sequential)  
**Input:** Close price  
**Backend:** TA-Lib (`SMA`), pandas-ta (`sma`)

## Description

Arithmetic mean of the last `period` closes. Each bar has equal weight.
Slower to react than EMA but less noisy for longer-term trend assessment.

## Parameters

| Param | Default | Range | Notes |
|-------|---------|-------|-------|
| `period` | 20 | 2+ | Lookback window. |
| `sequential` | False | — | `True` returns the full NaN-padded series. |

## Usage in Strategies

| Strategy | Usage |
|----------|-------|
| `BestSupertrend` | Fast SMA(7) / Slow SMA(20) crossover for entry and exit |
| `MicroMacroRSIDivergence` | Optional smoothed-RSI layer via `smooth_type=0` (SMA of RSI) |
| `MultiDivergence` | Z-Score denominator: `mean = SMA(close, z_period)` (via `_zscore_series`) |

## Notes

- `BestSupertrend` uses `ta.sma` with `sequential=True` to scan history for the most
  recent crossover event.
- The Z-Score in `MultiDivergence` computes rolling mean/stdev in pure numpy rather than
  calling `ta.sma` — it does not go through the indicator layer.
