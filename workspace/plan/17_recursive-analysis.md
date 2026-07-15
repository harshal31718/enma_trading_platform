# Plan 17 — Recursive-Formula Analysis

**Status:** Ready · **Priority:** P2 · **Phase:** 9 · **Depends on:** 11, 13 · **Related:** 16

**Goal:** Detect indicators whose **latest value depends on how much history was loaded** (recursive
formulas like EMA, RSI/Wilder, SuperTrend). If the most-recent indicator value drifts when you change
the warmup length, live results won't match backtest results.

---

## Current state (audited)

- **Nothing exists.** No recursive-analysis tooling in `engine/`.
- Relevance is high for Enma: AdaptiveTrend uses EMA(200), BestSupertrend uses SuperTrend (both
  recursive). The live path re-runs `prepare()` on a **rolling ≤500-window** each candle (workstream
  #1, P7) — so if 500 candles of warmup isn't enough for EMA(200), live drifts from backtest silently.
- This is distinct from S5: lookahead = future leak; recursive = **insufficient past**.

## Upstream reference (freqtrade `RecursiveAnalysis`)

From `freqtrade/optimize/analysis/recursive.py`:
1. Compute indicators on the **full** dataset using the strategy's declared `startup_candle_count`
   (baseline = "enough history").
2. Recompute on the **same end date** but with varied startup counts: `[199, 399, 499, 999, 1999]`
   (+ the strategy's own).
3. Compare the **final row** of indicator columns (full vs each partial) with pandas `.compare()`.
4. For differing columns, report `pct_change = (partial − full) / full × 100`.
5. **No fixed threshold** — *any* variance flags a recursive formula; report the magnitude so the user
   judges how much warmup is "enough."

## Design (Enma-native)

Standalone script reusing `prepare()` (the indicator-computation seam) — no need to touch the sim loop.

### `engine/scripts/recursive.py`
1. Pick a fixed **anchor end index** `T` in the candle array (the "now").
2. **Baseline:** `prepare(candles_np[:T+1])` with full available history → record `strategy.vars[col][T]`
   for every cached indicator column (the value at the anchor).
3. **Varied warmups:** for each `w` in `[200, 400, 500, 1000, 2000]` (cap at available length), call
   `prepare(candles_np[T-w+1 : T+1])` and record the indicator value at the **anchor** (last index of the
   slice).
4. **Diff:** `pct_change = (value_w − value_full) / value_full × 100` per column per `w`. Flag any column
   whose `|pct_change|` exceeds a reported tolerance (default `0.01%`) at the **largest** warmup we
   actually use in live (500) — that's the operationally important one.
5. **Report:** table of `column × warmup → pct_change`; explicitly call out columns still drifting at
   `w=500` (the live rolling-window size) as **live-vs-backtest drift risk**.

### Why this matters operationally
The output directly answers: *"Is the live rolling window (500) long enough for this strategy's
indicators?"* If EMA(200) still drifts >tol at w=500, bump the live warmup replay length for that
strategy (a `live_bot_manager` knob) — recommend the fix in the report.

## Files to create / modify

| Action | File | Change |
|--------|------|--------|
| Create | `engine/scripts/recursive.py` | warmup-sweep diff of indicator anchor values |
| Create | `engine/tests/test_recursive.py` | EMA/SuperTrend show drift at small warmup, converge at large; SMA(n) is stable at any warmup ≥ n |
| Modify | `workspace/docs/state/CURRENT_STATE.md` | note recommended min warmup per strategy once measured |

## Verification gate

- **Self-test:** EMA(50) drifts at `w=60` but converges by `w≈250` (≈5×period); SMA(50) is exactly
  stable for any `w ≥ 50`. The script must show this contrast.
- Run against all 5 seeded strategies; record the min-warmup recommendation for each.

## Sequencing & risks

- After **S2** (so multi-TF indicators are also swept) and naturally pairs with **S5** as the two
  "backtest integrity" tools. Order S5 then S6 is fine; they're independent of each other.
- Risk: dividing by a near-zero `value_full` → inflated pct. Guard: report "NaN/—" when
  `|value_full| < eps`, like freqtrade does.
- Payoff: this is the tool most likely to find a **real** live/backtest divergence given the rolling
  500-window live design.
