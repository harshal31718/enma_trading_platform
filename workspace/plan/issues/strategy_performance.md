# Analysis: Strategy Performance & Platform Gaps

Originally from `workspace/issues_and_solutions/issues/strategy_performance.md` (merged into `plan/` 2026-06-24).

---

## 1. O(N²) Indicator Recomputation in All 5 Strategies

**Root cause:** `BaseStrategy.before()` is called inside the backtest simulation loop with `strategy.candles = candles_np[:t+1]` growing by 1 each iteration. Strategies recompute full indicator arrays from scratch every tick instead of computing once and indexing.

| Strategy | Hot Path Indicator Calls per Candle | Complexity |
|----------|-------------------------------------|------------|
| MicroMacroRSIDivergence | `ta.rsi`, `ta.atr`, `ta.pivot_high` (2×), `ta.pivot_low` (2×), `_smoothed_rsi` | O(N²) — worst offender |
| MultiDivergence | `ta.rsi`, `ta.mfi`, `ta.stochastic`, `ta.adx`, `ta.macd`, `ta.obv`, `ta.pivot_high`, `ta.pivot_low` + z-score, swing | O(N²) — 9 oscillator sources |
| MicroScalper | `ta.ema` (4×), `ta.atr` (1 scalar + 1 sequential) | O(N²) — slice EMAs are worst |
| BestSupertrend | `ta.sma` (4×), `ta.atr` (sequential), pandas resample, backward loop for cross detection | O(N²) — pandas resample in hot loop |
| AdaptiveTrend | `ta.ema` (6×), `ta.atr` (1 scalar + 1 sequential) | O(N²) — already has partial fix but still O(N) per tick |

**Impact:** 100K+ candle backtests are unnecessarily slow. Latency grows quadratically with candle count.

---

## 2. Risk Model Limitations (6 Issues)

| # | Issue | Severity | File | Detail |
|---|-------|----------|------|--------|
| 1 | Fixed R:R target — static take-profit | HIGH | `risk.py:137-153` | `tp = price ± rrr × |price - stop|` — no adaptation as trade develops |
| 2 | Static bracket on divergence strategies | HIGH | `risk.py:83-168` | Only `ChandelierRiskModel` (AdaptiveTrend) trails; MicroMacroRSI and MultiDivergence use static `AtrBracketRiskModel` |
| 3 | ATR is backward-looking | MEDIUM | `talib_adapter.py:56-61` | ATR(14) = average of last 14 candles; stale during volatility spikes |
| 4 | Max notional can override risk budget | LOW | `portfolio.py:109-115` | Notional cap sizes position below what risk model allows |
| 5 | Cost gate defaults off | MEDIUM | `portfolio.py:30` | `min_edge_mult = 0.0` → always trade, never gate on cost |
| 6 | No portfolio-level exposure tracking | LOW (single) / HIGH (chaos) | `portfolio.py` | Each trade sized independently; no aggregate check |

---

## 3. Live / Backtest Synchronization Gap

**Problem:** `LiveBotManager._run_symbol_loop()` loads warmup candles and appends WS data, calling `before()` each tick. Currently `before()` recomputes over the entire growing array (warmup + all live candles).

- Latency grows linearly with session duration
- First iteration after warmup = O(W) where W = warmup size
- 1000th live iteration = O(W + 1000)
- Pivot confirmation needs `right` lookback bars — must work identically in live mode
- Candle gap on WS disconnection requires re-fetch + re-prepare

---

## Plan

See `plans/strategy_precompute_architecture.md` for the two-phase `prepare()`/`before()` architecture solution, `plans/per_strategy_migration.md` for per-strategy migration plans, and `plans/migration_checklist.md` for the execution checklist.
