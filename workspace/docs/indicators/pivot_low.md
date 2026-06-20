# Pivot Low — Swing Low Detector

**Function:** `ta.pivot_low(candles, left=10, right=10, source="low", sequential=False)`  
**Returns:** `float` (most recent confirmed pivot value, or `NaN`) | `np.ndarray` (full NaN-padded series)  
**Input:** Any candle column selected by `source`  
**Backend:** Library-agnostic — both adapters delegate to `pivots_from_candles` in `base.py`

## Description

Detects swing lows using the TradingView `ta.pivotlow` algorithm. A bar is a pivot low
when it is strictly less than the `left` bars before it AND the `right` bars after it.

**No-lookahead**: same as `pivot_high` — confirmation lags `right` bars.

## Parameters

| Param | Default | Range | Notes |
|-------|---------|-------|-------|
| `left` | 10 | 1+ | Bars to the left that must be higher. |
| `right` | 10 | 1+ | Bars to the right that must be higher. Detection lags by this many bars. |
| `source` | `"low"` | `"high"`, `"low"`, `"open"`, `"close"` | Which candle column to pivot on. |
| `sequential` | False | — | `True` returns the full NaN-padded series. |

## Return Value

- `sequential=False`: most recent confirmed pivot low value, or `NaN` if none exists.
- `sequential=True`: full NaN-padded series.

## Usage in Strategies

| Strategy | Usage |
|----------|-------|
| `MicroMacroRSIDivergence` | Swing lows at micro and macro scales on the `"low"` column |
| `MultiDivergence` | Price swing lows (`"low"`) for the price pivot baseline |

## Notes

- Mirror of `pivot_high` — see that doc for the shared `_compute_pivots` primitive and the
  note on detecting pivots on oscillator series.
- Both `pivot_high` and `pivot_low` are computed in `MicroMacroRSIDivergence.before()` on a
  windowed subset of candles for performance (`candles[off:]` where `off = n - span`).
