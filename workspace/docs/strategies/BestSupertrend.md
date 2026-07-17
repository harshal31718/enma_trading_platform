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

The HTF Supertrend is computed by resampling `self.candles` to the target timeframe via pandas
(backtest), or from live-fetched native HTF candles (`_htf_candles`, live — already excludes the
in-progress bar). Uses the last COMPLETED HTF bar (`tsl[-1]` on the live path; `htf_tsl[k-1]` on
the backtest bucket path — Plan 24 Step S-2, fixed 2026-07-17; previously the live path read
`tsl[-2]`, one bar more stale than backtest) to avoid lookahead.

## Indicators Used

| Indicator | Period | Purpose |
|-----------|--------|---------|
| `ta.sma` | `fast_length=7` | Entry/exit trigger (sequential) |
| `ta.sma` | `slow_length=20` | Entry/exit trigger (sequential) |
| `ta.atr` | `pd=10` | ATR input for inline Supertrend (sequential) |
| `ta.atr` | `atr_period=14` | Stop sizing for the hard ATR stop (AtrBracketRiskModel) |
| **Inline Supertrend** | `factor=3.0, pd=10` | HTF filter; see [supertrend.md](../indicators/supertrend.md) |

## Key Parameters

| Param | Default | Options | Notes |
|-------|---------|---------|-------|
| `direction_filter` | `"Longs+Shorts"` | `Longs+Shorts`, `LongsOnly`, `ShortsOnly` | Trade direction filter (renamed from `order_type` — Plan 24 Step S-4, 2026-07-17: the old name collided with `OrderPlan.order_type`; a saved config using the old key is now rejected by F-016's unknown-param validation) |
| `fast_length` | 7 | 1–100 | Fast SMA period |
| `slow_length` | 20 | 2–200 | Slow SMA period |
| `factor` | 3.0 | 1.0–100 | Supertrend multiplier |
| `pd` | 10 | 1–100 | Supertrend ATR period |
| `sl_atr_mult` | 2.0 | 0.5–10 | Hard ATR stop distance (AtrBracketRiskModel) |
| `atr_period` | 14 | 5–50 | ATR period for the hard stop |
| `tf` | `"daily"` | `1h`, `4h`, `daily`, `weekly`, `monthly` | HTF for Supertrend. `weekly`/`monthly` need a wide enough date range/live history to form `pd+2` completed HTF buckets — Plan 24 Step S-3 (2026-07-17) logs/notifies a session-visible error instead of silently trading zero times when the combo can't be satisfied |
| `position_size_pct` | 0.9 | 0.01–1.0 | Fixed fraction of equity (not risk-based). Default lowered from 1.0 to 0.9 — Plan 24 Step S-1 (2026-07-17): `size_by_notional()` now also sizes down to the true affordable notional (leverage/slippage/fee headroom) instead of the runner rejecting the entry outright, which is why the strategy previously never traded at its own default settings |

## Risk Model

- Binds `AtrBracketRiskModel` + `NotionalPortfolio`: sizing is notional (`position_size_pct` fraction
  of equity), but a **hard ATR stop** (`sl_atr_mult * ATR`, `atr_period`) is now armed at entry —
  this replaced the earlier `SignalExitRiskModel` (no-hard-SL) variant.
- Exit is trigger-based (SMA crossunder/crossover) or the hard ATR stop, or via `liquidate()` / `flip_position()`

## Notes

- This is the only strategy sizing via a fixed equity fraction (`NotionalPortfolio`) rather than `size_by_risk`.
- Supertrend logic is a Python loop over the candle array; performance on long backtests may be slower.
- `cross_buy`/`cross_sell` are precomputed once in `prepare()` into a per-index `_recent[i]` array
  (1 = recent bullish cross, -1 = recent bearish cross); `before()` just reads `_recent[i]` — no
  per-candle scan.
- No `MIN_WARMUP_CANDLES` declared — warmup is implicitly `max(fast_length, slow_length) + 1`.
