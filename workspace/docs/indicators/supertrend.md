# Supertrend (Inline — not in indicator layer)

**Location:** `engine/strategies/BestSupertrend/__init__.py` → `BestSupertrend._calculate_supertrend()`  
**Status:** Inline-only; not promoted to `IndicatorProvider` yet.

## Description

Trend-following indicator that plots a trailing stop above or below price based on ATR.
Switches between bullish (below price) and bearish (above price) via a ratchet mechanism
— once a level is set it can only tighten in the current trend direction.

```
up   = hl2 - factor * ATR
dn   = hl2 + factor * ATR
if trend_up == bullish: trend_up = max(up, prev_trend_up)  # ratchet
if trend_dn == bearish: trend_dn = min(dn, prev_trend_dn)
trend switches when close crosses the trailing stop
```

## Implementation (per BestSupertrend)

Uses `ta.atr(candles, period=pd, sequential=True)` for the ATR series, then iterates
to build the ratcheted trend_up/trend_down arrays. The trailing stop line (`tsl`) is
`trend_up` in an uptrend or `trend_down` in a downtrend.

A higher-timeframe (HTF) variant resamples `self.candles` via pandas to daily/weekly/etc.
before running the calculation, and uses `tsl[-2]` (previous completed bar) to avoid lookahead.

## Parameters

| Param | Default | Location |
|-------|---------|----------|
| `factor` | 3.0 | `BestSupertrend.PARAMS["factor"]` |
| `pd` (ATR period) | 10 | `BestSupertrend.PARAMS["pd"]` |
| `tf` (timeframe) | `"daily"` | `BestSupertrend.PARAMS["tf"]` |

## Promotion Path

If another strategy needs Supertrend, add it to `IndicatorProvider`:
1. Declare `supertrend(candles, period=3, factor=3.0, sequential=False) -> Pair` on `IndicatorProvider`.
2. Implement in both adapters using the same loop logic (no TA-Lib equivalent — pure numpy).
3. The HTF resampling is strategy-specific and should stay in the strategy (`_get_resampled_candles`).
4. Export from `__init__.py` and update this doc + `INDEX.md`.
