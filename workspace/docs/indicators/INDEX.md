# Indicators — Quick Reference

**Read this before adding any indicator to avoid duplication.**

All indicators live in `engine/indicators/`. Every indicator is implemented in two backends:
- `adapters/talib_adapter.py` (TA-Lib, default)
- `adapters/pandas_ta_adapter.py` (pandas-ta, pure-Python fallback)

Strategies always import as `import engine.indicators as ta` — never import a backend directly.

---

## Indicator Layer (13 indicators — both backends)

| Name | Function Signature | Returns | Currently Used By |
|------|--------------------|---------|-------------------|
| [EMA](ema.md) | `ta.ema(candles, period=9, sequential=False)` | float / ndarray | MicroScalper, AdaptiveTrend, MicroMacroRSIDivergence |
| [SMA](sma.md) | `ta.sma(candles, period=20, sequential=False)` | float / ndarray | BestSupertrend, MicroMacroRSIDivergence (smoothed RSI layer) |
| [RSI](rsi.md) | `ta.rsi(candles, period=14, sequential=False)` | float / ndarray | MicroMacroRSIDivergence, MultiDivergence |
| [ATR](atr.md) | `ta.atr(candles, period=14, sequential=False)` | float / ndarray | All 5 strategies (stop sizing / volatility gate) |
| [Donchian](donchian.md) | `ta.donchian(candles, period=20, sequential=False)` | (upper, mid, lower) | Not used by any current strategy |
| [MACD](macd.md) | `ta.macd(candles, fast=12, slow=26, signal=9, sequential=False)` | (line, signal, hist) | MultiDivergence |
| [Bollinger Bands](bollinger_bands.md) | `ta.bollinger_bands(candles, period=20, std=2.0, sequential=False)` | (upper, mid, lower) | Not used by any current strategy |
| [ADX](adx.md) | `ta.adx(candles, period=14, sequential=False)` | float / ndarray | MultiDivergence |
| [Stochastic](stochastic.md) | `ta.stochastic(candles, period=14, smooth_k=3, smooth_d=3, sequential=False)` | (%K, %D) | MultiDivergence |
| [Pivot High](pivot_high.md) | `ta.pivot_high(candles, left=10, right=10, source="high", sequential=False)` | float / ndarray | MicroMacroRSIDivergence, MultiDivergence |
| [Pivot Low](pivot_low.md) | `ta.pivot_low(candles, left=10, right=10, source="low", sequential=False)` | float / ndarray | MicroMacroRSIDivergence, MultiDivergence |
| [MFI](mfi.md) | `ta.mfi(candles, period=14, sequential=False)` | float / ndarray | MultiDivergence |
| [OBV](obv.md) | `ta.obv(candles, sequential=False)` | float / ndarray | MultiDivergence |

---

## Inline-Only Indicators (not promoted to the provider layer)

These exist as private methods inside specific strategies. Do NOT add them as standalone indicators
unless a second strategy needs them.

| Name | Location | Logic Summary |
|------|----------|---------------|
| [Z-Score](zscore.md) | `MultiDivergence._zscore_series()` | `(close - SMA(z_period)) / STDEV(z_period)` rolling; no library needed |
| [Supertrend](supertrend.md) | `BestSupertrend._calculate_supertrend()` | `hl2 ± factor*ATR` with ratchet; custom loop; ATR via `ta.atr` |

---

## Adding a New Indicator

1. Verify the indicator is **not** already in the layer table or inline table above.
2. Run `/add-indicator <name>` — it enforces implementing in **both** adapters.
3. After adding, update this INDEX and `workspace/docs/state/CURRENT_STATE.md`.
