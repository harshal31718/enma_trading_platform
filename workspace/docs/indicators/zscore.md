# Z-Score (Inline — not in indicator layer)

**Location:** `engine/strategies/MultiDivergence/__init__.py` → `MultiDivergence._zscore_series()`  
**Status:** Inline-only; implemented with pure numpy. Not promoted to `IndicatorProvider` yet.

## Description

Rolling statistical Z-Score: how many standard deviations the current close is from
its rolling mean. Negative values = price below average (potential oversold); positive = above (potential overbought).

```
z = (close[i] - mean(close, z_period)) / stdev(close, z_period)
```

Equivalent to the Pine source: `zsc = stdev20 != 0 ? (close - sma20) / stdev20 : 0`.

## Implementation

Vectorized numpy rolling window (no library call needed):

```python
def _zscore_series(self, close: np.ndarray) -> np.ndarray:
    w = int(self.z_period)
    csum = np.cumsum(np.insert(close, 0, 0.0))
    csq  = np.cumsum(np.insert(close * close, 0, 0.0))
    s    = csum[w:] - csum[:-w]
    s2   = csq[w:]  - csq[:-w]
    mean = s / w
    var  = np.clip(s2 / w - mean * mean, 0.0, None)
    std  = np.sqrt(var)
    z    = np.where(std > 0, (close[w - 1:] - mean) / std, 0.0)
    out[w - 1:] = z
    return out
```

## Parameters

| Param | Default | Location |
|-------|---------|----------|
| `z_period` | 20 | `MultiDivergence.PARAMS["z_period"]` |

## Promotion Path

If another strategy needs Z-Score, add it to `IndicatorProvider`:
1. Declare `zscore(candles, period=20, sequential=False) -> Single` on `IndicatorProvider` in `base.py`.
2. Implement in `talib_adapter.py` using the same numpy formula (TA-Lib has no direct Z-Score).
3. Implement in `pandas_ta_adapter.py` (same formula or `pandas-ta`'s `zscore` if available).
4. Export from `__init__.py` and update this doc.
