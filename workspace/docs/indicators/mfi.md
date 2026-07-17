# MFI — Money Flow Index

**Function:** `ta.mfi(candles, period=14, sequential=False)`  
**Returns:** `float` (0–100, latest) | `np.ndarray` (sequential)  
**Input:** High, Low, Close, Volume  
**Backend:** TA-Lib (`MFI`), pandas-ta (`mfi`)

## Description

Volume-weighted RSI. Uses the typical price (`(high + low + close) / 3`) and volume to
measure buying and selling pressure. Values above 80 = overbought; below 20 = oversold.
More sensitive to volume than RSI; effective at detecting divergences driven by smart money.

## Parameters

| Param | Default | Range | Notes |
|-------|---------|-------|-------|
| `period` | 14 | 2–50 | Lookback window. |
| `sequential` | False | — | `True` returns the full NaN-padded series. |

## Usage in Strategies

| Strategy | Usage |
|----------|-------|
| `MultiDivergence` | MFI series is one of 9 divergence sources; `_compute_pivots` on MFI series |

## Notes

- The Pine source computes `ta.mfi(hlc3, 14)` — `hlc3 = (high + low + close) / 3` as the
  price input. The TA-Lib implementation uses the standard `(high+low+close)/3` implicitly.
- Requires volume data — ensure candles come from a liquid market.
- Unlike RSI which uses only close, MFI incorporates volume so it can signal divergences
  where price and volume diverge (e.g., rising price but falling volume = bearish MFI divergence).
