# Plan 18 — Walk-Forward Analysis

**Status:** Merged→10 · **Superseded by:** `10_monte-carlo-strategy-lab.md` Phase 3 (§2.2, §3.1)

> **2026-07-15:** this file's design — a standalone synchronous `POST /optimize/walk-forward`
> endpoint plus a new `walkForwardResults` collection — **conflicts architecturally** with Plan
> 10 Phase 3, which already scopes walk-forward as part of the job-based Strategy Lab
> (`labResults` collection, `POST /api/v1/lab/optimizations`, BullMQ queue + Socket.IO
> progress). Plan 9's own step 9.6 already flags this scope as "absorbed by Plan 10 Phase 3."
> Building this file's endpoint as specified would create a surface Phase 3 immediately has to
> retire. **Do not build this file standalone.** Its real value — the fold-split algorithm
> (contiguous windows by candle count, anchored-vs-rolling train/test, OOS-stitching, the
> in-sample-vs-out-of-sample degradation signal) — is genuinely well-specified and should be
> pulled directly into Plan 10 Phase 3's implementation. The design below is kept unmodified as
> that reference.

**Goal:** Test strategy robustness across time by splitting the range into sequential
train→test folds, optimizing on each train window and evaluating out-of-sample on the following test
window. Catches strategies that only work on the period they were tuned on.

---

## Current state (audited)

- **Nothing exists** — no walk-forward module.
- Building blocks are all present: `engine/services/backtest_runner.py` (single-range sim),
  `engine/services/optimizer.py` (grid optimization with an `OBJECTIVE_REGISTRY` and
  `run_optimization(config, param_grid, max_combinations)`), and `engine/routers/optimize.py`
  (`POST /optimize`). Walk-forward is an **orchestration layer** over these — no new sim math.

## Upstream reference

- **freqtrade** does walk-forward via repeated hyperopt over rolling `--timerange` windows (no single
  module; it's a documented workflow): optimize on window `i`, validate on window `i+1`, advance.
- **nautilus** ships explicit walk-forward examples in its backtest suite: contiguous train/test
  windows, anchored or rolling origin, aggregate OOS metrics.

Common core: **non-overlapping OOS test windows stitched together = one honest out-of-sample equity
curve.** Anchored (expanding train) vs rolling (fixed-width train) is a config choice.

## Design (Enma-native)

New service orchestrating the existing optimizer + runner. Deterministic (seeded) so results are
reproducible.

### `engine/services/walk_forward.py`
Inputs: strategy, symbol, timeframe, full `[start, end]`, `param_grid`, `objective`, and:
- `n_folds` (default 4), `train_ratio` (default 0.7 of each fold), `mode` ∈ {`rolling`,`anchored`}.

Algorithm:
1. Split `[start, end]` into `n_folds` contiguous windows by **candle count** (not calendar days — use
   the candle index so folds are balanced). For each fold:
   - **Train** = first `train_ratio` of the window (anchored: start … train_end grows each fold).
   - **Test** = the remainder (out-of-sample, never seen by the optimizer).
2. **Train:** `run_optimization()` over `param_grid` on the train window → best params by `objective`.
3. **Test:** `run_backtest_simulation()` with those best params on the **test** window → OOS metrics +
   trades.
4. **Stitch:** concatenate the OOS test trades across folds into one equity curve; compute aggregate
   OOS Sharpe/Sortino/Calmar/max-drawdown/win-rate.
5. **Robustness signal:** report **in-sample vs out-of-sample degradation** per fold (e.g. OOS Sharpe /
   IS Sharpe). Large drop = overfit. This is the headline number.

### Endpoint + persistence
- `POST /optimize/walk-forward` (mirror the existing `/optimize` contract) — runs in `BackgroundTasks`,
  publishes progress to Redis like other long runs.
- Persist to a new collection `walkForwardResults` keyed by `jobId` (engine is sole writer, consistent
  with `backtestResults` ownership). Store per-fold {trainRange, testRange, bestParams, isMetrics,
  oosMetrics} + stitched OOS summary.
- All numeric response fields are **strings** (API contract).

### Determinism
Reuse the optimizer's existing seeding for `max_combinations` sampling; fold boundaries are pure index
math → byte-reproducible.

## Files to create / modify

| Action | File | Change |
|--------|------|--------|
| Create | `engine/services/walk_forward.py` | fold split + train(optimize)/test(backtest) loop + OOS stitch |
| Modify | `engine/routers/optimize.py` | `POST /optimize/walk-forward` (BackgroundTasks + progress) |
| Create | `server/src/models/WalkForwardResult.js` | Mongoose read-model for the new collection |
| Modify | `server/src/controllers/*` + routes | proxy `POST /api/v1/optimize/walk-forward` + `GET /:id` |
| Create | `engine/tests/test_walk_forward.py` | fold math: non-overlapping test windows; union of test ranges == full OOS span; sum of fold test-trade counts equals a single backtest over the stitched test ranges |

## Verification gate

- **Conservation test:** the concatenation of fold test windows exactly tiles the OOS portion of the
  range (no gaps, no overlap). A backtest over each test window with the chosen params produces the
  same trades whether run inside walk-forward or standalone.
- Smoke: run on AdaptiveTrend with a small grid; OOS summary returns finite metrics and per-fold
  IS/OOS degradation ratios.
- No golden-master gate needed (it doesn't change the single-run sim path — it *calls* it unchanged).

## Sequencing & risks

- After **S1** (so per-asset caps are stable) and naturally before/with **S8** (Bayesian hyperopt
  plugs into the *train* step). Build S7 first so S8 has a walk-forward harness to prove itself in.
- Risk: cost — `n_folds × grid` backtests. Cap via the optimizer's existing `max_combinations`; surface
  estimated run count before launching.
- Risk: tiny test windows → unstable metrics. Validate `train_ratio`/`n_folds` so each test window has
  a sane minimum candle count; reject configs that don't.
