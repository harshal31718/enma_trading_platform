# AdaptiveTrend

**File:** `engine/strategies/AdaptiveTrend/__init__.py`  
**Category:** Regime-aware trend-following  
**Timeframe:** 4h (primary) or 1h  
**Recommended pairs:** BTCUSDT, ETHUSDT

## Signal Logic

Four layers must all agree before entry:

1. **Regime filter** — EMA(200) defines direction; price must be above (long) or below (short) it,
   AND the EMA itself must be rising (long) or falling (short) by `slope_lookback` bars.
2. **Momentum trigger** — Fast EMA(21) crosses above Slow EMA(55) for long, vice versa for short.
3. **Volatility gate** — Current ATR must exceed `atr_floor_mult * rolling_mean(ATR)` (disabled when `atr_floor_mult=0`).
4. **Adaptive risk sizing** — Quantity = `(equity * risk_pct) / (sl_atr_mult * ATR)`, capped by `max_leverage`.

Exit uses a chandelier trailing stop: `highest_price_since_entry - trail_atr_mult * ATR` (longs), only ever tightening.
Optional breakeven move: stop moves to entry price once price extends `breakeven_r * initial_risk` in profit.

## Indicators Used

| Indicator | Period | Purpose |
|-----------|--------|---------|
| `ta.ema` | `trend_period=200` | Regime filter |
| `ta.ema` | `fast_period=21` | Entry trigger |
| `ta.ema` | `slow_period=55` | Entry trigger |
| `ta.atr` | `atr_period=14` | Stop sizing, volatility gate, trailing stop |

## Key Parameters

| Param | Default | Notes |
|-------|---------|-------|
| `trend_period` | 200 | Regime EMA |
| `slope_lookback` | 5 | Bars for EMA slope measurement |
| `fast_period` | 21 | Must be < `slow_period` |
| `slow_period` | 55 | — |
| `atr_floor_mult` | 1.0 | 0 disables gate |
| `sl_atr_mult` | 2.0 | Must be ≤ `trail_atr_mult` |
| `trail_atr_mult` | 3.0 | Chandelier trailing distance |
| `breakeven_r` | 0.0 | 0 disables breakeven move |
| `tp_r_mult` | 0.0 | 0 = pure trailing exit |
| `max_leverage` | 20.0 | Notional leverage cap for sizing |
| `allow_shorts` | 1 | 0 = long-only |

## Risk Model

- Stop: `price ∓ sl_atr_mult * ATR` (initial); chandelier trailing thereafter
- TP: Only if `tp_r_mult > 0` — `price ± tp_r_mult * initial_risk`
- Quantity: Custom `_position_qty` capped by `max_leverage` and `max_qty()`

## Notes

- `MIN_WARMUP_CANDLES = 210` (trend_period + slope_lookback + buffer).
- All indicators computed exactly once in `before()` — D-01/D-03 fix.
- Per-trade state stored in `self.vars` (trend_ema, atr, atr_baseline, etc.) — all indicators computed exactly once in `before()`.
