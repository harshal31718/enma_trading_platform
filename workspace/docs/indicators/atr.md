# ATR — Average True Range

**Function:** `ta.atr(candles, period=14, sequential=False)`  
**Returns:** `float` (latest) | `np.ndarray` (sequential)  
**Input:** High, Low, Close  
**Backend:** TA-Lib (`ATR`), pandas-ta (`atr`)

## Description

Measures market volatility as the smoothed average of the "true range" (max of
high-low, |high-prev_close|, |low-prev_close|). ATR doesn't indicate direction —
it quantifies how much price moves per bar.

## Parameters

| Param | Default | Range | Notes |
|-------|---------|-------|-------|
| `period` | 14 | 5–50 | Standard is 14. Larger = smoother, less reactive. |
| `sequential` | False | — | `True` returns the full NaN-padded series. |

## Usage in Strategies

Every strategy uses ATR. Common patterns:

| Pattern | Example |
|---------|---------|
| ATR stop distance | `stop = price - mult * atr` |
| Volatility gate | Compare current ATR vs rolling mean of ATR series |
| Inline Supertrend | `ta.atr(candles, period=pd, sequential=True)` in `BestSupertrend` |
| Take-profit | `tp = price + tp_mult * atr` (MicroScalper, MultiDivergence) |

The volatility gate pattern (MicroScalper, AdaptiveTrend) gets the sequential ATR,
slices the last `2*period` bars, and takes `np.mean(window)` to get the rolling baseline.

## Notes

- Use `size_by_risk(stop_price)` with an ATR-based stop to auto-calculate quantity via rule #6.
- `atr_stop_long = price - mult * atr`, `atr_stop_short = price + mult * atr` is the standard pattern.
- Never call `ta.atr` more than once per candle — compute in `before()` and store in `self.vars`.
