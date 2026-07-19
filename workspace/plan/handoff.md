# Session Handoff Log

Resume prompts for cross-session continuity (root `CLAUDE.md` Rule G / `AGENTS.md` → Session Handoff).

**Format rules:**
- Newest entry on top: `## <date> — <title> — <status>` with **Goal / Done / Files changed / Open questions**.
- Keep at most the **3 most recent entries**. When adding a new one, delete the oldest — git history is the archive. This file must stay a short resume prompt, not a project log.

---
## 2026-07-19 — Plan 10 Phase 3e shipped (Deflated Sharpe Ratio) — live-verified, 1 real unrelated bug fixed

**Goal:** user said "move on to next fix/plan" after Phase 3b. DSR/PBO was the next Plan 10 item,
deferred across 4 prior sessions specifically for lack of pytest access to verify the
normal-CDF/inverse-CDF primitive DSR needs — this session had that access, so it shipped instead
of deferring a 5th time.

**Shipped:** new `engine/services/stats.py` — `norm_cdf` (exact, `math.erf`), `norm_ppf` (Acklam's
rational approximation + Halley refinement, no scipy dep), `deflated_sharpe_ratio()`/
`expected_max_sharpe()` (Bailey & López de Prado 2014). Verified via round-trip
(`norm_cdf(norm_ppf(p))==p`) + published reference quantiles, plus property tests (DSR decreases
as trial count grows for the same apparent Sharpe — the actual deflation behavior, numerically
checked not just asserted). Trade-level DSR (not the paper's per-period form): the Sharpe-like
term is `sqn/sqrt(totalTrades)` (SQN already trade-level, no new metric needed for it); two NEW
metrics (`SkewnessStat`/`KurtosisStat`, trade-PnL, RAW non-excess kurtosis) feed the non-normality
correction — golden-master-verified additive-only. `walk_forward.py` attaches `fold.dsr` per fold.
`FoldResultsTable.jsx` gained a DSR column. PBO stays explicitly deferred (needs per-trial OOS
data this architecture doesn't collect — real, separate scope).

**Real, UNRELATED bug found and fixed via live testing:** verifying DSR through the actual `/lab`
Optimizer wizard (AdaptiveTrend, ~12 checked params) froze the whole engine container.
`optimizer.py`'s `_build_param_grid` materialized the FULL cartesian product
(`list(itertools.product(...))`) before capping to `max_combinations` — AdaptiveTrend's real
wizard-default grid is ~472 TRILLION combos, and building that list hangs/OOMs a single-process
container (confirmed: `docker stats` near-zero CPU during the hang, container health flipped
`unhealthy`, even `/health` from inside the same container timed out). Pre-existing, unrelated to
DSR, a real production risk (any user checking several wide-range params could freeze the shared
engine for everyone). Fixed: compute `total` via cheap multiplication (no materialization); when
capped, sample indices via `random.sample` on a lazy `range` (no materialization) and decode each
directly to its combo (`_decode_combo_index`, mixed-radix, verified against real
`itertools.product` output). No test had existed for `_build_param_grid` before this session.

**Live-verified, real Docker + browser access:** engine 538/538 (+50 new tests across
`test_stats.py`/`test_skew_kurtosis.py`/`test_param_grid.py`/2 walk_forward tests), server jest
156/156, client build clean. Golden master zero-drift outside the 2 new metric keys. Direct
`curl POST /simulate/optimize` against real cached BTCUSDT candles — real DSR values (57–69%
across runs). Then the actual regression repro: AdaptiveTrend's full default grid through the real
`/lab` wizard — froze pre-fix (confirmed via `docker stats`/health), completes in ~4s post-fix,
renders cleanly, zero console errors. Engine restarted mid-session to clear hang-accumulated state;
confirmed healthy afterward.

**Files changed:** new `engine/services/stats.py`, `engine/tests/test_stats.py`; `engine/services/
metrics.py` (+SkewnessStat/KurtosisStat); new `engine/tests/test_skew_kurtosis.py`;
`engine/services/optimizer.py` (+skewness/kurtosis to per-trial whitelist, `_build_param_grid`/
`_decode_combo_index` rewrite); new `engine/tests/test_param_grid.py`; `engine/services/
walk_forward.py` (+`_compute_fold_dsr`/`_trade_level_sharpe`, `fold.dsr`); `engine/tests/
test_walk_forward.py` (+2 tests); `client/src/components/lab/FoldResultsTable.jsx` (+DSR column);
`client/src/pages/StrategyLab.jsx` (disclosure note updated). Docs: `API_CONTRACTS.md`,
`CURRENT_STATE.md`, `engine/CLAUDE.md`, `10_monte-carlo-strategy-lab.md`, `0_tracker.md`.

**Next session:** (1) PBO needs a genuinely new architectural piece (OOS-evaluate every trial, not
just fold winners) — scope it properly, don't bolt it onto the existing per-fold-winner-only data
model. (2) Phase 4 (MC-scored selection) is the next undone Plan 10 phase. (3) Untouched backlog:
21.5c (batched reconcile, P2/small), Plan 6/7 (engine/server decomposition, P2), Plan 23
(MarginSurge strategy), Plan 8 (governance cleanup, P3), Plans 5/22/24 (shipped, waiting on
human-observed live Testnet re-verification).

---
## 2026-07-19 — Plan 10 Phase 3b shipped (Optuna/TPE Bayesian search) — live-verified, 1 real pre-existing bug fixed

**Goal:** user said "Phase 3b — Optuna/TPE swap proceed", the next item on the tracker after last
session's Phase 3d.

**Shipped:** `engine/services/optimizer.py` gained `run_bayesian_optimization()` (ask/tell async
loop over optuna's `TPESampler`, seeded for reproducibility) + `_suggest_params()` adapter reusing
the existing `param_grid` JSON spec unchanged for grid and Bayesian (Plan 19's own design). Shared
ranking/min-trades-filter/persistence tail extracted into `_finalize_optimization()` so both
methods return byte-identical shapes (`method: "grid"|"bayesian"` field added to both).
`walk_forward.py`'s per-fold train step now dispatches on `config.method`, with a
deterministic-but-distinct TPE seed per fold. `POST /optimize/run` + `POST /lab/optimizations`
gained `method`/`nTrials`/`seed`. `WalkForwardWizard.jsx` gained a Grid/Bayesian toggle + trials
input. `optuna` added to `engine/requirements.txt`, image rebuilt (`docker compose build engine`),
confirmed it survives a container restart.

**Real, pre-existing bug found and fixed (not new to Bayesian):** live-testing hit
`ValueError: Out of range float values are not JSON compliant` whenever any trial errored — this
was grid's own defect too (never exercised because `/optimize/run` has no Node route mounted and
no prior session hit an erroring combo through `/lab/optimizations` with live browser access).
Fixed at `_finalize_optimization()`'s shared tail: non-finite loss → `null` before JSON, for both
`results`/`best`, both methods. Updated `walk_forward.py`'s `best.get("loss")` check to
short-circuit on `None` before `math.isfinite()` (which raises `TypeError` on non-float).

**Live-verified, real Docker + browser access this session:** engine 488/488 (+16 tests), server
jest 156/156 (+8), client `vite build` clean. Direct `curl POST /optimize/run` with
`method=bayesian` against real cached BTCUSDT candles + MicroScalper (one trial genuinely errored,
correctly sanitized). Full `/lab` Optimizer wizard browser session (AdaptiveTrend/BTCUSDT,
Bayesian, 5 trials × 2 folds) — completed end-to-end via BullMQ→engine→Mongo, both folds correctly
reported "skipped — no eligible combo" (real search-budget tradeoff, not a bug), results canvas
rendered cleanly, zero console errors. Also verified `POST /simulate/optimize` directly with a
config that DID produce a winning combo (real degradation ratio computed). All test data cleaned
up from MongoDB Atlas after.

**Files changed:** `engine/requirements.txt` (+optuna), `engine/services/optimizer.py`
(`run_bayesian_optimization`, `_suggest_params`, `_finalize_optimization` shared tail, JSON-safety
fix), `engine/routers/optimize.py` (+method/nTrials/seed), `engine/services/walk_forward.py`
(+method dispatch, +seed, None-safe best-loss check), new
`engine/tests/test_bayesian_optimizer.py` (18 tests), `engine/tests/test_walk_forward.py` (+2
tests), `server/src/utils/labConfig.js` (+method/nTrials/seed + `MAX_N_TRIALS`),
`server/src/utils/__tests__/labConfig.test.js` (+8 tests), `client/src/components/lab/
WalkForwardWizard.jsx` (method toggle, trials input), `client/src/components/lab/
DegradationVerdict.jsx` (+method prop), `client/src/pages/StrategyLab.jsx` (wire method prop,
fixed stale "Optuna not built yet" note). Docs: `API_CONTRACTS.md`, `CURRENT_STATE.md`,
`engine/CLAUDE.md`, `10_monte-carlo-strategy-lab.md`, `0_tracker.md`.

**Next session:** (1) DSR/PBO still needs a session that can numerically verify the CDF math
before shipping it — don't guess at the formula. (2) Phase 4 (MC-scored selection) is the next
undone Plan 10 phase. (3) Untouched backlog: 21.5c (batched reconcile, P2/small), Plan 6/7
(engine/server decomposition, P2), Plan 23 (MarginSurge strategy), Plan 8 (governance cleanup,
P3), Plans 5/22/24 (shipped, waiting on human-observed live Testnet re-verification).

---
## 2026-07-19 — Real Docker access this session: verified Phases 2/3a/3c, shipped Phase 3d fully (persistence + UI), found 2 live bugs

**Goal:** the prior session's handoff (Phase 3c entry below) flagged verification as top priority
— three sessions in a row had shipped Plan 10 code with zero compilation/test execution. This
session had real `docker compose` access AND a working Chrome browser session already logged into
the app, so it verified with actual test execution and actual UI clicks, not just code review.

**Verified (all real):** engine full suite 472/472, server jest 148/148, client `vite build` clean.
Beyond unit tests: fired `POST /simulate/optimize` directly against cached BTCUSDT 1d candles +
MicroScalper (curl, bypassing Node) — confirmed correct fold date-boundary math and MongoDB
persistence. Then went further and drove the actual `/lab` Optimizer wizard in a real browser
against the real running stack, which is what caught the two bugs below — neither would have
been caught by unit tests or by curling the engine directly.

**Environment finding, not a Plan 10 defect:** the engine/server's `MONGO_URI` points at a live
MongoDB Atlas cluster (`*.wbzezj5.mongodb.net`), not the local `enma_trading_platform-mongodb-1`
docker-compose container — that container holds no real data for this project. Verify DB state via
`docker exec enma_trading_platform-engine-1 python -c "from config.mongo import get_database; ..."`,
not `mongosh` against the local container.

**Shipped: Plan 10 Phase 3d, fully — persistence + UI.** Engine: each fold in `walk_forward.py`'s
return now carries a `trials` key (`train_result["results"]` verbatim — `run_optimization` already
computed this, it was just discarded down to `best` before). Client: new
`TrialsExplorer.jsx` — sortable per-fold trials table + a 2-param loss heatmap when the grid varies
exactly 2 params. Deliberately no IS-vs-OOS scatter (only each fold's winner gets an OOS eval, so
no per-trial OOS value exists to plot honestly).

**Two real bugs found ONLY by live-clicking the actual wizard, fixed same session:**
1. **`WalkForwardWizard.jsx` never sent `exchange` in its submit payload** — `NewBacktestWizard.jsx`
   hardcodes `exchange: 'Binance Futures'`, this file just omitted the field entirely. Every real
   submission through the UI had been 400ing against `buildWalkForwardConfig`'s required-field
   check since Phase 3c shipped, unnoticed because no session before this one had live
   browser+backend access to click the button. Fix: added a hardcoded `exchange` state matching
   the backtest wizard's convention.
2. **JSON serialization crash (500) once #1 was fixed and a real job ran:** `optimizer.py`'s
   error/ineligible combos carry `loss=float("inf")` by design — previously only `best` (already
   filtered to finite loss) ever reached the router, so this was never exercised. Persisting every
   trial means every trial's `loss` now hits `json.dumps()` at the FastAPI response layer, which
   rejects inf/nan outright. Fix: `_json_safe_trials()` sanitizes non-finite `loss` to `None`
   before a fold's `trials` list is built. New regression test calls `json.dumps()` directly on the
   result — the class of bug pure unit tests (which never serialize) can't catch.

**Live-verified end-to-end after both fixes:** ran a real 2-fold/8-combo walk-forward job through
the actual `/lab` Optimizer wizard → BullMQ → engine → MongoDB round trip; confirmed the full
results canvas renders (degradation verdict, stitched OOS, fold table, trials table with correct
rank/error handling), no console errors. Test runs cleaned up from the DB after. Engine suite
472/472 with the new regression test.

**Files changed:** `engine/services/walk_forward.py` (+`trials` per fold, +`_json_safe_trials`),
`engine/tests/test_walk_forward.py` (+3 tests), new `client/src/components/lab/
TrialsExplorer.jsx`, `client/src/components/lab/WalkForwardWizard.jsx` (`exchange` field fix),
`client/src/pages/StrategyLab.jsx` (wire in TrialsExplorer), `client/src/components/lab/
FoldResultsTable.jsx` (stale-comment fix), `server/src/models/LabResult.js` (stale-comment fix).
Docs: `API_CONTRACTS.md`, `CURRENT_STATE.md`, `client/CLAUDE.md`, `server/CLAUDE.md`,
`engine/CLAUDE.md`, `10_monte-carlo-strategy-lab.md`, `0_tracker.md`. First commit (Phases 1-3d
minus the two live-found fixes) pushed to `dev` as `4c3bb88`; the fixes above are uncommitted,
pending this session's next commit.

**Next session:** (1) Phase 3b (Optuna/TPE swap — needs a new pip dependency, update
`engine/CLAUDE.md` + root `CLAUDE.md` stack table per Rule F when adding it). (2) DSR/PBO still
needs a session that can numerically verify the CDF math before shipping it — don't guess at the
formula. (3) Consider a param heatmap for >2-param grids (currently only renders at exactly 2) if
the team wants it — would need a different visualization (e.g. parallel coordinates) since a 2D
grid can't represent more axes. (4) Untouched from earlier backlog: 21.5c (batched reconcile,
P2/small), Plan 6/7 (engine/server decomposition, now unblocked, P2), Plan 23 (MarginSurge
strategy, backtest-only work can start now), Plan 8 (governance cleanup, P3), Plans 5/22/24
(shipped, waiting on a human-observed live Testnet re-verification session).
