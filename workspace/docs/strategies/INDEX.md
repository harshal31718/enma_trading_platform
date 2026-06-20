# Strategies — Quick Reference

**Read this before adding any strategy to avoid duplication.**

All strategies live in `engine/strategies/<Name>/__init__.py`, extend `BaseStrategy`,
and are seeded to MongoDB by `engine/services/strategy_seeder.py` on startup.
Under the **Five-Model Quant Architecture** (see [MODELS.md](../core/MODELS.md)), each strategy functions as the **Alpha Model** component of the pipeline, delegating to pluggable Risk, Portfolio, Cost, and Execution models.

Indicators are imported as `import engine.indicators as ta`. See `workspace/docs/indicators/INDEX.md`
for the full indicator catalog before choosing what to use.

---

## Implemented Strategies (5)

| Name | Category | Signal Logic | Key Indicators | Best Timeframe |
|------|----------|-------------|----------------|----------------|
| [MicroScalper](MicroScalper.md) | Scalper (always-in) | Fast EMA(3/9) cross + ATR gate; `flip_position` | ema, atr | 1m |
| [AdaptiveTrend](AdaptiveTrend.md) | Trend + Regime | EMA(200) regime + EMA(21/55) cross + ATR gate + chandelier trailing stop | ema, atr | 4h |
| [BestSupertrend](BestSupertrend.md) | Trend + MTF | HTF Supertrend (inline) + SMA(7/20) crossover | sma, atr (inline Supertrend) | 1h–4h |
| [MicroMacroRSIDivergence](MicroMacroRSIDivergence.md) | Divergence | RSI regular divergence on micro+macro pivot confluence; ported from Pine | rsi, atr, pivot_high, pivot_low, ema/sma | 1h–4h |
| [MultiDivergence](MultiDivergence.md) | Divergence Confluence | 9-oscillator vote; entry when ≥N agree on direction; ported from Pine | rsi, mfi, stochastic, adx, macd, obv, pivot_high, pivot_low, atr + inline Z-Score | 15m–4h |

---

## Pine Script Sources (external — not stored in this repo)

Two strategies were ported from external TradingView Pine scripts. **The `.pine` files are not
checked into this repository** — only the ported Python in `engine/strategies/` lives here.

| Source (external) | Ported To | Notes |
|-------------------|-----------|-------|
| `Micro&MacroRSIDivergence.pine` (© Uncle_the_shooter) | `MicroMacroRSIDivergence` | Pine is a visualisation indicator; strategy adds trading rules |
| `Multi-Divergence Strategy.pine` (GainzAlgo screener) | `MultiDivergence` | Pine screener scores 9 sources independently; strategy collapses to a confluence threshold |

---

## Adding a New Strategy

1. Check the table above — confirm the signal logic doesn't duplicate an existing strategy.
2. Check `workspace/docs/indicators/INDEX.md` — reuse existing `ta.*` functions rather than computing inline.
3. Run `/add-strategy <Name>` — scaffolds `engine/strategies/<Name>/__init__.py` and seeds it.
4. After implementation, update this INDEX, add a `workspace/docs/strategies/<Name>.md`, and update `workspace/docs/state/CURRENT_STATE.md`.
