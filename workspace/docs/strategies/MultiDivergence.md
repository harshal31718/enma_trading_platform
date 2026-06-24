# MultiDivergence

**File:** `engine/strategies/MultiDivergence/__init__.py`  
**Category:** Multi-oscillator divergence confluence  
**Timeframe:** 15m–4h  
**Recommended pairs:** BTCUSDT, ETHUSDT and other liquid pairs  
**Pine source:** `Multi-Divergence Strategy.pine` — GainzAlgo screener (external TradingView script; not stored in this repo)

## Signal Logic

9 divergence sources are scored independently on each bar where a **new price pivot** confirms.
A trade fires when `≥ min_confluence` sources agree on the same direction AND strictly outnumber
the opposing direction.

**Bullish divergence** per source: price prints a lower low while the oscillator prints a higher low.  
**Bearish divergence** per source: price prints a higher high while the oscillator prints a lower high.

Signal is evaluated only when a fresh price pivot confirms (`piv_len` bars on each side) — non-repainting.

## Divergence Sources (9)

| ID | Name | Indicator |
|----|------|-----------|
| 0 | RSI | `ta.rsi` |
| 1 | MFI | `ta.mfi` |
| 2 | STOCH | `ta.stochastic` (%K) |
| 3 | Z-SCORE | Inline `_zscore_series` — `(close - SMA) / STDEV` |
| 4 | ADX | `ta.adx` |
| 5 | MACD | `ta.macd` (line only) |
| 6 | OBV | `ta.obv` |
| 7 | PRICE | Inline `_price_div` — swing amplitude contraction (<70% of prior) |
| 8 | SWING | Raw volume column (`candles[:, 5]`) via `_compute_pivots` |

Each source can be individually toggled off via `use_rsi`, `use_mfi`, … `use_swing` params.

## Indicators Used

| Indicator | Period | Purpose |
|-----------|--------|---------|
| `ta.pivot_high` | `piv_len` | Price swing high baseline |
| `ta.pivot_low` | `piv_len` | Price swing low baseline |
| `ta.rsi` | `rsi_period=14` | Source 0 |
| `ta.mfi` | `mfi_period=14` | Source 1 |
| `ta.stochastic` | `stoch_period=14` | Source 2 (%K) |
| `ta.adx` | `adx_period=14` | Source 4 |
| `ta.macd` | `fast=12, slow=26, signal=9` | Source 5 (MACD line) |
| `ta.obv` | — | Source 6 |
| `ta.atr` | `atr_period=14` | Stop/TP sizing |
| `_compute_pivots` (base.py) | `piv_len` | Oscillator pivot detection for each source |
| Inline Z-Score | `z_period=20` | Source 3 — see [zscore.md](../indicators/zscore.md) |

## Key Parameters

| Param | Default | Notes |
|-------|---------|-------|
| `piv_len` | 4 | Pivot confirmation lag on each side; 2–15 |
| `min_confluence` | 3 | Min sources that must agree; must not exceed enabled count |
| `sl_atr_mult` | 1.5 | Stop distance (or use `custom_sl_pct`) |
| `tp_atr_mult` | 2.0 | Take-profit distance |
| `use_custom_sl` | 0 | 1 = fixed % stop instead of ATR |
| `custom_sl_pct` | 1.0 | Fixed stop % of entry price |
| `allow_shorts` | 1 | 0 = long-only |

## Risk Model

- Stop: `price ∓ sl_atr_mult * ATR` (or `price * custom_sl_pct / 100` if custom)
- Take-profit: `price ± tp_atr_mult * ATR` (fixed absolute, not R:R)
- Quantity: `size_by_risk(stop, entry_price=entry)`

## Notes

- `MIN_WARMUP_CANDLES = 60` — MACD slow(26)+signal(9) warmup + pivot window.
- `_compute_pivots` is imported directly from `engine.indicators.base` (not via `ta.*`) to run on
  oscillator series that are not candle arrays.
- `_price_div` (source 7): bearish when `swing_up_0 < swing_up_1 * 0.7` (amplitude contraction);
  bullish when swing down contracts — structural, not oscillator-based.
- `div_swing` (source 8) is a raw-volume equivalent of OBV divergence — distinct from `use_obv`.
- A note from the original Pine: a 37% win rate is expected; profit comes from ATR multiples captured.
