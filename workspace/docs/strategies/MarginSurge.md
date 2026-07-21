# MarginSurge

**File:** `engine/strategies/MarginSurge/__init__.py`
**Category:** Volatility-compression breakout scalper
**Timeframe:** 5m / 15m (both validated — see Verdict below)
**Recommended pairs (validation set):** BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT
**Plan:** `workspace/plan/23_high-risk-leverage-strategy.md`

## Verdict: validation FAILED — not recommended for live or further deployment

**This is not a normal "shipped, here's how it works" doc.** Plan 23 was explicit that a
negative-expectancy edge should be killed by its own validation gates rather than shipped anyway
("the correct outcome of this plan is 'don't ship it' — that is a success of the process, not a
failure"). That's the outcome here. The implementation is architecturally correct (passes
`test_boundaries.py`, passes the lookahead sentinel — no lookahead bias) and remains in the
codebase as a reference/for future iteration, but **its alpha has no demonstrated edge** at the
parameters specified in Plan 23, and grid-optimizing on top of it produces textbook overfitting,
not a rescue.

### What was tested (2026-07-21)

1. **Cost-realism table** (default params, leverage=20, risk_pct=3%, full year 2024, 4 symbols ×
   2 timeframes): every combo showed heavy net losses (-46% to -51% of capital). Only
   `SOLUSDT/15m` technically passed the breakeven-win-rate filter (payoff ratio 1.42 → breakeven
   WR 41%) but its *actual* win rate (29%) sat well below that bar — a real alpha problem, not a
   cost problem.
2. **Diagnostic re-run** at leverage=50/risk_pct=1% (removes margin-rejection noise so the trade
   sample reflects the alpha itself, not sizing friction): **every one of 6 symbol/timeframe
   combos showed negative expectancy** over the full year — win rates 17-45%, expectancy -18 to
   -114 $/trade, net losses of 18-79% of capital. This rules out "it's just a leverage/sizing
   artifact" — the entry logic itself does not have a positive edge on 2024 data for any tested
   major.
3. **Lookahead sentinel** — PASS. No divergence between full-array and expanding-window
   `prepare()` for MarginSurge (confirms the Donchian-band and BB-bandwidth "prior candle" shift
   is implemented causally, as designed).
4. **Grid optimization + manual OOS split** on the least-bad combo (SOLUSDT/15m), 64 combinations
   over `dc_period`/`sl_atr_mult`/`rrr`, trained on H1 2024, validated untouched on H2 2024:
   - Best in-sample combo (`dc_period=10, sl_atr_mult=1.5, rrr` — irrelevant, see note below):
     Sharpe 1.76, 50% win rate, +$729.61 (+7.3%), expectancy +$33.03/trade.
   - **Same params, OOS window (H2 2024): 22% win rate, -$1,782.18 (-17.8%), expectancy
     -$44.56/trade.** The plan's own acceptance rule ("OOS expectancy ≥ 50% of in-sample
     expectancy") isn't just missed — the sign flips. This is the textbook in-sample-only-edge
     overfitting pattern QNT-6 warns about, not a marginal miss.
   - **Note on `rrr`:** all four `rrr` values (1.0/2.0/3.0/4.0) at the winning `dc_period`/
     `sl_atr_mult` produced *identical* metrics. With `breakeven_r=1.0` and `trail_atr_mult=1.0`
     both active by default, exits are dominated by the breakeven/trail/time-stop mechanics
     before the static R-multiple TP is ever reached — meaning `rrr` wasn't actually being
     explored by this grid pass. Flagged here rather than silently reported as if it were a real
     3-parameter search.
5. **Monte Carlo + leverage selection (§4), chaos stress (§6)** — **not run.** Gate 4's OOS
   failure is itself a kill per the plan's own gate ordering ("each can kill the strategy — that's
   the point"); running Monte Carlo ruin-probability curves or a chaos stress session on a
   parameter set that has already failed out-of-sample validation would not be a responsible use
   of further compute, and risks manufacturing false confidence from a resampled version of the
   same already-disproven trade sample.

### What this means going forward

- **Do not start a live session with this strategy** — doubly gated: (a) live sessions for it
  require Plan 21 steps 21.1-21.4 regardless (unmet prerequisite, per the plan), and (b) even once
  that's unblocked, nothing above supports running it with real capital exposure.
- **Backtest/Strategy Lab use is fine** — the code is a legitimate, boundary-clean reference
  implementation; a future session could revisit the alpha (different entry logic, a different
  compression/breakout formulation, or different symbols/timeframes) using this file as a
  starting point, but should not assume the current entry conditions have any edge without
  re-running the same gates.
- Seeded into MongoDB (`services/strategy_seeder.py`) so it's visible/selectable in the UI for
  backtesting, same as any other strategy — its description there states the validation outcome
  explicitly rather than implying it's ready to trade.

## Concept (as specified, for reference)

Long entry — all of: close breaks above the **prior candle's** Donchian(`dc_period`=20) upper
band (shifted by 1 — compares against yesterday's already-formed channel, not one that includes
today's own high); that prior candle's Bollinger(20) bandwidth sits in the bottom `squeeze_pct`
(30%) of its trailing 200-candle history (compression precondition); ADX(14) ≥ `adx_min` (25) and
rising vs 3 candles ago; MFI(14) ≥ 55; close > EMA(200). Short entry is the exact mirror. Stop is
`sl_atr_mult` (0.75) × ATR(14) from entry; TP nominally 2R (see the `rrr` note above — rarely the
actual exit path); breakeven move at 1R; ATR trail (1.0×) after breakeven; time-stop exit after
`max_hold_candles` (24) if neither SL/TP fires first.

## Indicators Used

| Indicator | Period | Purpose |
|-----------|--------|---------|
| `ta.donchian` | `dc_period=20` | Breakout level (prior-candle shifted) |
| `ta.bollinger_bands` | 20 (fixed) | Bandwidth → compression precondition |
| `ta.adx` | 14 (fixed) | Momentum confirmation |
| `ta.mfi` | 14 (fixed) | Flow confirmation |
| `ta.ema` | 200 (fixed) | Trend alignment |
| `ta.atr` | 14 (fixed, via `AtrBracketRiskModel`) | Stop/TP/trail sizing |

## Key Parameters

| Param | Default | Notes |
|-------|---------|-------|
| `dc_period` | 20 | Donchian breakout lookback; 10-55 |
| `squeeze_pct` | 0.30 | Compression threshold (bottom % of 200-candle bandwidth history) |
| `adx_min` | 25 | Minimum ADX for momentum confirmation |
| `sl_atr_mult` | 0.75 | Stop distance (the design's risk unit — deliberately tight) |
| `rrr` | 2.0 | Nominal TP target — see the grid-search note above on why this rarely binds |
| `breakeven_r` | 1.0 | Move stop to entry at this R multiple |
| `trail_atr_mult` | 1.0 | ATR trail multiplier after breakeven |
| `atr_percentile_min` | 0.40 | ATR-percentile veto floor (dead-market filter, in `AtrBracketRiskModel`) |
| `max_hold_candles` | 24 | Time-stop |

## Risk Model

- `AtrBracketRiskModel` (bound in `__init__`) owns the SL/TP bracket, breakeven move, ATR trail,
  and the `atr_percentile_min` veto — none of that logic lives in the strategy class.
- `RiskBudgetPortfolio` sizes by risk budget: `qty = min(equity*risk_pct/risk_per_unit,
  equity*leverage/price)`.

## Notes

- `MIN_WARMUP_CANDLES = 250` — covers EMA(200) plus the rolling-200 bandwidth-percentile window
  with margin, and stays well under the live retention cap (`MAX_CANDLES_RETAINED=500`, Plan 8
  Step 8.3/ENG-8) so the strategy becomes ready deterministically live, not just in backtest.
- The `max_hold_candles` time-stop deliberately does **not** use `on_open_position()` —
  `LiveAdapter` never calls that hook (only `BacktestAdapter` does), so relying on it would make
  the time-stop backtest-only. Entry-index tracking instead uses only `self.is_open`/`self.index`/
  `self.vars`, which both adapters keep consistent.
- `_rolling_percentile_rank()` (module-level helper) is vectorized via
  `numpy.lib.stride_tricks.sliding_window_view` rather than a per-index Python loop — verified
  bit-identical to a naive loop implementation before use, needed once this strategy is run
  through grid search or Monte Carlo (which call `prepare()` far more times than one backtest).
