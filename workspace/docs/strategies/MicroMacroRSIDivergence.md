# MicroMacroRSIDivergence

**File:** `engine/strategies/MicroMacroRSIDivergence/__init__.py`  
**Category:** RSI divergence (reversal)  
**Timeframe:** 1h–4h (avoid sub-15m; divergence is a swing concept)  
**Recommended pairs:** BTCUSDT, ETHUSDT  
**Pine source:** `Micro&MacroRSIDivergence.pine` — © Uncle_the_shooter (external TradingView script; not stored in this repo)

## Signal Logic

Fires only on **regular divergences** (reversal) with micro + macro **confluence**:

- **Long:** A MACRO pivot low shows bullish divergence (price lower low + RSI higher low)
  AND a MICRO pivot low shows the same divergence within `confluence_window` bars.
- **Short:** A MACRO pivot high shows bearish divergence (price higher high + RSI lower high)
  AND a MICRO pivot high shows the same within `confluence_window` bars.

The macro pivot fires the trigger (it confirms later); the micro is corroboration.
A signal fires only on the exact candle the macro pivot becomes confirmed (`right` bars after it formed).

**Optional early exit:** When an opposite confluence fires while in a position (`exit_on_opposite=1`).

## Indicators Used

| Indicator | Period | Purpose |
|-----------|--------|---------|
| `ta.rsi` | `rsi_period=14` | Core divergence source (sequential) |
| `ta.atr` | `atr_period=14` | Stop-loss sizing |
| `ta.pivot_high` | `micro_pivot` / `macro_pivot` | Swing high detection at two scales |
| `ta.pivot_low` | `micro_pivot` / `macro_pivot` | Swing low detection at two scales |
| `ta.ema` or `ta.sma` | `smooth_length=2` | Smoothed-RSI confirmation layer (via synthetic candle) |

## Key Parameters

| Param | Default | Notes |
|-------|---------|-------|
| `micro_pivot` | 3 | Must be < `macro_pivot` (Pine `pivotLength`) |
| `macro_pivot` | 5 | Larger = fewer, stronger, later signals (Pine `pivotLengthMacro`) |
| `confluence_window` | 20 | Max bars between micro and macro pivots |
| `min_pivot_bars` | 1 | Min distance between the two RSI pivots |
| `max_pivot_bars` | 500 | Max distance (staleness filter) |
| `min_div_diff` | 0.0 | Minimum RSI gap between pivots, 0 = off |
| `smooth_type` | 1 | 0 = SMA, 1 = EMA (only used when `enable_smoothed_filter=1`) |
| `smooth_length` | 2 | Smoothed-RSI MA period (only used when `enable_smoothed_filter=1`) |
| `enable_rsi_level_filter` | 1 | ON. Require RSI < 50 for bull, > 50 for bear |
| `enable_rsi_direction_filter` | 0 | OFF (Pine default). RSI turning in trade direction |
| `enable_smoothed_filter` | 0 | OFF (Pine default). Smoothed RSI sloping with divergence |
| `exit_on_opposite` | 1 | Exit early on opposite confluence |
| `sl_atr_mult` | 1.5 | ATR multiplier for stop distance |

## Risk Model

- Stop: `price ∓ sl_atr_mult * ATR`
- Take-profit: `rr_target("long/short", stop, rr=self.rrr)` — uses the global RRR setting
- Quantity: `size_by_risk(stop)`

## Notes

- **Defaults tuned toward the Pine source for tradeability.** The noise gates are kept loose so the
  strategy actually fires: `min_div_diff=0.0` (off), `min_pivot_bars=1`, `confluence_window=20`,
  `max_pivot_bars=500`. `enable_rsi_level_filter` defaults **on** (RSI < 50 for longs / > 50 for
  shorts); the direction and smoothed filters default off. The micro+macro confluence requirement is
  always retained.
- `MIN_WARMUP_CANDLES = 30`.
- The 50-level filter (when enabled) is intentionally inverted from the Pine source (Pine's `rsiAbove50`
  for bullish would make long entries impossible at genuine price lows — this port uses `rsi < 50` for
  bulls).
- Smoothed RSI is computed on a synthetic candle array with RSI in the CLOSE column, routing through
  the pluggable backend.
- Pivot scan is windowed to `max_pivot_bars + 4*macro_pivot + 10` bars for performance.
- Hidden divergences from the Pine source are intentionally **not traded** — only regular divergences.
