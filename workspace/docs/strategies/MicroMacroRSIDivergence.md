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
| `ta.ema` or `ta.sma` | `smooth_length=60` | Smoothed-RSI confirmation layer (via synthetic candle) |

## Key Parameters

| Param | Default | Notes |
|-------|---------|-------|
| `micro_pivot` | 2 | Must be < `macro_pivot` (Pine `pivotLength`) |
| `macro_pivot` | 10 | Larger = fewer, stronger, later signals (Pine `pivotLengthMacro`) |
| `confluence_window` | 80 | Max bars between micro and macro pivots (was 30 — widened) |
| `min_pivot_bars` | 3 | Min distance between the two RSI pivots (was 5) |
| `max_pivot_bars` | 100 | Max distance (staleness filter) |
| `min_div_diff` | 2.0 | Minimum RSI gap between pivots, 0 = off (was 4.0) |
| `smooth_type` | 1 | 0 = SMA, 1 = EMA (only used when `enable_smoothed_filter=1`) |
| `smooth_length` | 60 | Smoothed-RSI MA period (only used when `enable_smoothed_filter=1`) |
| `enable_rsi_level_filter` | 0 | OFF (Pine default). Require RSI < 50 for bull, > 50 for bear |
| `enable_rsi_direction_filter` | 0 | OFF (Pine default). RSI turning in trade direction |
| `enable_smoothed_filter` | 0 | OFF (Pine default). Smoothed RSI sloping with divergence |
| `exit_on_opposite` | 1 | Exit early on opposite confluence |
| `sl_atr_mult` | 2.0 | ATR multiplier for stop distance |

## Risk Model

- Stop: `price ∓ sl_atr_mult * ATR`
- Take-profit: `rr_target("long/short", stop, rr=self.rrr)` — uses the global RRR setting
- Quantity: `size_by_risk(stop)`

## Notes

- **Defaults relaxed (2026-06):** with all optional filters on and a tight confluence window, the
  strategy fired ~0 trades over a year of BTCUSDT 1h candles. Defaults were loosened toward the Pine
  source: the three optional filters now default **off** (matching Pine's `enableDivFilter` /
  `enableRsiDirectionFilter` / `enableSmoothedDivFilter` = `false`), `min_div_diff` 4→2,
  `confluence_window` 30→80, `min_pivot_bars` 5→3. Verified against the real class over the available
  BTCUSDT 1h history: 1 signal (old) → 13 signals / 6 long + 7 short (new). The always-on noise gates
  (`min_div_diff`, `min`/`max_pivot_bars`) and the micro+macro confluence requirement are retained.
- `MIN_WARMUP_CANDLES = 210` — large due to smooth_length(60) + max_pivot_bars(100) + macro*2.
- The 50-level filter (when enabled) is intentionally inverted from the Pine source (Pine's `rsiAbove50`
  for bullish would make long entries impossible at genuine price lows — this port uses `rsi < 50` for
  bulls).
- Smoothed RSI is computed on a synthetic candle array with RSI in the CLOSE column, routing through
  the pluggable backend.
- Pivot scan is windowed to `max_pivot_bars + 4*macro_pivot + 10` bars for performance.
- Hidden divergences from the Pine source are intentionally **not traded** — only regular divergences.
