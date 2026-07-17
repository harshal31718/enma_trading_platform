# OBV — On-Balance Volume

**Function:** `ta.obv(candles, sequential=False)`  
**Returns:** `float` (latest, unbounded) | `np.ndarray` (sequential)  
**Input:** Close, Volume  
**Backend:** TA-Lib (`OBV`), pandas-ta (`obv`)

## Description

Cumulative volume indicator. Adds volume when price closes up vs prior bar, subtracts it
when price closes down. The absolute value is meaningless — what matters is the trend and
direction relative to price. OBV diverging from price is a classic leading signal.

## Parameters

| Param | Default | Notes |
|-------|---------|-------|
| `sequential` | False | `True` returns the full series (unbounded, cumulative). |

No `period` parameter — OBV is cumulative from the start of the candle array.

## Usage in Strategies

| Strategy | Usage |
|----------|-------|
| `MultiDivergence` | OBV series is one of 9 divergence sources (plus `div_swing` also compares OBV lows vs price lows) |

## Notes

- `MultiDivergence` uses OBV for two separate divergence checks: the standard oscillator divergence
  (`use_obv` → `osc_div`) AND the raw swing-volume divergence (`use_swing` → compares `candles[:, 5]`
  volume column directly, not OBV). These are independent signals.
- OBV values grow extremely large for frequently-traded symbols — normalize before plotting but treat
  as-is for divergence detection (the sign of the pivot comparison is what matters).
- No warmup period — OBV is valid from bar 1 (cumulative sum).
