# Stochastic Oscillator

**Function:** `ta.stochastic(candles, period=14, smooth_k=3, smooth_d=3, sequential=False)`  
**Returns:** `(%K, %D)` — (float, float) or (ndarray, ndarray)  
**Input:** High, Low, Close  
**Backend:** TA-Lib (`STOCH`), pandas-ta (`stoch`)

## Description

Momentum oscillator comparing a close to its high-low range over `period` bars.
`%K` is the raw stochastic; `%D` is a smoothed version. Values above 80 = overbought;
below 20 = oversold. Crossovers between %K and %D are classic entry signals.

## Parameters

| Param | Default | Range | Notes |
|-------|---------|-------|-------|
| `period` | 14 | 2–50 | Lookback for high-low range. |
| `smooth_k` | 3 | 1–10 | Smoothing of %K (slow stochastic). |
| `smooth_d` | 3 | 1–10 | Smoothing of %D (signal line). |
| `sequential` | False | — | `True` returns tuple of two ndarrays. |

## Return Values

- `%K`: Smoothed stochastic (0–100)
- `%D`: Signal line — smoothed %K (0–100)

## Usage in Strategies

| Strategy | Usage |
|----------|-------|
| `MultiDivergence` | `%K` series is one of 9 divergence sources; `_compute_pivots` runs on `%K` |

## Notes

- `MultiDivergence` uses only `%K` (the first element of the tuple) for divergence detection.
- The Pine source uses `ta.stoch(close, high, low, 14)` — equivalent to `smooth_k=1` (raw %K
  before smoothing). The Python strategy uses default `smooth_k=3` (slow stochastic).
- TA-Lib backend: `STOCH(high, low, close, fastk_period=period, slowk_period=smooth_k, slowd_period=smooth_d)`.
