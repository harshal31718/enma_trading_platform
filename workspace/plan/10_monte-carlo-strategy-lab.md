# Plan 10 — Monte Carlo Optimiser & Strategy Lab

**Status:** In progress — MC engine core shipped 2026-07-15 (Phase 1a), job plumbing shipped
2026-07-19 (Phase 1b), Strategy Lab MC tab shipped 2026-07-19 (Phase 2), walk-forward job
plumbing shipped 2026-07-19 (Phase 3a), **Optimizer tab UI shipped 2026-07-19 (Phase 3c, see
below)**, **Phase 3d fully shipped and live-verified 2026-07-19 (engine persistence + client
trials table, see below)**; Phase 3b (Optuna TPE), DSR/PBO overfitting stats, and Phase 4
(MC-scored selection) not started · **Priority:** P1 ·
**Depends on:** 9 (steps 9.1/9.3 for correct inputs — both Shipped; 9.6/9.9 are absorbed here) ·
**Related:** 2 (jobs/CI), 7 (client decomposition)

## Phase 3d shipped 2026-07-19 (per-trial persistence + trials table UI — DSR/PBO still not started)

**Engine — per-trial persistence.** `services/walk_forward.py`'s per-fold loop already had every
combo `run_optimization` scored sitting in `train_result["results"]` — the grid search was never
re-run once the winner was picked, its full ranked list was just discarded down to `best` before
this change. Fix: each fold dict in `run_lab_walk_forward`'s return now carries a `trials` key —
`train_result["results"]` verbatim (params/loss/rank/metrics per combo), present on both normal
and `skipped` folds. No new simulation math, no new formula, no schema migration.

**Real bug found and fixed by live-verifying, not just unit tests:** the first live browser
exercise of the Optimizer tab (below) hit a real HTTP 500 — `ValueError: Out of range float
values are not JSON compliant`. `optimizer.py`'s error/ineligible combos carry `loss=float("inf")`
by design (its own error path); only `best` (already filtered to a finite loss via
`math.isfinite`) reached the router before this session, so this was never exercised. Persisting
every trial means every trial's `loss` now serializes into the HTTP response, and Python's `json`
module rejects inf/-inf/nan outright. Fix: `_json_safe_trials()` sanitizes any non-finite `loss`
to `None` before a fold's `trials` list is built. New regression test
(`test_run_lab_walk_forward_trials_are_always_json_serializable`) calls `json.dumps()` on the
result directly — this is the class of bug unit tests alone can't catch, since they never
serialize the response the way FastAPI actually does. Full engine suite 472/472.

**Client — trials table.** New `client/src/components/lab/TrialsExplorer.jsx`: a per-fold
sortable trials table (rank/params/IS metrics/loss, "error" shown for failed combos) plus a
loss-landscape heatmap when the grid varies exactly 2 params (both genuinely buildable from
`fold.trials` alone). Deliberately **not** an IS-vs-OOS scatter — only each fold's winning combo
gets evaluated out-of-sample, so no per-trial OOS value exists to plot; fabricating one would
misrepresent the data. Wired into `StrategyLab.jsx`'s Optimizer results canvas, replacing the
stale "not built yet" placeholder for the trials-table piece specifically (Optuna/DSR/PBO notice
kept, still accurate).

**Also found and fixed while live-testing:** `WalkForwardWizard.jsx`'s submit payload never
included `exchange` at all (`NewBacktestWizard.jsx`'s equivalent hardcodes
`exchange: 'Binance Futures'` — this file just omitted the field), so every real submission
through the UI 400'd against `buildWalkForwardConfig`'s required-field check. This had been true
since Phase 3c shipped and was never caught because no prior session had live browser/backend
access to click the actual button — a concrete example of why "the code compiles" and "the
feature works" are different claims.

**Live-verified end-to-end, this session's own Chrome instance, already-logged-in session:**
selected MicroScalper/BTCUSDT/1d/2022-06-15→2023-12-31 in the real Optimizer wizard, ran a
2-fold/8-combo-per-fold job through the real BullMQ queue → engine → MongoDB (Atlas) round trip,
watched it fail with the exchange-field 400, fixed it, resubmitted, hit the inf-loss 500, fixed
that too, resubmitted again, and confirmed the full results canvas renders correctly — degradation
verdict, stitched OOS card, fold table, and the new trials table with correct rank/params/error
handling, no console errors. Both test lab runs cleaned up from the DB after.

**Still not done:** Deflated Sharpe Ratio and PBO (§2.2's "honesty layer") still need a
normal-CDF/inverse-CDF primitive and are still deferred pending a session that can numerically
verify the formula. Optuna/TPE search is Phase 3b, separately scoped.

## Phase 3c shipped 2026-07-19 (Optimizer tab UI — fold-level only, not the full trials view)

New "Optimizer" tab on the Strategy Lab page (`client/src/pages/StrategyLab.jsx` now uses
`Tabs`/`TabsContent` for "Robustness (MC)" vs "Optimizer", per §4.1's two-tab layout).
`WalkForwardWizard.jsx`: strategy/symbol/timeframe/date-range picker (mirrors
`NewBacktestWizard.jsx`'s own fields), `ParamGridForm.jsx` (auto-renders min/max/step-or-point-count
per param from the strategy's existing PARAMS schema — same `{label, default, min, max, type}`
shape `ParamsForm.jsx` already consumes for single-value backtest runs, per §4.3.7's own
recommendation), objective dropdown (new thin Node proxy `GET /api/v1/lab/objectives` →
engine's existing `GET /optimize/objectives`), mode/nFolds/trainRatio/minTrades/maxCombinations
inputs, and a combo-count × fold-count cost estimate preview with a warning above 1,000 backtests.
`OptimizationHistoryRail.jsx` mirrors the MC tab's `HistoryRail.jsx`. Results canvas:
`DegradationVerdict.jsx` (the headline avg IS→OOS Sharpe degradation ratio, severity-colored),
`StitchedOOSCard.jsx` (the trade-level OOS aggregate), `FoldResultsTable.jsx` (one row per fold —
train/test range, best params, IS/OOS Sharpe, degradation, OOS trade count). Socket wiring against
`optimization:{labId}` mirrors the MC tab's `simulation:{labId}` pattern exactly. Also fixed:
`lab.controller.js`'s `runOptimization` now resolves a client-sent `strategyId` to the engine's
`filePath` via `Strategy.findById` (matching `POST /api/v1/backtest`'s own convention) instead of
trusting a raw `strategyFile` path from the client, which the Phase 3a controller had skipped.

**Real, disclosed limitation — not the plan's full §4.3 vision:** `walk_forward.py` (Phase 3a)
only persists each fold's WINNING param combo, not every trial evaluated during that fold's grid
search. So `FoldResultsTable.jsx` is genuinely one-row-per-fold, not the plan's §4.3.1 "trials
table (params, IS/OOS metrics, DSR, mc_p5, rank)" — there is no per-trial IS-vs-OOS scatter, param
heatmap, or walk-forward window map possible from today's persisted data. Building those needs an
engine-side change (persist every trial's params+metrics per fold, not just the winner) — real,
not-small scope, called **Phase 3d** below rather than faked with fold-level data relabeled as
"trials." The UI says this explicitly in an inline note rather than silently presenting a
fold-table as if it were the richer view the plan originally sketched.

**Verification gap, same pattern as Phases 2/3a:** no Docker/Linux-native `client/node_modules` in
this sandbox — none of this was compiled or rendered. Hand-reviewed against `NewBacktestWizard.jsx`
and the MC tab's own already-shipped components for import-path/prop-shape consistency.

## Phase 3a shipped 2026-07-19 (walk-forward job plumbing, grid search only)

Engine: new `engine/services/walk_forward.py` — pure orchestration over the two already-shipped,
already-tested primitives (`services.optimizer.run_optimization` for train,
`services.backtest_runner.run_backtest_simulation` for test), per Plan 18's own framing ("no new
sim math"). Fold split by candle COUNT (not calendar days) via a new `_fetch_candle_times()` +
`_split_folds()` (rolling = fixed-width train per fold; anchored = expanding train from the very
first candle). Per fold: grid-optimize on the train window → best params → single backtest on the
test window with those params → per-fold in-sample-vs-out-of-sample Sharpe degradation ratio (the
plan's own headline "is this overfit" signal) computed from two already-real numbers, no new
statistical formula. Stitched-OOS aggregate reads back each fold's persisted `backtestTrades` and
concatenates them trade-level (same pnl/capital-additive, scale_out-excluded convention
`monte_carlo.py` already uses) — explicitly documented as a trade-level approximation, not the
candle-level Sharpe a single contiguous backtest reports (folds have calendar gaps between them).
New `POST /simulate/optimize` router endpoint, same thin async-job-semantics pattern as
`/simulate/monte-carlo`. `services/optimizer.py` gained an opt-in `min_trades` filter
(`OptimizerConfig.min_trades`, default 0/off — fully backward compatible) that excludes
lucky-few-trades combos from being selected as `best` (still visible in `results`, just
ineligible for the top pick).

Node: `labConfig.js` gained `buildWalkForwardConfig()` (reject-not-clamp validation, mirroring
`buildMonteCarloConfig`'s stance, except the two documented numeric caps `MAX_N_FOLDS`=12 and
`MAX_MAX_COMBINATIONS`=500 — unlike the old sync `/optimize/run`, the job-based Lab path never lets
`maxCombinations=0` mean "uncapped", since a fold × grid product without a cap can mean thousands
of backtests). New `lab.controller.js` handlers (`runOptimization`/`getOptimization`/
`listOptimizations`) at `/api/v1/lab/optimizations` — no parent-jobId ownership check needed
(unlike Monte Carlo, an optimization isn't derived from an existing backtest; it's a standalone
strategy+symbol+range run scoped directly to `req.user.id`). New `optimizationQueue`/
`optimization.worker.js` mirroring `simulationQueue`/`simulation.worker.js` exactly.
`socketEmitter.js` gained an `optimization` job-type case (`optimization:progress/complete/error`);
`config/socket.js`'s room join/leave/disconnect handling extended to the `optimization:` prefix
(alongside the existing `backtest:`/`simulation:` cases — this was NOT actually a generic
`<prefix>:<id>` handler despite a prior session's tracker note claiming so; it's three explicit
string-prefix checks, corrected here rather than left to bite a future session).

**Deliberately deferred, not silently dropped:**
- **Optuna/TPE search (Plan 19's design) — Phase 3b.** Grid search only ships here; the search
  loop is swappable without touching the fold/stitch logic (Plan 19 itself notes "S8 swaps only
  the search loop").
- **Deflated Sharpe Ratio / PBO overfitting statistics (§2.2's "honesty layer") — Phase 3b/3c,
  not attempted this session.** Both need a normal-CDF/inverse-CDF numerical primitive this
  session had no way to verify (no pytest/Docker access in the writing sandbox — see below).
  Shipping an unverified statistical formula that traders would use to judge overfitting risked
  being worse than shipping none; deferred rather than guessed at. The min-trades filter (the
  other half of the honesty layer) DID ship — it's a simple threshold, no formula risk.
- **Optimizer tab UI — shipped later the same day as Phase 3c** (fold-level wizard/history/results
  only; see Phase 3c's own section above for what shipped and what didn't). This session (3a)
  shipped job plumbing only, mirroring Phase 1b → Phase 2's own sequencing: backend before UI.
  The trials table / IS-vs-OOS scatter / param heatmap / walk-forward window map need per-trial
  data this session's persistence doesn't capture — that's Phase 3d, still not done.
- **Progress publishing** — `socketEmitter.js`'s `optimization` case is wired end-to-end, but
  `walk_forward.py` never calls `publish_progress` (unlike Monte Carlo where this is a deliberate
  no-op because the job is sub-second, a walk-forward run is genuinely multi-minute — this one
  is a real gap, not a documented non-issue. Needs per-fold progress threaded through
  `run_optimization`'s existing-but-unused `progress_callback` param down into `walk_forward.py`.

**Verification gap, disclosed rather than skipped:** same sandbox constraint as Phase 2 — no
Docker access, and this session cannot run engine pytest (`asyncpg`/TA-Lib import chain
unavailable on host, per root `CLAUDE.md` Rule B) or server jest (this is server+engine code, not
client, so the earlier Phase 2 node_modules platform-mismatch doesn't apply here, but there is
still no Docker to run jest in either). New tests written (`engine/tests/test_walk_forward.py`,
14 cases covering fold-split conservation/anchored-vs-rolling/degradation-ratio computation/trade
stitching/error paths; `labConfig.test.js` gained 12 `buildWalkForwardConfig` cases) but **not
executed** — same disclosed pattern as Phase 2 and the 2026-07-18 session's Docker gap. Run inside
the container to confirm:
```
docker exec enma_trading_platform-engine-1 pytest /app/tests/test_walk_forward.py
docker exec enma_trading_platform-server-1 npm test -- labConfig.test.js
```

## Phase 2 shipped 2026-07-19 (Strategy Lab page, MC tab)

New route `/lab` (`client/src/pages/StrategyLab.jsx`) + nav item (between Backtest and
AlgoTrading), `hooks/useLab.js` (mirrors `useBacktest.js`'s job-lifecycle pattern exactly —
mutation to enqueue, query-by-id with terminal-state `staleTime: Infinity`, history-list query).
`components/lab/`: `RunWizard` (backtest selector + mode/runs/blockLen/ruinThresholdPct),
`HistoryRail` (status-iconed run list), `FanChart` (recharts `ComposedChart`, p5/p25/p50/p75/p95
bands over the synthetic trade-sequence index from `equityBands`), `PercentileSpread` (box/
whisker-style spread for final-equity and max-drawdown), `ExceedanceCurve` (P(DD>x) from
`drawdownExceedance`, ruin-threshold reference line), `RuinCard` (severity-colored), `VerdictStrip`
(point-estimate vs MC-p5 gap sentence, per the plan's own example wording), `ConfigDrawer`
(read-only, reproducibility). Socket wiring mirrors `Backtest.jsx`'s `backtest:*` room pattern
against `simulation:{labId}` (`simulation:progress`/`simulation:complete`/`simulation:error`,
already wired server-side in Phase 1).

**Real scope gap found and resolved honestly, not silently:** §4.2 items 2–3 call for final-equity
and max-drawdown *histograms*. `run_lab_simulation` (Phase 1) only persists the five percentiles
(`finalEquityPercentiles`/`maxDrawdownPercentiles`) — the raw per-run array (up to 20,000 values)
is discarded after `np.percentile` runs; there is no binned-count field in `labResults.results`
today. A true histogram needs an engine-side change (persist bins or raw samples) that Phase 1
didn't scope. Rather than fabricate a histogram from 5 points, `PercentileSpread.jsx` renders an
honest box/whisker-style percentile spread instead, with an explicit code comment documenting why
and what would need to change. **Follow-up scope, not done here:** add binned histogram data to
`run_lab_simulation`'s persisted results if/when the fan chart + percentile spread turn out to be
insufficient in practice.

**Also scoped out (per Phase 1's own already-documented decisions, unchanged):** the mode-breakdown
table (§4.2 item 5) needs multiple modes enabled per single run — the engine only runs one mode
(`block` xor `iid`) per submission; comparing them today means two separate history-rail entries,
not a combined breakdown row. True drag-to-explore on the ruin threshold isn't wired (would imply
live recompute) — re-running with a different `ruinThresholdPct` via the wizard is the mechanism.

**Retired:** `SimulationResults.jsx` deleted; its Risk Dashboard slot (Zone 3) replaced with a
CTA card linking to `/lab`. `GET /api/v1/risk/backtest/:id/simulation` now returns **410 Gone**
with a pointer to `/api/v1/lab/simulations` (per Phase 2's own acceptance criteria) — the
`engine/routers/leverage_sensitivity.py` router itself is untouched (still callable directly,
just no longer reachable from the product). `useBacktestSimulation` hook removed from
`useRiskSettings.js`. Added a "Robustness Check" deep-link button on the Backtest report page
(next to Export JSON) to `/lab?sourceJobId={jobId}` — covers part of §4.4's "everywhere else"
scope (the auto-enqueued MC summary strip itself is not built; that's a bigger Phase 4-adjacent
piece needing an auto-enqueue trigger on backtest completion, left as remaining scope below).

**Not done / remaining for Phase 2's own full scope:**
- Backtest-page compact MC summary strip (auto-enqueued on backtest completion) — only a manual
  deep-link button shipped, not the auto-enqueue-and-render-inline piece from §4.4.
- Component tests for the results canvas (Plan 2's harness) — not written this session; the repo's
  only existing client test file is a page-level smoke test (`src/tests/pages.smoke.test.jsx`),
  no per-component harness convention exists yet to follow.
- **Verification gap, disclosed rather than skipped:** this session's sandbox has no Docker access
  (root `CLAUDE.md` Rule B) and its bind-mounted `client/node_modules` is a Windows-installed copy
  (`@rollup/rollup-linux-x64-gnu` / `@esbuild/linux-x64` missing) — `vite build`/`vitest` cannot run
  here, and reinstalling would violate the "do not alter `node_modules` on host" constraint. All
  new/changed files were written directly and reviewed for import-path and JSX correctness against
  existing sibling components, but **no automated build/test run has confirmed this compiles or
  renders** — that check is still owed, same caveat pattern as the 2026-07-18 session's Docker gap.

## Phase 1 shipped 2026-07-19 (job plumbing — SRV-5 architectural fix)

Engine: `services/monte_carlo.run_lab_simulation()` — config-driven (mode `block`|`iid`, runs
capped at `MAX_RUN_COUNT`=20k, optional `blockLen`/`ruinThresholdPct`/`seed`), writes the full
result to `labResults` itself (engine sole-writer, mirrors `backtestResults`). Seed defaults to a
deterministic hash of `sourceJobId:configHash` (not `simId`) so any re-submission of an identical
config reproduces the same draw sequence regardless of which labId it lands under. New
`routers/simulate.py` (`POST /simulate/monte-carlo`), same async-job-semantics pattern as
`routers/backtest.py` (only the failure path writes on the router side). The original
`run_monte_carlo_simulation()` (used by `leverage_sensitivity.py`) is untouched — retiring it is
Phase 2's job, alongside `SimulationResults.jsx`.

Node: new `LabResult` model (`labId`, `type`, `sourceJobId`, `config`, `configHash`, `status`,
`results` — same ownership split as `BacktestResult`: server creates the `queued` doc + updates
`status`/`error` only, engine writes `results`), `simulationQueue`/`simulation.worker.js` (mirrors
`backtestQueue`/`backtest.worker.js` exactly, including the redundant-but-harmless status
double-write), `lab.controller.js`/`lab.routes.js` mounted at `/api/v1/lab`. `configHash` is
computed server-side (`utils/labConfig.js`, pure + unit-tested) and short-circuits identical
resubmissions against a cached completed doc before ever touching the queue.

**Acceptance criteria met:** 5k-run MC on a real 38-trade backtest completed in **~1.0s**
end-to-end (well under the 5s bar — smaller trade count than the plan's 2k-trade benchmark, but
the vectorized core is the same one Phase 1a already proved out at 100x); re-submitting an
identical config returns the cached doc (`configHash` lookup, tested); a forced error (invalid
`mode`) surfaces its real message via `HTTPException`/`ApiError`, not a blanket 503 (tested);
seeded re-run reproduces an identical `equityBands`/`ruinProbability` doc regardless of labId
(tested — `test_deterministic_seed_from_source_and_confighash_not_simid`). Engine container suite
458/458 (450 + 8 new `test_lab_simulation.py`); server jest 129/129 (116 + 13 new
`labConfig.test.js`).

**Scope decisions taken (deferred, not forgotten):**
- **Cancel endpoint (`DELETE /lab/simulations/:id`) not built.** The plan's §3.1 lists it, but MC
  runs complete in ~1s — there's nothing meaningful to cancel. Revisit for Phase 3's optimizer
  jobs, which are genuinely multi-minute and where cancellation has real value.
- **Only `block` and `iid` modes implemented.** Skip-trades/cost-stress/start-date-perturbation
  (§2.1 modes 3–5) are real scope but not required by Phase 1's own acceptance criteria; add them
  when Phase 2's UI actually needs a mode picker for them, not before.
- **Progress publishing (`progress:{simId}` Redis channel, `socketEmitter.js`'s new `simulation`
  case) is wired end-to-end but the engine never actually calls `publish_progress` during the ~1s
  run** — not worth the plumbing for a sub-second job. The channel/socket-room infrastructure is
  in place for Phase 3's optimizer (genuinely long-running, needs real progress updates).

**Not yet done:** no UI consumes any of this yet — `POST /api/v1/lab/simulations` is reachable but
nothing calls it. Phase 2 (Strategy Lab page, MC tab) is the correct next slice.

**Drift-reviewer pass (2026-07-19):** clean — no stack/structure/API/boundary drift; ownership
check in `lab.controller.js` correctly scopes by `userId` and 404s cross-user `sourceJobId`.
One low-severity finding fixed same-day: `server/src/config/socket.js`'s `join`/`leave`/`disconnect`
handlers only special-cased `backtest:` rooms for the subscribe/auto-cleanup dance — added a
`simulation:` case (generalized to any `<prefix>:<id>` room) so Phase 2's UI gets the same
semantics without a second wiring pass. Inert either way today (`simulation.worker.js` already
self-subscribes independent of client room membership) but now correct for when Phase 2 lands.

> Source findings: `audit_2_quant-core.md` QNT-6/7/17 + the diagnosis in §1
> below. Scope: the Monte Carlo simulation feature (currently rendered but broken), the
> parameter optimizer (currently engine-only, **unreachable from the UI**), and a dedicated
> UI surface that combines them into one "Strategy Lab". Planning only — no code in this file
> **except the §3.3 MC-engine-core scope note directly below**, which documents what actually
> shipped against this plan.

## Scoped delivery note (2026-07-15) — read before starting Phase 1b

This plan's full scope (new BullMQ queue/worker, new `labResults` collection, new Node routes,
a brand-new "Strategy Lab" React page with wizards/charts/tables, Optuna-backed optimizer
exposure) is a multi-day feature build. In one session, only the highest-value, most
self-contained slice shipped: **the MC engine core rewrite** (§3.3's methodology), left wired
into the *existing* synchronous endpoint rather than the new job-based architecture §3.1
specifies — the SRV-5 architectural defect (multi-minute compute behind a synchronous `GET`)
is **not fixed**, only the math behind it.

**What shipped:** `engine/services/monte_carlo.py` rewritten — vectorized (numpy) circular block
bootstrap replacing the O(n_runs × n_trades) pure-Python i.i.d. loop (~100x faster: 5,000 runs
over a real 38-trade job completed in 0.22s, tested end-to-end through the live
`/backtest/run/leverage-sensitivity` endpoint); `scale_out` legs excluded from the resampling
pool (QNT-14); equity-path compounding fixed from a silent mix of additive-return-computed +
multiplicative-application to consistently additive (each trade's return is a fraction of FIXED
starting capital, so paths must sum, not compound); default run count raised 2,000 → 5,000.
Response contract preserved exactly (`ruinProbability`, `drawdownDistribution`) so
`SimulationResults.jsx` and the existing endpoint keep working unchanged; extra fields
(`finalEquityPercentiles`, `maxDrawdownPercentiles`, `meta`) added additively for the future
job-based Lab to consume without another contract break. 6 new tests
(`engine/tests/test_monte_carlo.py`): empty-trades default, scale_out exclusion, deterministic
per-jobId seeding, distinct seeds per jobId, exceedance-curve monotonicity, percentile
ordering. Full engine suite 94/94.

**What did NOT ship (everything else in this file is still an accurate plan, not done):**
- §3.1 job architecture (queue/worker/Node routes) — the endpoint is still synchronous.
  `random.Random`'s replacement with `np.random.default_rng` also changes the *exact* sequence
  of pseudo-random draws vs before (same statistical properties, different bitstream) — outputs
  for a given jobId will differ numerically from pre-rewrite runs even though both are
  "correct"; there is no committed golden baseline for MC output to diff against (same gap
  noted in Plan 9's golden-master-persistence lesson).
- §3.2 `labResults` persistence / `configHash` caching — every call still fully recomputes.
- §3.3's remaining items: block length is not user-configurable (hardcoded `max(5, √N)`); the
  i.i.d. variant is not exposed as a labeled alternative; skip-trades / cost-stress /
  start-date-perturbation modes (§2.1 items 3–5) don't exist; optimizer walk-forward/DSR/PBO/
  Optuna (§2.2, absorbs 9.6) untouched — `services/optimizer.py` is unchanged.
- §4 Strategy Lab UI (new page, wizards, fan chart, trials table, etc.) — nothing built.
- Everywhere-else items (§4.4): no backtest-page MC summary strip, `SimulationResults.jsx` not
  retired, Risk Dashboard unchanged.

**Recommended next step for whoever picks this up:** Phase 1b (job plumbing) is the correct next
slice — it's well-specified, reuses the existing BullMQ/Socket.IO backtest-job pattern this
codebase already proves out, and is the architectural fix (SRV-5) the MC-core rewrite alone
doesn't address.

**2026-07-15 — Phase 3 design source found:** the feature-gap program (plans 11-19, folded from
`workspace/next_phase/`) independently specified Phase 3's exact scope as two standalone files:
`18_walk-forward-analysis.md` (fold-split algorithm, anchored-vs-rolling train/test, OOS
stitching) and `19_bayesian-hyperopt.md` (Optuna `trial.suggest_*` adapter over the existing
`param_grid` spec, async ask/tell design). Both are now `Merged→10` — when Phase 3 is
implemented, build from those two files' math/adapter design, **not** their originally-specified
standalone sync `/optimize/walk-forward` endpoint or `walkForwardResults` collection, which
conflict with this plan's `labResults`/job-queue architecture (§3.1-3.2 above).

---

## 1. Current state & why it doesn't work

### 1.1 What exists today (wiring, verified in code)

| Layer | What | Where |
|---|---|---|
| Engine — MC | `run_monte_carlo_simulation(job_id)` — i.i.d. bootstrap over `backtestTrades`, 2,000 runs, pure-Python loop, returns ruin probability (hardcoded 30% DD) + 5-bucket DD distribution. Nothing persisted. | `engine/services/monte_carlo.py` |
| Engine — route | `POST /backtest/run/leverage-sensitivity` runs **both** leverage sensitivity (5 full backtest re-runs) **and** MC, synchronously, in one request | `engine/routers/leverage_sensitivity.py` |
| Engine — optimizer | Full grid-search API: `POST /optimize/run`, `GET /optimize/objectives`, results in `optimizationResults` | `engine/routers/optimize.py`, `services/optimizer.py` |
| Node | `GET /api/v1/risk/backtest/:id/simulation` → proxies the engine call; wraps **every** failure as `503 ENGINE_UNAVAILABLE` | `server/src/controllers/risk.controller.js:193-214` |
| Node — optimizer | **Nothing.** No route, no controller mentions "optimize" — the engine optimizer is unreachable from the product | (absence verified by repo grep) |
| Client | `SimulationResults.jsx` (backtest selector + leverage table + MC panel) — rendered on the **Risk Dashboard** (`RiskDashboard.jsx:595`), fetched by `useBacktestSimulation` (TanStack `GET`, `staleTime: Infinity`) | `client/src/components/risk/SimulationResults.jsx`, `hooks/useRiskSettings.js:41-53` |
| Client — optimizer | **Nothing.** No component references optimization | (absence verified) |

### 1.2 Why the user sees "not working" — root causes, ranked

1. **[Certain] Synchronous multi-minute compute behind a cache-forever `GET`.**
   Selecting a backtest fires a `GET` that makes the engine re-run the *full backtest five
   times* (leverage 1/2/5/10/20) plus the MC loop, inline in the HTTP request. Each re-run
   calls `ensure_candles_available` (can hit Binance REST). Node's `engineClient` allows 1h
   (SRV-5), the client axios instance sets **no timeout**, and TanStack Query retries failures
   (default 3×) — so a failure re-triggers the whole five-backtest chain. The UI shows
   "Running simulations…" indefinitely or a generic error. This is the SRV-5 anti-pattern
   (long work as synchronous HTTP) on the heaviest endpoint in the product.
2. **[Certain] The re-runs compute the wrong thing even when they succeed — QNT-17.**
   `leverage_sensitivity_runner` reads `alphaParams` / `riskParams` / `slippagePct` /
   `fundingEnabled` from the parent `backtestResults` doc — fields the runner **never
   persists**. Every scenario runs with default strategy params. The MC then resamples trades
   of the *parent* run, so the two panels describe two different configurations.
3. **[Certain] Any engine exception surfaces as `503 ENGINE_UNAVAILABLE`** (`risk.controller.js`
   catch-all) — insufficient candles, missing strategy `filePath`, a QNT-1-broken multi-symbol
   parent, anything. The UI cannot distinguish "engine down" from "this backtest can't be
   simulated", so every data problem reads as an outage.
4. **[Certain] Multi-symbol parents produce garbage inputs** (QNT-1): the trades being
   resampled are missing every SL/TP exit. MC on fiction is fiction.
5. **[Certain] Methodology defects** (QNT-7): i.i.d. resampling understates drawdown tails;
   "ruin" hardcoded at 30% DD; scale-out partial legs resampled as independent trades
   (QNT-14); additive PnL compounded multiplicatively; no percentile bands, no final-equity
   distribution — the two numbers shown are the least useful outputs an MC can produce.
6. **[Certain] Small bugs:** scenario docs persist `equityCurve: sim_res.get("equityCurve", [])`
   but `run_backtest_simulation`'s return dict has no `equityCurve` key → always `[]`;
   MC results are recomputed on every call (never persisted); the Node route does not check
   `userId` ownership of the jobId (any authenticated user can trigger 5 re-runs of anyone's
   backtest — cheap DoS lever, relates to SEC-5).

**Verdict:** don't patch `SimulationResults.jsx`. The compute belongs in a job, the MC engine
needs a rewrite (Plan 9.9 methodology), the optimizer needs to be exposed, and the UI deserves
a real surface. That is this plan.

---

## 2. Product shape — what "Monte Carlo Optimiser" means here

Three capabilities, one surface. Naming used below: **Strategy Lab** (working title).

### 2.1 Capability A — Robustness Simulator (Monte Carlo on an existing backtest)

Answers: *"how fragile is this backtest's result?"* Input: any completed backtest (jobId).
Modes (each a checkbox; all vectorized over one loaded trade/equity dataset):

1. **Trade-sequence bootstrap** (block bootstrap, default block ≈ √N trades, configurable) —
   preserves win/loss clustering that i.i.d. shuffling destroys. Outputs the *distribution* of
   equity paths.
2. **Trade resample w/ replacement** (classic bootstrap) — wider distribution; both are shown,
   worst-case of the two is highlighted (standard practice).
3. **Skip-trades randomization** — each run randomly drops k% of trades (default 5–10%):
   models missed fills / downtime / partial history. Cheap, brutally revealing for
   low-trade-count strategies.
4. **Cost stress** — re-price every trade with slippage ×(1..3) and fees ±50%, sampled per
   run: models regime changes in execution quality.
5. **Start-date perturbation** (equity-curve mode) — begin compounding at random offsets:
   kills strategies whose profit is one lucky launch window.

### 2.2 Capability B — Parameter Optimizer (gives the dead `/optimize` API a home)

Answers: *"which params should I run?"* — but reported honestly (Plan 9.6 methodology is a
prerequisite and is *delivered through this surface*):

- Grid / random / **Optuna TPE** search over the strategy's typed `PARAMS` schema (the schema
  already exists — the wizard can render min/max/step per param automatically).
- **Walk-forward split** is the default execution mode: optimize in-sample, score
  out-of-sample, roll; the UI reports the *stitched OOS* metrics, with the in-sample numbers
  demoted to a secondary column.
- Overfitting panel: **Deflated Sharpe Ratio** and **PBO/CSCV estimate** computed over the
  trial set; a min-trades filter (default 30) excludes lucky-few-trades combos from ranking.

### 2.3 Capability C — the "Monte Carlo optimiser" proper (A × B)

This is the piece that makes the name accurate — **MC-scored selection**: candidates from
Capability B are not ranked by their point metric but by their **Monte Carlo percentile
outcome** (default: 5th-percentile net profit and 95th-percentile max drawdown from a
block-bootstrap of each candidate's OOS trades). Concretely, it *optimizes*:

| Target | How | Output |
|---|---|---|
| **Strategy params** | rank optimizer trials by MC-p5 profit / MC-p95 DD instead of raw Sharpe | robust param set + fragility gap (point metric vs MC-p5) per combo |
| **`risk_pct` (position sizing)** | search the largest risk_pct such that `P(maxDD > X) < Y` (X, Y user-set; e.g. P(DD>30%)<5%) over resampled paths — a drawdown-constrained fractional-Kelly stand-in | recommended risk_pct + the full P(DD)–vs–risk_pct curve |
| **Leverage** | replace the point-estimate 5-row leverage table with the same MC bands per leverage level | leverage row = median + p5/p95 band, not one number |
| **Ruin threshold policy** | user-defined ruin (equity floor or DD), reported as probability with CI | honest "probability of ruin" |

Sizing/leverage answers are *simulation-derived recommendations*, never auto-applied — the
user copies them into session/backtest config explicitly (keeps the human sign-off, matches
the platform's risk-settings hierarchy).

---

## 3. Architecture & integration

### 3.1 Execution model — jobs, not request/response

Reuse the **existing BullMQ backtest pattern** (queue → worker → engine → Redis progress →
Socket.IO), which already works end-to-end for backtests:

- New queue `simulationQueue` (Node, `server/src/services/`), worker mirrors
  `workers/backtest.worker.js`.
- Node routes (all POST-to-start, GET-to-read; JWT + ownership check on the parent jobId):
  - `POST /api/v1/lab/simulations` `{jobId, config}` → enqueue MC robustness run
  - `POST /api/v1/lab/optimizations` `{strategy, range, paramGrid|auto, objective, walkForward, mcScoring}` → enqueue optimization
  - `GET /api/v1/lab/simulations/:simId` / `GET /api/v1/lab/optimizations/:optId` → status+results
  - `GET /api/v1/lab/…?list` → history lists for the page
  - `DELETE /…/:id` → cancel (Redis cancel channel, same as backtest cancel)
- Engine endpoints (thin, async-job semantics like `backtest/run`):
  - `POST /simulate/monte-carlo` — new router; body = `{jobId, config}`; publishes progress on
    `progress:{simId}`.
  - `POST /optimize/run` — **exists**; extend with walk-forward + MC-scoring config and
    progress publishing (it already has a `progress_callback` param, unused).
  - Retire `POST /backtest/run/leverage-sensitivity` after migration (leverage becomes an MC
    mode / optimizer axis; the endpoint's synchronous double-duty design is the root defect).
- Progress: engine publishes `{pct, message, stage}`; worker relays to `user:<id>` room —
  identical plumbing to backtest progress, zero new infrastructure.

### 3.2 Persistence

New Mongo collection `labResults` (engine writes, Node reads — same ownership rule as
`backtestResults`):

```
{
  labId, type: "monte_carlo" | "optimization",
  userId, sourceJobId | strategyName+range,
  config: { modes, runs, blockLen, ruinDef, seed, costStress, … },   // FULL config, always
  configHash,                       // idempotency: same source+config → return cached
  engineVersion, strategyHash,      // reproducibility (pairs with Plan 3's version pinning)
  status, progressPct, error,       // job lifecycle
  results: {
    // MC: percentile equity bands (downsampled ≤500 pts × 5 bands), finalEquity histogram,
    //      maxDD histogram, P(DD>x) curve, ruinProb ± CI, per-mode breakdown
    // OPT: trials table (params, IS/OOS metrics, DSR, mc_p5, rank), best-robust pick,
    //      walk-forward window map, PBO estimate
  },
  createdAt, completedAt
}
```

Design rules: results are **projections of a stored config** (fixes QNT-17's class of bug by
construction — nothing is ever re-derived from unpersisted parent fields); deterministic
`seed` stored so any run is exactly reproducible; `configHash` short-circuits duplicate
submissions (fixes today's recompute-on-every-select).

### 3.3 Engine implementation notes (for the implementing session)

- **Vectorize:** simulate as a matrix — `(n_runs × n_trades)` indices sampled once,
  `np.cumprod` / `np.cumsum` over axis 1; 10k runs × 2k trades is ~10⁷ floats ≈ well under 1s.
  The current `random.Random` per-trade Python loop is the wrong tool by ~100×.
- **Inputs:** completed **round-trips only** (exclude `scale_out` legs — QNT-14) fetched once;
  equity-based returns (`pnl/capital` additive **or** log-return compounding — pick one,
  document it; do not mix as today).
- **Block bootstrap:** circular block sampling, block length default `max(5, round(√N))`,
  user-overridable; expose the i.i.d. variant as a labeled alternative, not the default.
- **Runs:** default 5,000; hard cap 20,000 (tail metrics stabilize by 10k — more is waste).
- **Optimizer:** load candles **once** per optimization (QNT-6 operational fix); per-trial
  summary persistence only — no `backtestResults`/`backtestTrades` writes per combo; Optuna as
  an engine dependency (needs root+engine CLAUDE.md dependency-rule update); walk-forward as a
  scheduling layer over `run_backtest_simulation` with per-window `(train, test)` date pairs.
- **Guardrails:** refuse MC on parents flagged stale (multi-symbol pre-9.1 results); refuse
  optimization grids > N_max combos without explicit `maxCombinations`; min-trades filter in
  ranking on by default.

### 3.4 Sequencing dependency on Plan 9 (hard)

- **9.1 first** (multi-symbol exit bug): MC/optimizer outputs on multi-symbol data are
  meaningless until fixed.
- **9.3 first** (persist full run config): the Lab's "re-run with same config" and the
  leverage-band mode both read the persisted config.
- 9.6/9.9 (optimizer honesty, MC methodology) are **absorbed into this plan** — implement them
  here rather than twice; Plan 9 keeps the pure-bugfix steps.

---

## 4. UI — dedicated page: **Strategy Lab**

**Recommendation: dedicated page** (new route `/lab`, nav item between Backtest and Risk),
not a Backtest-page section. Reasons: (a) the workflows are multi-minute jobs with history —
they need list/detail states, not a card; (b) the existing Backtest page is already a
1,760-line god component (CLI-1) — nothing more goes in it; (c) optimizer needs a wizard of
its own. The Backtest report keeps only a **compact MC summary strip** (see 4.4).

### 4.1 Page layout

Two tabs (mirrors the two job types), each = left config/list rail + main results canvas —
same visual grammar as the Backtest page (dark, `emerald-400`/`red-400` P&L invariant, Radix
tabs/cards, lightweight-charts/recharts already in the stack):

```
┌──────────────────────────────────────────────────────────────────┐
│  STRATEGY LAB          [ Robustness (MC) ]  [ Optimizer ]        │
├──────────────┬───────────────────────────────────────────────────┤
│ New Run ▸    │  RESULTS CANVAS (per selected run)                │
│  (wizard)    │                                                   │
│ ──────────── │  MC tab: fan chart · histograms · P(DD) curve ·   │
│ Run history  │          ruin card · mode breakdown · verdict     │
│  ⏳ running   │  OPT tab: trials table · IS-vs-OOS scatter ·      │
│  ✔ done      │          param heatmap · walk-forward map ·       │
│  ✖ failed    │          robust-pick card                         │
└──────────────┴───────────────────────────────────────────────────┘
```

### 4.2 Robustness (MC) tab — result components

1. **Equity fan chart** (headline visual): p5/p25/median/p75/p95 bands over trade sequence,
   original backtest equity overlaid as a line. Bands ≤500 downsampled points each.
2. **Final-equity histogram** + capital marker (P(loss) annotated).
3. **Max-drawdown histogram** + **P(DD > x) exceedance curve** with the user's ruin threshold
   as a draggable marker (replaces today's 5 fixed buckets).
4. **Ruin card:** `P(ruin) = 3.2% ± 0.5%` with the ruin definition printed under it, red/amber/
   emerald severity coloring.
5. **Mode breakdown table:** one row per enabled mode (block, i.i.d., skip-trades, cost-stress,
   start-date) × (median profit, p5 profit, p95 DD) — makes "which perturbation breaks it"
   readable at a glance.
6. **Verdict strip:** point-estimate vs MC-p5 gap ("your backtest's +43% has a 1-in-20 outcome
   of −12% under cost stress") — the sentence users actually need.
7. Config drawer (read-only for a done run): every knob + seed + engineVersion — reproducible.

### 4.3 Optimizer tab — result components

1. **Trials table** (virtualized): params, OOS Sharpe/profit/DD, trade count, DSR, MC-p5,
   rank; in-sample columns collapsed by default; min-trades-failed rows greyed.
2. **IS-vs-OOS scatter** — the overfitting picture (points far below the diagonal = curve-fit).
3. **Param heatmap** (2 selected axes) / parallel-coordinates for >2 params.
4. **Walk-forward window map:** per-window IS/OOS bars across time.
5. **Robust-pick card:** the MC-scored winner with copy-to-backtest / copy-to-session actions
   (fills the existing wizards' param fields — integration point, no auto-apply).
6. **Overfitting panel:** DSR, PBO estimate, trial count, plain-language interpretation.
7. New-run wizard: strategy → symbol/TF/range (reuse `NewBacktestWizard` steps) → param grid
   auto-rendered from the `PARAMS` schema (min/max/step prefilled from schema bounds) →
   objective + walk-forward + MC-scoring toggles → cost/estimate preview (combo count × est.
   runtime) with a hard warning above the cap.

### 4.4 Everywhere else

- **Backtest report page:** one compact strip on the Overview tab — `MC p5/median/p95 final
  equity · P(ruin)` — fed by an auto-enqueued default-config MC when a backtest completes
  (cheap: <1s vectorized), deep-linking to the Lab for the full analysis. This is what the
  user currently believes the backtest page should show, made real.
- **Risk Dashboard:** `SimulationResults.jsx` is **retired**; its slot links to the Lab. The
  leverage table returns as an MC-banded view inside the Lab (per §2.3).
- **States:** every run shows queued → running (pct + stage from Socket.IO) → done/failed;
  failures show the engine's actual error string (no more blanket `503 ENGINE_UNAVAILABLE` —
  Node passes engine error bodies through with a proper status split: 4xx data problems vs
  5xx engine problems).

---

## 5. Optimizations (performance & system)

1. **Vectorized MC** (§3.3): ~100× over the current loop; enables 5–10k runs interactively.
2. **Load-once data plane:** candles and trades fetched once per job, shared across all
   modes/trials (today: per-combo candle re-fetch + per-call trade re-fetch).
3. **`configHash` result cache:** identical request → instant cached result (today: full
   recompute per dropdown selection).
4. **Optuna TPE + median pruning** instead of exhaustive grid: order-of-magnitude fewer
   backtests for equal search quality; prunes hopeless combos after the first walk-forward
   window.
5. **Progress + cancel** on both job types via existing Redis channels (optimizer currently
   publishes to channels nobody consumes; wire them to the worker instead).
6. **No junk persistence:** per-trial summaries only; temp `backtestResults` writes (current
   leverage runner behavior, cleaned up in `finally`) eliminated rather than cleaned.
7. **Downsampled band storage** (≤500 pts × 5 bands) keeps `labResults` docs ~50 KB, far under
   BSON limits, chart-ready without client processing.
8. **Concurrency guard:** one running lab job per user (queue-level), protecting the
   single-process engine event loop (until Plan 6's decomposition); optimizer trials
   parallelizable later via a process pool without API changes.

---

## 6. Phases & acceptance criteria

**Phase 0 — prerequisites (Plan 9):** 9.1 + 9.3 shipped. Gate: multi-symbol SL/TP test green;
`backtestResults` carries full config.

**Phase 1 — MC engine rewrite + job plumbing.** New `/simulate/monte-carlo` router, vectorized
block-bootstrap engine, `labResults` collection, `simulationQueue` + worker + Socket.IO
progress, Node routes with ownership checks.
*Accept:* 5k-run MC on a 2k-trade backtest completes < 5 s end-to-end; re-submitting identical
config returns cached; forced engine error surfaces its real message in the API response;
seeded re-run reproduces byte-identical results doc (minus timestamps).

**Phase 2 — Strategy Lab page, MC tab.** Route/nav, run wizard, history rail, fan chart,
histograms, exceedance curve, ruin card, verdict strip. Retire `SimulationResults.jsx` +
its `GET`-with-side-effects endpoint.
*Accept:* full flow (select backtest → configure → watch progress → results render) works on a
seeded strategy; component tests for the results canvas (harness from Plan 2); old endpoint
returns 410 with a pointer.

**Phase 3 — Optimizer exposure + honesty layer.** Node proxy for `/optimize`, walk-forward
scheduling, min-trades filter, DSR/PBO, Optuna backend, per-trial-summary persistence,
Optimizer tab UI (table, scatter, heatmap, wizard).
*Accept:* an optimization over a seeded strategy reports stitched OOS metrics + DSR; grid >cap
rejected with a clear message; trials table renders 500+ trials without jank (virtualized).

**Phase 4 — MC-scored selection + sizing/leverage recommendations (§2.3).** MC pipeline runs
over top-k optimizer trials; risk_pct search; leverage bands; robust-pick card wired to the
backtest/session wizards' param prefill. Backtest-page MC summary strip + auto-enqueue.
*Accept:* robust pick differs from raw-metric pick on at least one seeded strategy (fragility
gap demonstrated); leverage view shows bands, not points; copy-to-backtest round-trips params.

## 7. Open questions

1. Page name — "Strategy Lab" vs "Optimizer" vs "Simulations" (naming shows up in nav + docs).
2. Is the auto-enqueued post-backtest MC on by default, or per-user setting? (Costs ~1 s CPU
   per completed backtest — recommend on by default, off switch in Settings.)
3. Optuna adds a real dependency to the engine image — accept, or ship Phase 3 with
   grid+random first and TPE as 3b? (Recommend: accept; it is the payoff of the phase.)
4. Access gating: Lab open to all authenticated users (like backtest) or behind `algoAccess`?
   Optimizations are the most compute-hungry thing a user can trigger — recommend open but
   with the per-user concurrency=1 guard + stricter rate limit (ties into SEC-5 work).
5. Do leverage bands fully replace `backtestLeverageScenarios`, or keep that collection as the
   band cache? (Recommend replace; migrate the Risk Dashboard link in the same PR.)

## Handoff template

```
Next session: Plan 10 Phase N done — [what changed], [accept-criteria status],
[UI screenshots verified y/n], [next phase], [open questions touched].
```
