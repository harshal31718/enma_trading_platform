# RSI — Relative Strength Index

**Function:** `ta.rsi(candles, period=14, sequential=False)`  
**Returns:** `float` (0–100, latest) | `np.ndarray` (sequential)  
**Input:** Close price  
**Backend:** TA-Lib (`RSI`), pandas-ta (`rsi`)

## Description

Momentum oscillator measuring the speed and magnitude of price changes.
Values above 70 typically indicate overbought conditions; below 30 indicate oversold.
The midline at 50 separates bullish and bearish momentum regimes.

## Parameters

| Param | Default | Range | Notes |
|-------|---------|-------|-------|
| `period` | 14 | 2–50 | Standard is 14. Shorter = noisier, more signals. |
| `sequential` | False | — | `True` returns the full NaN-padded series. |

## Usage in Strategies

| Strategy | Usage |
|----------|-------|
| `MicroMacroRSIDivergence` | Core divergence source; micro+macro pivot divergence on RSI series |
| `MultiDivergence` | One of 9 oscillator sources in the confluence vote |

## Notes

- `MicroMacroRSIDivergence` optionally smooths RSI with `ta.ema`/`ta.sma` (smoothed RSI layer).
- `MultiDivergence` runs `_compute_pivots` directly on the sequential RSI array to find
  oscillator pivot highs and lows for divergence detection.
