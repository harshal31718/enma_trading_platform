# Plan 10 — Monte Carlo Optimiser & Strategy Lab

**Status:** **SHIPPED IN FULL, 2026-07-19/20 — no remaining scoped-but-unbuilt items.** MC engine
core shipped 2026-07-15 (Phase 1a), job plumbing shipped 2026-07-19 (Phase 1b), Strategy Lab MC tab
shipped 2026-07-19 (Phase 2), walk-forward job plumbing shipped 2026-07-19 (Phase 3a), Optimizer
tab UI shipped 2026-07-19 (Phase 3c), Phase 3d (engine persistence + client trials table), Phase 3b
(Optuna TPE Bayesian search), Phase 3e (Deflated Sharpe Ratio) — all shipped and live-verified
2026-07-19. Phase 4a (MC-scored trial selection) + Phase 4b (risk_pct/leverage search,
copy-to-backtest, backtest-page MC summary strip) shipped 2026-07-19, real-Docker-verified the same
day (engine 551/551, server jest 169/169, client `vite build` clean + vitest 11/11). **PBO
(Probability of Backtest Overfitting, CSCV) — the plan's last item — shipped and real-Docker-
verified 2026-07-19/20 (see "PBO shipped" section below): engine 567/567 (+16 new), server jest
181/181 (+12 new), client build clean, live-verified against the real `/lab` PBO tab.** ·
**Priority:** P1 ·
**Depends on:** 9 (steps 9.1/9.3 for correct inputs — both Shipped; 9.6/9.9 are absorbed here) ·
**Related:** 2 (jobs/CI), 7 (client decomposition)

## PBO shipped 2026-07-19/20 (Probability of Backtest Overfitting, CSCV — closes Plan 10 out)

**Why now:** the last remaining Plan 10 item, previously scoped-but-not-started (see "Scoping
notes" below, still accurate as historical record of the two open architectural questions this
design resolves). User said "move and implement."

**Design decisions (resolving the scoping notes' two open questions), verified against the actual
code before writing anything:**
1. **Subsample source: PBO's own independent block scheme, NOT walk-forward's fold boundaries.**
   `run_lab_pbo()` calls `optimizer.run_optimization`/`run_bayesian_optimization` DIRECTLY over the
   FULL requested date range — no fold splitting at all — to get N candidates, each backtested once
   over the whole range. The date range is then partitioned into `nBlocks` (even, default 8, capped
   12) contiguous, equal-candle-count blocks, PBO's own scheme, matching CSCV's actual requirement
   (symmetric train/test combinatorics over one shared partition, not walk-forward's sequential
   rolling/anchored refit).
2. **Per-trial trade data already existed — confirmed by reading `optimizer.py`, not assumed.**
   Every combo `run_optimization`/`run_bayesian_optimization` scores already gets its own full
   backtest with trades bulk-persisted to `backtestTrades` under `{job_id}_c{idx:04d}` (grid) /
   `_t{idx:04d}` (bayesian) — no new persistence path needed. The one real gap: the returned trial
   dict didn't carry that job_id (lost once `_finalize_optimization` re-sorts by loss). **Fixed at
   the source**, not worked around: both search functions now include `"jobId": combo_job_id` in
   every scored trial dict — small, additive, backward-compatible.

**This closes the "3,500 extra backtests" cost the scoping notes flagged for the naive approach**:
only the initial N candidates are ever backtested (identical cost to a plain optimization run).
Every one of CSCV's `C(nBlocks, nBlocks/2)` train/test combinations is scored by slicing each
candidate's ALREADY-fetched trade list by block membership (via `entryAt`, parsed back from its
persisted ISO-string form) and recomputing a trade-level statistic in memory (numpy) — zero
additional `run_backtest_simulation` calls beyond the N candidates.

**Scoring statistic:** the same trade-level Sharpe-like proxy (`mean(pnl/capital)/std(pnl/capital)`)
already established for DSR (Phase 3e) and the stitched-OOS aggregate — a full-range annualized
Sharpe can't be recomputed from an arbitrary trade subset without re-running a backtest, so this is
a deliberate, documented choice, not an oversight.

**A real bug caught during design, before any code was trusted:** CSCV's OOS ranking must be
ASCENDING (rank 1 = worst performer, rank N = best) — this isn't cosmetic, it's required for
`P(logit<=0)` to mean what PBO's own definition says it means (the IS-selected candidate performed
at/below the OOS median = overfit signal). An initial descending-rank draft would have silently
INVERTED the entire statistic — a candidate that performed BEST out-of-sample would have counted as
"overfit." Caught while hand-deriving two exact-value test scenarios (not just directional
assertions) before trusting the implementation: a perfectly anti-correlated IS/OOS construction
(`pbo == 1.0` exactly) and a strictly/uniformly ordered construction (`pbo == 0.0` exactly) — both
asserted to the exact float value in `engine/tests/test_pbo.py`, not just "high" or "low."

**Honesty guards, same stance as DSR/Phase 4a:** a block-combination where the IS-selected
candidate can't be determined (no candidate has enough train-side trades), or a candidate with no
computable OOS statistic in a given split (ranks worst by construction, not excluded — "no OOS
signal" is itself informative), never produces a fabricated logit. If every combination is
uncomputable, `pbo` is `null` with `insufficientData: true`.

**Server:** new `buildPBOConfig()` (`labConfig.js`) — deliberately NO `mode`/`nFolds`/`trainRatio`
fields (unlike `buildWalkForwardConfig`), since PBO isn't a walk-forward variant; same
`riskLeverageGrid` validation reused, new `nBlocks` (even, `MIN_N_BLOCKS`=4, `MAX_N_BLOCKS`=12 —
must match the engine's own cap exactly). New `pboQueue.js`/`pbo.worker.js` (mirrors
`optimizationQueue.js`/`optimization.worker.js` exactly), `POST/GET /api/v1/lab/pbo[/:labId]`,
`LabResult.type` enum gained `'pbo'`, `config/socket.js`/`socketEmitter.js` gained the `pbo:` room
prefix (same three-way pattern as `backtest:`/`simulation:`/`optimization:`).

**Client:** new "Overfitting (PBO)" third tab on `/lab`. `PBOWizard.jsx` mirrors
`WalkForwardWizard.jsx`'s paramGrid/riskLeverageGrid/method/objective shape (deliberately NOT a
clone with fold fields removed — a fresh component reflecting PBO's actual shape) plus an `nBlocks`
control with a live `C(n, n/2)` combination-count preview. `PBOVerdictCard.jsx` clones
`RuinCard.jsx`'s severity-card template (PBO thresholds: <20% low / 20-50% elevated / ≥50% high —
a documented judgment call, not from a specific citation, since the CSCV paper itself doesn't
prescribe a universal cutoff). `PBOCandidatesTable.jsx` mirrors `TrialsExplorer.jsx`'s sortable
table shape without the fold-switcher (PBO has one flat candidate list, not per-fold trials).

**Verified with real Docker access, this session:** engine container pytest **567/567** (551 + 16
new `test_pbo.py` cases — pure unit tests for `_block_boundaries`/`_assign_block`/
`_stat_from_returns`, the two hand-derived exact-value CSCV scenarios described above, an
insufficient-data guard test, a missing-OOS-data-ranks-worst-not-excluded test, and 6 `run_lab_pbo`
wiring tests against fakes). Server jest **181/181** (169 + 12 new `buildPBOConfig` cases). Client
`vite build` clean, `vitest` 11/11. **Live-verified end-to-end, real logged-in browser session
against the actual `/lab` PBO tab**: submitted a real run (MicroScalper/BTCUSDT/1h/2023, 6
candidates, 4 CSCV blocks, grid search) through the full BullMQ→engine→MongoDB pipeline; inspected
the persisted `labResults` doc directly (5 eligible candidates after one combo errored, `pbo: 0.0`,
`nEvaluated: 5`, `nSkipped: 1`) to confirm the shape; `PBOVerdictCard`/`PBOCandidatesTable` rendered
the real result correctly (0.0% / "LOW" severity, full candidate breakdown with rank/params/Sharpe/
trades) with zero console errors. One real copy bug found and fixed during this same live pass
(missing space in the wizard's block-count explainer text — `"4-vs-4train/test split"` — a JSX
line-wrap whitespace-collapse issue, fixed with an explicit `{' '}`), re-verified after the fix.



Both Phase 4a and 4b were built and self-tested from a sandbox with no Docker access — real but
partial verification (pip-installed dependency reconstruction, `@babel/parser` JSX-parse-only for
client files, no `vite build`/`vitest`/real `jest`). A second session, concurrently working the
same repo with real `docker exec` access, closed those gaps:

- **Engine, full container suite:** `docker exec enma_trading_platform-engine-1 python -m pytest
  /app/tests/` — **551/551 passed** (the 4 pre-existing unrelated `EventLog`/Mongo-hostname
  failures the sandbox saw don't reproduce inside the real docker-compose network, confirming that
  diagnosis was correct).
- **Server, full container suite:** `docker exec enma_trading_platform-server-1 npm test` —
  **169/169 passed**, including the 5 new `mcScoring`/`mcTopK` and 8 new `riskLeverageGrid`
  `labConfig.test.js` cases the sandbox could only verify via a standalone Node script.
- **Client:** `npx vite build` clean (only the pre-existing >500kB chunk-size warning, unrelated),
  `npx vitest run` — the existing `pages.smoke.test.jsx` suite 11/11.
- **Golden master** (`scripts/golden_master.py run/compare`, root `CLAUDE.md` Rule C): flagged real
  drift across 3 seeded strategies against the `after_dsr` baseline captured earlier the same day.
  Investigated rather than dismissed or blindly accepted: two independent golden-master re-runs
  against the CURRENT code+environment are byte-identical to each other (proves determinism is
  intact), and `SELECT COUNT(*) ... FROM candles WHERE symbol='BTCUSDT' AND timeframe='1h' AND
  time BETWEEN '2024-01-01' AND '2025-01-01'` returns only 1,440 of the ~8,760 candles the fixed
  golden-master window needs — a real TimescaleDB data-availability gap that changed between when
  `after_dsr.json` was captured and now, NOT a Phase 4 code regression (Phase 4a/4b touch only
  `optimizer.py`/`walk_forward.py`/`monte_carlo.py` — never `backtest_runner.py`, strategies, or
  indicators, and neither seeded-strategy default run passes through any new opt-in code path).
  Root cause of the gap itself (partial `ensure_candles_available` backfill, or a
  container/volume reset) not chased further — out of scope for this verification pass, flagged
  here so a future session doesn't have to re-diagnose it.
- **Live browser verification**, real logged-in session against the actual `/lab` Optimizer wizard
  (not a mock): confirmed the MC-scoring checkbox + top-K input render and correctly extend the
  cost-estimate string; submitted a real walk-forward job (MicroScalper/BTCUSDT/1h/2023, 2 folds,
  6 combos/fold, mcScoring on) through the full BullMQ → engine → MongoDB pipeline; inspected the
  persisted `labResults` doc directly (`fold.mcScoring.candidates[]`, `.rawPick`, `.robustPick`)
  to confirm the shape matches the design; the rendered `RobustPickPanel.jsx` correctly showed the
  **honest "insufficient OOS trades, no fabricated percentile" guard path** (every candidate in
  this particular run had 0-1 OOS trades, below `MIN_MC_OOS_TRADES`=10, so `robustPick: null` and
  the panel rendered its "no valid MC-robust pick" fallback rather than a fake number) — the
  "MC-robust pick differs from raw pick" happy path is covered instead by the sandbox session's
  own deliberately-constructed `test_walk_forward.py` fixture (§ Phase 4a Verification below),
  which controls OOS trade counts directly rather than depending on which real market window
  happens to produce enough trades. Zero console errors in either case.

## Phase 4b shipped 2026-07-19 (risk_pct/leverage search — engine tested 537/537, client verified via real Node execution + JSX parse)

**Why now:** user reviewed this session's own scoping notes (below) and made 3 decisions: (1)
separate grid cartesian-multiplied against the strategy's `param_grid`, not tagged/prefixed keys in
the same dict; (2) searched independently per fold; (3) build risk_pct/leverage before PBO.

**Engine (`services/optimizer.py`):** new `_build_combined_grid(param_grid, risk_leverage_grid,
max_combinations, seed)` — cartesian-multiplies an optional `risk_leverage_grid` (keys `risk_pct`
fraction-of-equity, `leverage` int) against the strategy grid, returning
`{"alphaParams": {...}, "riskLeverage": {...}}` per combo — the two namespaces kept separate from
the start (never merged into one flat dict), because `run_backtest_simulation` validates every
`alpha_params` key strictly against the strategy's own `PARAMS` schema and would error on an
unrecognized `risk_pct` key rather than ignore it. Reuses `_decode_combo_index` unchanged for the
combinatorics guardrail this session's own scoping notes flagged (a 3-param grid capped at 200
combos, multiplied by 3×3 risk/leverage values, would otherwise become 1,800 combos with no
existing guardrail catching it) — `_build_combined_grid` computes the TRUE combined total across
every dimension and samples over THAT combined index space. `run_optimization`/
`run_bayesian_optimization` both gained an optional `risk_leverage_grid` param (default `None` =
zero behavior change) and now override `leverage`/`risk_params` per-combo before each
`run_backtest_simulation` call; every scored trial carries its own `riskLeverage` for downstream
reuse. `_finalize_optimization` persists `riskLeverageGrid` alongside `paramGrid` for
reproducibility.

**Engine (`services/walk_forward.py`):** new `_override_bt_common(bt_common, risk_leverage)` helper
— a fold's winning trial's OWN `riskLeverage` (not the job's flat `leverage`/`riskParams` default)
is what that fold's OOS test call actually uses, and the same override applies per-candidate inside
`_mc_score_fold`'s extra top-K OOS backtests. "Searched independently per fold" turned out to need
zero new per-fold logic — each fold already runs its own independent
`run_optimization`/`run_bayesian_optimization` call, so the combined grid is simply what gets
handed to it. `fold.bestRiskLeverage` and `meta.riskLeverageGrid` added to the persisted result.

**Server (`server/src/utils/labConfig.js`):** `riskLeverageGrid` validated when present — object,
non-empty, keys restricted to exactly `risk_pct`/`leverage`, each spec must have `values` or
`min`/`max`, and a key colliding with a `paramGrid` key of the same name is rejected outright
(fail loud rather than silently guessing which one wins downstream in the engine's namespace
split). Bounded by the existing `maxCombinations` cap (already clamped to `MAX_MAX_COMBINATIONS`) —
`_build_combined_grid` samples over the true combined total, so a wide `riskLeverageGrid` can't
bypass it.

**Client:** `WalkForwardWizard.jsx` gained a "Search risk_pct / leverage too" toggle with min/max/
steps inputs (risk % entered as a percentage, matching this app's other risk fields, converted to
the engine's native fraction convention only at submit) — off by default, and the combo-count cost
estimate now multiplies the strategy grid size by the risk/leverage grid size, matching what the
engine's own guardrail actually bounds. `TrialsExplorer.jsx`'s trials table gains Risk %/Leverage
columns only when a run searched them. `RobustPickPanel.jsx`'s candidates show
`(risk=X%, lev=Yx)` inline next to strategy params when present, and its existing "Copy robust pick
→ Backtest" deep link now also carries the robust pick's own risk_pct/leverage forward
(`prefillLeverage`/`prefillRiskPct` query params) — `NewBacktestWizard.jsx`'s prefill effect seeds
them, and the pre-existing exchange-settings prefill effect was hardened to defer to a pending
risk_pct/leverage prefill regardless of which of the two async queries happens to resolve first
(a real ordering bug this session caught and fixed before it could ship, not just theorized about).

**Verification, the most thorough this session achieved:** new `engine/tests/
test_risk_leverage_search.py` (7 tests: `_build_combined_grid` combinatorics + guardrail sampling,
`run_optimization`/`run_bayesian_optimization` per-combo override reaching a mocked
`run_backtest_simulation`, zero-behavior-change when `risk_leverage_grid` is omitted) plus 2 new
`test_walk_forward.py` cases (end-to-end: the grid reaches every fold's train step, the winning
trial's risk/leverage — not the job default — reaches the OOS call, `bestRiskLeverage`/
`meta.riskLeverageGrid` populate correctly). **Actually executed with real pytest in this session's
sandbox** (not just written) — engine full suite **537/537** (the entire suite, not just the new
tests), after reconstructing the dependency chain (`pip install` into the sandbox, the `/engine`
symlink shim from this session's earlier verification work) and fixing 8 pre-existing test fakes
in `test_walk_forward.py` that needed a `**kwargs` catch-all for the new `risk_leverage_grid`
keyword. `server/src/utils/labConfig.js`'s new validation was verified with a standalone Node
script (real `require()`/`assert` execution, not jest — this sandbox's `server/node_modules/jest`
is an empty directory) covering all 8 new cases plus a 4-case regression check that nothing
pre-existing broke; the same 8 cases were also written into `labConfig.test.js` for whenever real
jest access exists. Client-side changes verified via `@babel/parser` JSX-valid parsing only — no
working `vitest`/`vite` in this sandbox, so nothing was rendered or click-tested.

## Scoping notes (2026-07-19) — risk_pct/leverage search (shipped, see above) + PBO (shipped, see "PBO shipped" section above)

Per this session's own planning-task convention (design docs only, no code/stubs until told to
build): both remaining Plan 10 items were researched against the actual current code (not guessed
at) to identify the real architectural decisions someone building them will need to make. The
risk_pct/leverage section below is now historical — the user made the 3 decisions it lays out and
this session built it same-day (see the Phase 4b section above). **PBO is also now historical** —
shipped 2026-07-19/20, see the "PBO shipped" section near the top of this file.

### risk_pct / leverage search (Phase 4b's remaining half)

**Current state, confirmed by reading the code, not assumed:** `leverage` and `risk_params` are
each a single fixed value per entire optimization/walk-forward run today — `walk_forward.py:501`
(`int(config.get("leverage") or 10)`) and `:518` set them once into `bt_common`, reused identically
across every fold and every trial. `optimizer.py`'s `OptimizerConfig` likewise carries them as
single scalar/dict fields (not per-trial). `labConfig.js` mirrors this: `leverage`/`riskParams` are
validated as one scalar/object, never a range (unlike `paramGrid`, which is explicitly a
per-param range spec).

**Why this can't just be "add risk_pct to the existing param_grid dict":** `_build_param_grid`
(optimizer.py) is a flat, untyped `dict[str, dict]` that would happily expand a `risk_pct` key
alongside strategy params — but the resulting combo dict is passed wholesale as `alpha_params` into
`run_backtest_simulation`, which validates every `alpha_params` key strictly against that
strategy's own `PARAMS` schema (`backtest_runner.py`) and raises `Unknown parameter` on anything
else. `risk_pct` is a `risk_params` dict key, not a strategy-schema key — injecting it into
`param_grid` as-is would make every single trial error out, not silently ignore the extra
dimension.

**Two real design options, not yet chosen:**
1. **Tagged/prefixed keys in the same `param_grid`** (e.g. `risk.risk_pct`, `exec.leverage`),
   split back into `alpha_params` vs `risk_params`/`leverage` right before each
   `run_backtest_simulation` call. Advantage: reuses the existing `max_combinations`/
   `_build_param_grid` cap completely unmodified — it doesn't distinguish key "kinds," so the
   combined grid is automatically bounded by the same guardrail already in place. Disadvantage:
   mixes non-strategy concerns into the strategy-param namespace; every consumer of `param_grid`
   (grid search, Bayesian `_suggest_params`, the client's `ParamGridForm`) needs to know about the
   split convention.
2. **A separate risk/leverage grid, cartesian-producted against the existing strategy grid
   externally** (client-side: a second small form section, e.g. "Search risk_pct/leverage too,"
   next to the existing per-param range inputs). Advantage: clean separation, matches how the
   wizard already separates concerns (strategy params vs. objective/mode/mcScoring toggles).
   Disadvantage: this multiplication happens OUTSIDE `_build_param_grid`, so the existing cap does
   **not** protect it automatically — a 3-param strategy grid capped at 200 combos, multiplied
   externally by 3 risk_pct values × 3 leverage values, becomes 1,800 backtests per fold with no
   single guardrail catching it unless the combined cardinality is explicitly folded into
   `max_combinations` *before* calling `_build_param_grid` (a new, explicit guardrail, in the same
   spirit as `MAX_MC_TOP_K`/`MIN_MC_OOS_TRADES`).

**Recommendation (not a decision — needs sign-off):** option 2, because it keeps the wizard's
mental model clean and matches how Phase 4a's own guardrails were built (a small, explicit,
documented cap rather than an implicit one) — but it requires writing that new cap deliberately,
not inheriting it for free. Bayesian search is cheaper to extend either way (`_suggest_params` just
gets 1-2 more TPE dimensions; no cartesian blow-up since Bayesian never enumerates the full grid).

**Scope this should stay opt-in**, same pattern as `mcScoring`/`method: bayesian` — default off,
zero behavior change for every existing run, a new checkbox + range inputs in `WalkForwardWizard`,
and the combo-count cost estimate needs another multiplier so it doesn't silently undercount.

**Not yet answered, needs a decision before implementation starts:** should risk_pct/leverage be
searched independently per fold (like the strategy grid already is), or held fixed across all
folds within one run and only swept across separate runs? The former is more thorough but
multiplies cost by `nFolds` on top of everything else in point 2 above.

### PBO (Probability of Backtest Overfitting, CSCV method)

> **RESOLVED AND SHIPPED 2026-07-19/20 — see the "PBO shipped" section near the top of this file.**
> Both open questions below were answered: subsample source is PBO's own independent block scheme
> (NOT walk-forward's folds), and per-trial trade data turned out to already exist (confirmed by
> reading `optimizer.py`) — the only real gap was a missing `jobId` field on scored trial dicts,
> fixed at the source. This subsection is kept as the original scoping analysis / historical
> record, not a current TODO.

**Confirmed via code reading:** today, `run_lab_walk_forward` OOS-evaluates only each fold's single
winner (`best_params`). Phase 4a's `mcScoring` OOS-evaluates a *few more* trials per fold
(`mcTopK`, capped at 10) — but that is still a fixed top-K subset of **one fold's one fixed
train/test boundary**, not "every trial across every combinatorial split," which is what CSCV
actually requires (per this file's own pre-existing docstring in `walk_forward.py`). Phase 4a's
extra-OOS-backtest plumbing is reusable in the narrow mechanical sense ("run one more backtest and
score it") but does **not** generate the additional split combinations PBO needs — that's new
fold-partitioning logic, not a wider `top_k`.

**Why this is a materially different, larger piece of work, not an extension of walk-forward:**
canonical CSCV partitions the full backtest into `S` contiguous subsamples and evaluates every one
of `C(S, S/2)` combinatorial train/test splits (e.g. `S=8` → 70 combinations), computing every
trial's out-of-sample rank in every combination. This is symmetric train/test combinatorics, not
walk-forward's sequential rolling/anchored fold order — it is a genuinely different statistical
procedure that happens to share vocabulary ("in-sample/out-of-sample") with walk-forward, not a
mode of it. The open architectural question, not yet resolved: does PBO reuse walk-forward's
existing fold boundaries as its `S` subsamples (cheap to build, but ties PBO's subsample count to
whatever `nFolds` the user picked for an unrelated reason), or does it need its own independent
subsampling scheme over the full date range (statistically cleaner, but a parallel pipeline next to
walk-forward rather than a feature bolted onto it)?

**Cost, the reason this needs explicit scoping before any code:** the naive approach (re-run every
trial's backtest against every combinatorial split's test set) multiplies backtest count by
`n_trials × C(S, S/2)` — for even a modest 50-trial Bayesian search and `S=8`, that's 3,500 extra
backtests, an order of magnitude past anything else this plan has built. The much cheaper
alternative — compute each trial's full-range trade-level returns ONCE, then slice/re-score that
already-computed series against each combination's test-period boundaries — avoids re-backtesting
entirely, but needs confirming whether every trial's trade-level data is actually persisted
anywhere today (Phase 3d's `fold.trials` carries params/loss/rank/**metrics**, not raw per-trade
data — whether `backtestTrades` exists per-trial, keyed by a per-trial jobId, or only for each
fold's single winner, was not confirmed this session and is the first thing a PBO implementation
session needs to check before designing further).

**Recommendation:** PBO deserves its own short design pass (likely its own `services/pbo.py`, not
an addition to `walk_forward.py`) before any code — specifically resolving (a) subsample source
(reuse fold boundaries vs. independent), and (b) whether per-trial trade-level data needs a new
persistence path or already exists. Not attempted further this session — writing an unverified cost
model or data-shape assumption into code would risk the same "shipped but unreachable/wrong" class
of gap this session already found and fixed once in Phase 4a.

## Phase 4a shipped 2026-07-19 (MC-scored trial selection — engine built by a prior session, this session closed the API gap + shipped UI + tests)

**Why now:** a different session (context lost mid-work, resumed from a partially-corrupted
pasted transcript) had already built the full engine side of Phase 4a — `services/walk_forward.py`
gained `_eligible_trials`/`_mc_score_fold`, `services/monte_carlo.py` had already been refactored
to expose `compute_mc_stats` as a pure Mongo-free function for `_mc_score_fold` to call directly.
This session's job was to establish ground truth by reading the actual files (the pasted transcript
was truncated mid-word and not trustworthy as a instruction source), verify that work, and finish
whatever it left incomplete.

**Real gap found: the engine feature was completely unreachable via the API.** A full-codebase
grep for `mcScoring`/`mcTopK` turned up matches ONLY inside `walk_forward.py` — `server/src/utils/
labConfig.js`'s `buildWalkForwardConfig()` never read either field out of the request body at all,
so no request could ever set `config.mcScoring = true` no matter what the client sent. The fully-
built engine feature had shipped dead code from day one. Fixed: `labConfig.js` now validates
`mcScoring` (bool) and `mcTopK` (clamped to a new `MAX_MC_TOP_K=10`, matching the engine's own
guardrail, defaulting to `DEFAULT_MC_TOP_K=3` when `mcScoring` is on) and includes both in its
returned config (5 new `labConfig.test.js` cases).

**Shipped the rest of the full-stack wiring, previously missing:**
- `WalkForwardWizard.jsx` — mcScoring checkbox + conditional `mcTopK` input, and the combo-count
  cost estimate now accounts for the extra top-K OOS backtests
  (`(cappedPerFold + 1 + mcExtraPerFold) * nFolds`) so the estimate doesn't silently undercount
  what an mcScoring-enabled run actually costs.
- New `client/src/components/lab/RobustPickPanel.jsx` — renders per-fold when
  `fold.mcScoring?.enabled`: a fold switcher (for multi-fold runs), an amber "picks differ" banner
  vs a neutral "picks agree" banner, and a candidates table (rank/params/OOS net profit%/OOS
  trades/MC p5 profit%/fragility gap) highlighting the raw pick and the MC-robust pick. Wired into
  `StrategyLab.jsx` between `FoldResultsTable` and `TrialsExplorer`.
- New engine test coverage in `test_walk_forward.py` (previously zero for this code path):
  `_eligible_trials` unit tests (min-trades filter, non-finite-loss exclusion even at
  `min_trades<=0`), and an end-to-end `mcScoring=True` run verifying `fold.mcScoring` is populated
  correctly, that the raw pick's OOS backtest is reused rather than re-run (no duplicate
  `run_backtest_simulation` call for rank 1), that the extra OOS backtest IS made for the
  remaining top-K candidates, and that the MC-robust pick can diverge from the raw pick when a
  candidate's OOS trades hide a tail-loss behind a similar headline point-estimate.

**Phase 4b slice shipped same day: robust-pick copy-to-backtest action (§4.3 item 5).**
`RobustPickPanel.jsx` gained a "Copy robust pick → Backtest" button, enabled once
`config.strategyFile` (the optimization job's persisted filePath) resolves against
`useStrategies()` client-side — same filePath join key `NewBacktestWizard`/`Backtest.jsx` already
use, no server change needed. Clicking it deep-links to `/backtest?prefillStrategyId=...&
prefillSymbol=...&prefillTimeframe=...&prefillExchange=...&prefillParams=<json>` (prefixed
`prefill*` names deliberately — `Backtest.jsx`'s existing history-filter UI already owns bare
`symbol`/`timeframe` query params for list filtering; reusing those names would have silently
corrupted that filter state instead of seeding the wizard). `Backtest.jsx` reads these once
(ref-guarded, mirroring the existing `jobIdParam`/`exchangeSettings` prefill patterns already in
this codebase) and auto-opens the `NewBacktestWizard` dialog; `NewBacktestWizard.jsx` gained a new
optional `initialConfig` prop (additive — every existing caller passes nothing and gets identical
blank-defaults behavior) that seeds `selectedStrategy`/`params`/`symbol`/`timeframe`/`exchange`
once `useStrategies()` resolves. Malformed/tampered `prefillParams` JSON degrades to no param
prefill rather than crashing the page. Button is disabled (with an honest tooltip, not silently
hidden) when the strategy can't be matched — e.g. renamed/deleted since the optimization ran.

**Phase 4b slice shipped same day: backtest-page MC summary auto-enqueue strip (§4.4).** New
`client/src/features/backtest/MCSummaryStrip.jsx`, rendered on `Backtest.jsx`'s Overview tab right
after the metrics grid, gated on `activeResult.status === 'completed'`. Auto-fires
`useRunMonteCarlo({ sourceJobId })` with no other config (the engine/server's own defaults: `block`
mode, `DEFAULT_RUNS`, 30% ruin threshold) once per `sourceJobId`, reusing Phase 1's already-shipped
`configHash` idempotent-cache short-circuit rather than a client-side "does one already exist?"
check — remounting for the same backtest just returns the cached completed doc instantly instead
of re-queueing. Polls via the existing `useSimulation` hook + `simulation:complete`/`simulation:
error` Socket.IO events (same room/event names `RobustnessTab` already uses) — no progress bar,
since a default-config MC run completes in under a second and the engine doesn't call
`publish_progress` for a job that short (documented in this file's own Phase 1 section). Renders
p5/median/p95 final-equity % + P(ruin) with severity coloring, plus a "Full analysis in Lab →" deep
link (`/lab?sourceJobId=...`, same pattern as the existing "Robustness Check" button). Fails
quietly (renders nothing) rather than showing an alarming error banner on an otherwise-successful
backtest report — this is a bonus strip, not the report itself. No engine or server change needed;
100% client-side, reusing already-tested infra unchanged.

**Still deferred (Phase 4b's remaining half):** risk_pct search and leverage bands — both need a
genuine engine-side extension (searching over `risk_params`/leverage as additional optimizer
dimensions, not just strategy PARAMS), materially larger than either slice shipped today.

**Verification for this slice:** same sandbox constraints as the rest of Phase 4a — no working
`vite`/`vitest` here (`client/node_modules`'s `.bin/` shims are Windows-format and fail to execute
directly under this Linux sandbox's `sh`, and importing `vitest` for a real run hits the same
native-binary gap already diagnosed for `esbuild`). All 4 touched files (`RobustPickPanel.jsx`,
`StrategyLab.jsx`, `NewBacktestWizard.jsx`, `Backtest.jsx`) were confirmed to parse as valid JSX via
`@babel/parser` (the same real check used for the rest of Phase 4a), and reviewed line-by-line
against each file's existing state/effect conventions, but not rendered or click-tested.

**Real engine pytest execution achieved this session (a first this week).** No Docker in this
sandbox, but the engine's Python deps have no hard OS-level requirement beyond TA-Lib (not needed
by this code path), so they were pip-installed directly for verification purposes only (does not
touch the actual Docker image/`requirements.txt`). The one real blocker — every strategy file
imports via `from engine.core...`, relying on a `/engine → /app` symlink `main.py` creates at
container boot — was replicated with a writable-path shim (`/tmp/pyshim/engine` + `PYTHONPATH`)
since this sandbox has no root write access. **Result: 534 engine tests collected, 530 passed, 4
failed — all 4 failures are the same pre-existing, unrelated cause** (`test_execute_entry_
risk_check_event.py` x2, `test_reconcile_fixes.py` x2 — each hits a real, unmocked EventLog Mongo
write against the hostname `mongodb`, which only resolves inside the actual docker-compose
network; DNS failure in this sandbox, not a code bug). Every Phase 4a file passed for real:
`test_walk_forward.py` 22/22 (the new mcScoring tests confirmed the raw pick's OOS backtest is
reused not duplicated, and the MC-robust pick genuinely diverges from the raw pick via the real
`compute_mc_stats`, not a mocked stand-in), `test_stats.py`/`test_lab_simulation.py`/
`test_bayesian_optimizer.py`/`test_monte_carlo.py` 57/57. **Still unverified:** `server`/`client`
jest/`vite build` — both `node_modules` in this sandbox are broken in a way distinct from the
previously-known Windows/Linux native-binary mismatch (entire packages like `jest`/`express` exist
as empty directories), so reinstalling wasn't attempted (would violate "don't alter node_modules on
host"). `RobustPickPanel.jsx` was reviewed against `FoldResultsTable.jsx`'s existing styling/
structure conventions and parses as valid JSX (`@babel/parser`) but was not rendered.

## Phase 3e shipped 2026-07-19 (Deflated Sharpe Ratio — PBO still deferred, real unrelated bug found+fixed)

**Why now:** DSR/PBO had been deferred across four prior Plan 10 sessions (Phase 1, 3a, 3b, 3d)
with the identical stated reason: no way to numerically verify the normal-CDF/inverse-CDF
primitive DSR depends on without pytest access. This session had real Docker access, so the
blocker no longer applied — shipped, verified, not guessed at.

**Engine — `services/stats.py` (new).** `norm_cdf(x)` is exact (`math.erf`, a full-precision
stdlib primitive — no approximation risk at all). `norm_ppf(p)` (the inverse, no closed form) uses
Peter Acklam's published rational approximation (~1.15e-9 relative error) plus one Halley
refinement step (using the exact `norm_cdf` above as the error signal, pushing accuracy to
~1e-12) — no scipy dependency, since scipy isn't in `engine/requirements.txt`. Verified two ways
in `tests/test_stats.py` (29 tests): round-trip (`norm_cdf(norm_ppf(p)) == p` to ~1e-9, swept
across both Acklam approximation branches plus the branch boundary) and against published
reference quantiles (Φ⁻¹(0.975)≈1.959963985, Φ⁻¹(0.995)≈2.575829304, Φ(1)≈0.8413447460685429).
`expected_max_sharpe()` (SR_0, the extreme-value-theory expected-max-Sharpe-under-null-across-N-
trials term) and `deflated_sharpe_ratio()` (Bailey & López de Prado 2014) built on top, with
property tests verifying the core deflation behavior numerically: DSR decreases as trial count
increases for the same apparent Sharpe (picking the best of more trials should make the same
result look less convincing — directly tested, not just asserted), DSR stays in [0,1] across 50
randomized property-test cases, and DSR returns an explicit `insufficientData: true` (dsr=0.5,
never a fabricated confident number) when there's too little data or a pathological
non-normality term rather than raising or silently returning something misleading.

**Engine — trade-level, not the paper's per-period formulation.** Deliberate choice: SQN
(`services/metrics.py`'s existing `SQNStat`) is `sqrt(N)*mean(pnl)/std(pnl)` — already a
trade-level Sharpe-like statistic. Dividing out `sqrt(N)` recovers `mean(pnl)/std(pnl)` directly
from data ALREADY persisted per trial (`sqn`, `totalTrades`) — no new per-trial metric needed for
the Sharpe-like term itself. Two new metrics WERE needed for the non-normality correction:
`SkewnessStat`/`KurtosisStat` (`services/metrics.py`, trade-level round-trip PnL skewness / RAW
non-excess kurtosis — 3.0 for normal, matching Bailey & López de Prado's own paper convention, NOT
numpy/scipy's excess-kurtosis default) — additive-only, golden-master-verified (`before_dsr`/
`after_dsr` snapshots on all 5 seeded strategies: every pre-existing metric byte-identical, only
`skewness`/`kurtosis` appeared as new keys in the diff). `optimizer.py`'s per-trial metrics
whitelist gained `skewness`/`kurtosis` so they flow through into `fold.trials[].metrics`.

**Engine — wiring.** `walk_forward.py`'s per-fold loop computes `fold.dsr` right after each fold's
`best`/`trials` are determined: `_trade_level_sharpe()` (the `sqn/sqrt(N)` recovery) applied to
every trial in that fold's pool (for `V[SR_n]`/SR_0) and to the winner (`SR_hat`), `T` =
winner's `totalTrades`, skew/kurtosis = winner's own trade-PnL skew/kurtosis. Skipped folds (no
eligible combo) carry a static `{dsr: 0.5, insufficientData: true}` rather than omitting the
field.

**Real, pre-existing, UNRELATED bug found and fixed via this session's own live testing:**
verifying DSR through the actual `/lab` Optimizer wizard (AdaptiveTrend, ~12 checked params —
each expanded to dozens-to-hundreds of grid values) froze the entire engine container. Root
cause: `optimizer.py`'s `_build_param_grid` called `list(itertools.product(*value_lists))` to
materialize the FULL cartesian product BEFORE applying the `max_combinations` cap — for
AdaptiveTrend's real wizard-default grid this is ~472 trillion combinations (confirmed via the
UI's own cost-estimate string), and attempting to build a Python list of that size hangs/OOMs a
single-process container (confirmed via `docker stats` showing near-zero CPU during the hang —
stuck allocating, not computing; confirmed the engine's OWN health status flipped to `unhealthy`
and even a bare `/health` curl from *inside* the same container timed out). This is a real
production risk entirely independent of Phase 3e/DSR — any user checking several params with
default-width ranges in the existing, already-shipped Optimizer wizard could freeze the shared
engine for every other user. **Fix:** `_build_param_grid` now computes `total` via cheap
multiplication (no materialization), and when `max_combinations` would cap it, samples indices
via `random.sample` on a lazy `range` object (Python special-cases `range` — no materialization)
and decodes each index directly to its combo via `_decode_combo_index` (mixed-radix decomposition
matching `itertools.product`'s own iteration order — verified against real `itertools.product`
output for small cases in `test_param_grid.py`, plus a test reproducing the exact
472-trillion-combo AdaptiveTrend grid completing in milliseconds instead of hanging). No test had
existed for `_build_param_grid` at all before this session.

**Client.** `FoldResultsTable.jsx` gained a DSR column (color-coded: emerald ≥95%, amber ≥80%,
red below, "—" when `insufficientData`). `StrategyLab.jsx`'s disclosure note updated — DSR is no
longer listed as not-built; PBO's specific data-availability reason is now spelled out precisely
rather than lumped in with DSR under one generic "needs a numerically-verified primitive" line.

**Live-verified, real Docker + browser access, this session:** engine suite 538/538 (+29 stats
tests, +9 skew/kurtosis tests, +10 param-grid tests, +2 walk_forward DSR tests), server jest
156/156 (unchanged — no server-side contract change), client `vite build` clean. Golden master
(`before_dsr` vs `after_dsr`, all 5 seeded strategies): zero drift outside the two new
`skewness`/`kurtosis` keys. Beyond unit tests: direct `curl POST /simulate/optimize` against real
cached BTCUSDT candles + MicroScalper — real DSR values (68.6%, 63.4%, 57.0% across different
runs), correctly `insufficientData: false`, JSON-serialized cleanly. Then the actual real-world
regression repro: drove the genuine `/lab` Optimizer wizard in a real logged-in browser session
with AdaptiveTrend's full default param grid (the exact case that froze the container pre-fix) —
completed end-to-end in ~4s post-fix, rendered the trials table with no console errors. Engine
container was restarted mid-session to clear state accumulated by the pre-fix hang reproductions;
confirmed clean afterward (`docker ps` healthy, fresh runs succeed).

**Still not done:** PBO (Probability of Backtest Overfitting, CSCV) remains deferred — needs every
trial's out-of-sample performance across multiple train/test resample combinations, which this
architecture deliberately doesn't collect (Phase 3d's own documented reason: only each fold's
winner gets OOS-evaluated). Computing real PBO means OOS-evaluating every trial in every fold —
multiplying the walk-forward job's backtest count by the grid/trial size — real, separate,
not-small scope for a future session, not attempted here.

## Phase 3b shipped 2026-07-19 (Optuna/TPE Bayesian search — DSR/PBO still not started)

**Engine.** `engine/services/optimizer.py` gained `run_bayesian_optimization()` + a
`_suggest_params()` adapter, per Plan 19's own design: the same `param_grid` JSON spec
(`{min,max,step,type:"int"}` / `{min,max,type:"float"}` / `values` categorical) drives both grid
(`itertools.product`) and Bayesian (`trial.suggest_int`/`suggest_float`/`suggest_categorical`) —
no new client contract. Uses optuna's ask/tell API rather than `study.optimize(...)` — Plan 19's
own documented risk ("ask/tell is cleaner for async") — because each trial needs to `await
run_backtest_simulation(...)`. Seeded `TPESampler` for reproducibility (same seed + same space →
identical trial sequence, tested). A failing trial's exception is caught and `study.tell()`'d a
large finite sentinel loss (optuna's `tell()` rejects non-finite values, unlike grid's plain list
append) while the reported/persisted result still carries `loss=inf` → sanitized to `null` (see
bug below) — same error-path shape as grid. The ranking/min-trades-filter/persistence tail
(previously duplicated at the end of `run_optimization`) was extracted into a shared
`_finalize_optimization()` so grid and Bayesian return byte-identical result shapes; both now
carry a `method: "grid"|"bayesian"` field.

**Router.** `POST /optimize/run` gained `method: "grid"|"bayesian"` (default `"grid"`, back-compat)
+ `nTrials`/`seed` (bayesian only), dispatching to the new function.

**Walk-forward integration, per Plan 19's own sequencing note** ("make S8 selectable as the fold
optimizer"): `walk_forward.py`'s per-fold train step reads `config.method`/`config.nTrials`/
`config.seed` and dispatches to `run_bayesian_optimization` when `method == "bayesian"`, with a
deterministic-but-distinct seed per fold (`base_seed + foldIndex`, same stance as `monte_carlo.py`'s
own per-source seeding). No other fold/stitch logic changed — both optimizer functions return the
identical ranked-results shape Phase 3a/3d's fold loop already consumes.

**Real, pre-existing bug found and fixed at the source, not just worked around:** live-testing the
Bayesian path (both a direct `curl POST /optimize/run` against real cached BTCUSDT candles, and a
full browser session through the actual `/lab` Optimizer wizard) hit
`ValueError: Out of range float values are not JSON compliant` the moment any trial's backtest
raised (`loss=inf` by the optimizer's own error-path design, same class of bug Phase 3d already
fixed for `walk_forward.py`'s per-fold `trials`). This crash was **not new to Bayesian** — grid's
`run_optimization` had carried the identical defect since before this session, just never
exercised because `/optimize/run` has no Node route mounted today (only the job-based
`/lab/optimizations` path is reachable from the product, and no prior session had hit an erroring
combo through it with live browser access). Fixed once at the shared `_finalize_optimization()`
tail — every non-finite loss is sanitized to `null` before it reaches JSON, for both `results` and
`best`, for both methods. `walk_forward.py`'s own `best.get("loss")` check was updated to
short-circuit on `None` before calling `math.isfinite()` (which raises `TypeError` on non-float).

**Client.** `WalkForwardWizard.jsx` gained a Grid/Bayesian search-method toggle and a
trials-per-fold input (replacing the max-combinations field when Bayesian is selected); the cost
estimate strip now reads "Bayesian: N TPE trials/fold (of M possible combos)" instead of the grid
combo count. `DegradationVerdict.jsx` shows "Bayesian/TPE search" in its header when applicable.
`server/src/utils/labConfig.js`'s `buildWalkForwardConfig()` gained `method`/`nTrials` (clamped to
`MAX_N_TRIALS`=500, same guardrail stance as `MAX_MAX_COMBINATIONS`)/`seed` validation.

**Live-verified, real Docker access, this session:** engine suite 488/488 (+16 new tests across
`test_bayesian_optimizer.py` and `test_walk_forward.py`'s new bayesian-dispatch test), server jest
156/156 (+8 new `labConfig.test.js` cases), client `vite build` clean. Beyond unit tests: a direct
`curl POST /optimize/run` with `method: "bayesian"` against real cached BTCUSDT 1h candles +
MicroScalper (6 trials, one genuinely errored on a strategy-internal param-bound check, correctly
surfaced as `loss: null` with its real error string, `best` correctly picked the finite-loss
winner) — then went further and drove the actual `/lab` Optimizer wizard in a real logged-in
browser session against the real running stack (AdaptiveTrend/BTCUSDT, Bayesian method, 5 trials/
fold × 2 folds): the run completed end-to-end through BullMQ → engine → MongoDB, both folds
legitimately reported "skipped — no eligible parameter combination" (5 TPE trials over a large
multi-param space genuinely found nothing eligible — not a bug, a real search-budget tradeoff),
and the results canvas (trials table, stitched OOS, fold table) rendered correctly with zero
console errors. Test data cleaned up from MongoDB Atlas after both runs. Also directly verified
`POST /simulate/optimize` (the actual job-based walk-forward path) end-to-end with a friendlier
AdaptiveTrend/BTCUSDT config — a fold produced a real winning combo, correct degradation ratio,
and clean JSON.

**Still not done:** Deflated Sharpe Ratio and PBO (§2.2's "honesty layer") still need a
normal-CDF/inverse-CDF primitive and remain deferred pending a session that can numerically verify
the formula.

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
