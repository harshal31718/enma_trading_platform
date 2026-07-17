# Bollinger Bands

**Function:** `ta.bollinger_bands(candles, period=20, std=2.0, sequential=False)`  
**Returns:** `(upper, middle, lower)` — floats or `(ndarray, ndarray, ndarray)`  
**Input:** Close price  
**Backend:** TA-Lib (`BBANDS`), pandas-ta (`bbands`)

## Description

Volatility bands placed `std` standard deviations above and below a simple moving average.
The bands expand during high volatility and contract during low volatility. The middle band
is a plain SMA. Used for mean-reversion, breakout, and squeeze detection.

## Parameters

| Param | Default | Range | Notes |
|-------|---------|-------|-------|
| `period` | 20 | 5–200 | SMA lookback for the middle band. |
| `std` | 2.0 | 0.5–4.0 | Standard deviation multiplier for band width. |
| `sequential` | False | — | `True` returns tuple of three ndarrays. |

## Return Values

- `upper`: `SMA(period) + std * STDEV(period)`  
- `middle`: `SMA(period)` of close  
- `lower`: `SMA(period) - std * STDEV(period)`

## Usage in Strategies

**Not used by any current strategy.** This indicator is implemented and available but
no built-in strategy currently calls it.

## Notes

- `middle` is identical to `ta.sma(candles, period=period)` — don't call both if you only need the SMA.
- Bollinger Bands cover a related concept to Donchian channels but use volatility-adjusted widths
  (standard deviation) rather than fixed high/low lookback. Don't conflate the two.
- If adding a new strategy that needs volatility bands or a squeeze detector, use this — don't reinvent inline.
