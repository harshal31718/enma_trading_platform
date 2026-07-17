# MACD — Moving Average Convergence Divergence

**Function:** `ta.macd(candles, fast=12, slow=26, signal=9, sequential=False)`  
**Returns:** `(macd_line, signal_line, histogram)` — floats or ndarrays  
**Input:** Close price  
**Backend:** TA-Lib (`MACD`), pandas-ta (`macd`)

## Description

Classic momentum trend-following indicator. The MACD line is the difference between
a fast EMA and a slow EMA. The signal line is an EMA of the MACD line. The histogram
is `macd_line - signal_line`. Crossovers and divergences are the primary signals.

## Parameters

| Param | Default | Range | Notes |
|-------|---------|-------|-------|
| `fast` | 12 | 2–50 | Fast EMA period. Shorter = more reactive. |
| `slow` | 26 | 5–100 | Slow EMA period. Must be > `fast`. |
| `signal` | 9 | 2–50 | Signal EMA period. |
| `sequential` | False | — | `True` returns tuple of three ndarrays. |

## Return Values

- `macd_line`: `EMA(close, fast) - EMA(close, slow)`  
- `signal_line`: `EMA(macd_line, signal)`  
- `histogram`: `macd_line - signal_line`

## Usage in Strategies

| Strategy | Usage |
|----------|-------|
| `MultiDivergence` | MACD line is one of 9 divergence sources; `_compute_pivots` runs on MACD line series |

## Notes

- `MultiDivergence` uses only `macd_line` for pivot detection — the signal line and histogram
  are computed but not used for divergence (they're part of the MACD computation).
- Requires `macd_fast < macd_slow` — enforced by `validate_params`.
- Warmup: ~`slow + signal` bars before valid values appear (~35 bars at default params).
