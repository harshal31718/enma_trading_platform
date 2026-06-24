# MicroScalper

**File:** `engine/strategies/MicroScalper/__init__.py`  
**Category:** High-frequency scalper / pipeline stress-tester  
**Timeframe:** 1m  
**Recommended pairs:** BTCUSDT or any high-liquidity futures pair

## Signal Logic

- **Long entry:** Fast EMA(9) crosses above Slow EMA(21) AND ATR volatility gate passes
- **Short entry:** Fast EMA(9) crosses below Slow EMA(21) AND ATR volatility gate passes
- **Position flip (always-in):** While holding, an opposite crossover makes `forecast()` return
  `Signal(direction=-current_dir)`; the pipeline's Execution model closes the current leg and opens
  the opposite one atomically. Zero gap between legs.
- **Exit:** ATR-based SL/TP armed on every entry (including flips)

This is a stop-and-reverse (SAR) strategy — nearly always in a position. Designed for
maximum trade volume to stress-test the backtesting engine, not to maximize profit.

## Indicators Used

| Indicator | Period | Purpose |
|-----------|--------|---------|
| `ta.ema` | `fast_period=9` | Fast trend line |
| `ta.ema` | `slow_period=21` | Slow trend line |
| `ta.atr` | `atr_period=14` | Stop/TP sizing and volatility gate |

Volatility gate: if `atr_multiplier > 0`, current ATR must exceed `rolling_mean(ATR) * multiplier`.
Rolling mean uses `series[-(period*2):]` via `np.mean` (backend-agnostic, BUG-05 fix).

## Key Parameters

| Param | Default | Notes |
|-------|---------|-------|
| `fast_period` | 9 | Must be < `slow_period` |
| `slow_period` | 21 | — |
| `atr_period` | 14 | — |
| `atr_multiplier` | 1.2 | 0 disables volatility gate |
| `sl_atr_mult` | 1.5 | Must be < `tp_atr_mult` |
| `tp_atr_mult` | 2.0 | — |

## Risk Model

- Stop: `price ∓ sl_atr_mult * ATR`
- TP: `price ± tp_atr_mult * ATR`
- Quantity: `size_by_risk(stop)`

## Notes

- Stop-and-reverse is expressed through `forecast()` returning a reversed `Signal` while holding;
  the pipeline's Execution model performs the atomic close-and-reopen. No `update_position()` override
  and no direct `self.buy/sell` writes (the legacy pattern is gone).
- `MIN_WARMUP_CANDLES = 25` (slow_period + atr_period + buffer).
- The direct `import talib` that existed for ATR baseline was removed (BUG-05) — now uses numpy.
