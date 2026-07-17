# Pivot High — Swing High Detector

**Function:** `ta.pivot_high(candles, left=10, right=10, source="high", sequential=False)`  
**Returns:** `float` (most recent confirmed pivot value, or `NaN`) | `np.ndarray` (full NaN-padded series)  
**Input:** Any candle column selected by `source`  
**Backend:** Library-agnostic — both adapters delegate to `pivots_from_candles` in `base.py`

## Description

Detects swing highs using the TradingView `ta.pivothigh` algorithm. A bar is a pivot high
when it is strictly greater than the `left` bars before it AND the `right` bars after it.

**No-lookahead**: a pivot at index `i` is only confirmed `right` bars later, so the last
`right` positions in the output are always `NaN` until those bars exist.

## Parameters

| Param | Default | Range | Notes |
|-------|---------|-------|-------|
| `left` | 10 | 1+ | Bars to the left that must be lower. |
| `right` | 10 | 1+ | Bars to the right that must be lower. Detection lags by this many bars. |
| `source` | `"high"` | `"high"`, `"low"`, `"open"`, `"close"` | Which candle column to pivot on. |
| `sequential` | False | — | `True` returns the full NaN-padded series (needed for multi-pivot scans). |

## Return Value

- `sequential=False`: most recent confirmed pivot high value, or `NaN` if none exists.
- `sequential=True`: array of same length as `candles`; position `i` holds the pivot value when confirmed, `NaN` otherwise.

## Usage in Strategies

| Strategy | Usage |
|----------|-------|
| `MicroMacroRSIDivergence` | Swing highs at micro (`micro_pivot`) and macro (`macro_pivot`) scales on the `"high"` column |
| `MultiDivergence` | Price swing highs (`"high"`) for the price pivot baseline |

## Notes

- Shares the underlying `_compute_pivots` primitive with `pivot_low` — same geometry, opposite direction.
- `MultiDivergence` also calls `_compute_pivots` **directly** on oscillator series (RSI, MFI, etc.)
  because those series are not candle arrays. `ta.pivot_high/low` is the public API for price columns.
- Pivot detection on oscillator series: use `from engine.indicators.base import _compute_pivots` inside
  the strategy, not via `ta.pivot_high` (which only takes candle arrays).
