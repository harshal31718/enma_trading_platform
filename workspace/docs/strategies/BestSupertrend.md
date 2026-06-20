# BestSupertrend

**File:** `engine/strategies/BestSupertrend/__init__.py`  
**Category:** Trend-following with multi-timeframe Supertrend filter  
**Timeframe:** 1h–4h  
**Recommended pairs:** Any

## Signal Logic

- **Long:** Close ≥ HTF Supertrend value AND the most recent SMA crossover is bullish (`cross_buy`)
- **Short:** Close ≤ HTF Supertrend value AND the most recent SMA crossover is bearish (`cross_sell`)
- **Long exit:** Fast SMA(7) crosses under Slow SMA(20) (or flip if bear signal also active)
- **Short exit:** Fast SMA(7) crosses over Slow SMA(20) (or flip if bull signal also active)

The HTF Supertrend is computed by resampling `self.candles` to the target timeframe via pandas,
then running the inline Supertrend algorithm. Uses `tsl[-2]` (previous completed HTF bar) to avoid lookahead.

## Indicators Used

| Indicator | Period | Purpose |
|-----------|--------|---------|
| `ta.sma` | `fast_length=7` | Entry/exit trigger (sequential) |
| `ta.sma` | `slow_length=20` | Entry/exit trigger (sequential) |
| `ta.atr` | `pd=3` | ATR input for inline Supertrend (sequential) |
| **Inline Supertrend** | `factor=3.0, pd=3` | HTF filter; see [supertrend.md](../indicators/supertrend.md) |

## Key Parameters

| Param | Default | Options | Notes |
|-------|---------|---------|-------|
| `order_type` | `"Longs+Shorts"` | `Longs+Shorts`, `LongsOnly`, `ShortsOnly` | Trade direction filter |
| `fast_length` | 7 | 1–100 | Fast SMA period |
| `slow_length` | 20 | 2–200 | Slow SMA period |
| `factor` | 3.0 | 1.0–100 | Supertrend multiplier |
| `pd` | 3 | 1–100 | Supertrend ATR period |
| `tf` | `"daily"` | `daily`, `weekly`, `monthly`, `quarterly`, `yearly` | HTF for Supertrend |
| `position_size_pct` | 0.1 | 0.01–1.0 | Fixed fraction of equity (not risk-based) |

## Risk Model

- Uses `size_by_notional(position_size_pct)` — **not** risk-based sizing (no SL/TP set at entry)
- Exit is trigger-based (SMA crossunder/crossover) or via `liquidate()` / `flip_position()`

## Notes

- This is the only strategy not using `size_by_risk` — it uses a fixed equity fraction.
- Supertrend logic is a Python loop over the candle array; performance on long backtests may be slower.
- The `cross_buy`/`cross_sell` scan iterates backwards through SMA history to find the most recent cross.
- No `MIN_WARMUP_CANDLES` declared — warmup is implicitly `max(fast_length, slow_length) + 1`.
