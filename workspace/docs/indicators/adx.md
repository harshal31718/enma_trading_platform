# ADX — Average Directional Index

**Function:** `ta.adx(candles, period=14, sequential=False)`  
**Returns:** `float` (0–100, latest) | `np.ndarray` (sequential)  
**Input:** High, Low, Close  
**Backend:** TA-Lib (`ADX`), pandas-ta (`adx`)

## Description

Measures trend *strength* (not direction). Values above 25 indicate a trending market;
below 20 indicates a ranging/weak-trend market. ADX is always positive regardless of
whether the trend is up or down.

Note: TA-Lib's `ADX` returns only the ADX line (not +DI/-DI). The full `ADXR`, `+DI`, `-DI`
are not exposed in the indicator layer — if you need directional components, add `dmi` separately.

## Parameters

| Param | Default | Range | Notes |
|-------|---------|-------|-------|
| `period` | 14 | 5–50 | Lookback. Standard is 14. |
| `sequential` | False | — | `True` returns the full NaN-padded series. |

## Usage in Strategies

| Strategy | Usage |
|----------|-------|
| `MultiDivergence` | ADX series is one of 9 divergence sources; `_compute_pivots` runs on the ADX series |

## Notes

- ADX divergence (used by `MultiDivergence`) is unconventional — standard ADX use is as a
  trend-strength filter, not a divergence oscillator. The Pine source screener includes it
  as an experimental source.
- `BestSupertrend`'s Pine source uses `ta.dmi(14, 14)` to get `[_, _, adx]` — the Python port
  uses inline Supertrend instead and doesn't call `ta.adx` directly.
- Warmup: ~`2 * period` bars before valid values (TA-Lib ADX smoothing).
