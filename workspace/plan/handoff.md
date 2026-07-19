# Session Handoff Log

Resume prompts for cross-session continuity (root `CLAUDE.md` Rule G / `AGENTS.md` → Session Handoff).

**Format rules:**
- Newest entry on top: `## <date> — <title> — <status>` with **Goal / Done / Files changed / Open questions**.
- Keep at most the **3 most recent entries**. When adding a new one, delete the oldest — git history is the archive. This file must stay a short resume prompt, not a project log.

---
## 2026-07-19 — Plan 10 Phase 4a/4b real-Docker verification — closes out every gap the sandbox session below flagged

**Goal:** a concurrent session (same repo, different account — this session's own token limit had
been hit) built Phase 4a (MC-scored trial selection) and Phase 4b (risk_pct/leverage search +
copy-to-backtest + MC summary strip) from a sandbox with no Docker access, disclosing several
verification gaps (see the entry below this one for full detail). This session had real
`docker exec` access and closed every one of those gaps.

**Verified for real:** engine container `pytest /app/tests/` — **551/551** (the 4 failures the
sandbox saw were confirmed environment-only, don't reproduce inside the real docker-compose
network). Server container `npm test` — **169/169**, including all new `mcScoring`/`mcTopK`/
`riskLeverageGrid` `labConfig.test.js` cases. Client `vite build` clean, `vitest run` 11/11.

**Golden master investigated, not just run:** flagged real drift on 3 seeded strategies vs the
`after_dsr` baseline. Root-caused rather than assumed-broken: two independent golden-master
re-runs against the CURRENT code are byte-identical to each other (determinism intact), and
TimescaleDB's `candles` table for BTCUSDT/1h has a real gap — only 1,440 of ~8,760 candles cached
for the golden harness's fixed 2024-01-01→2025-01-01 window — a data-availability change between
when `after_dsr.json` was captured and now, not a Phase 4 code regression (neither Phase 4a nor 4b
touches `backtest_runner.py`/strategies/indicators, and the drifted strategies' default runs never
exercise either phase's opt-in code path). Not chased further — the gap's root cause (partial
candle backfill vs. a container/volume reset) is flagged for whoever needs full historical data.

**Live-verified in a real logged-in browser session** against the actual `/lab` Optimizer wizard:
mcScoring toggle + top-K input render and correctly extend the cost estimate; a real walk-forward
job (MicroScalper/BTCUSDT/1h/2023, mcScoring on) completed through the full BullMQ→engine→Mongo
pipeline; `RobustPickPanel.jsx` correctly rendered the honest "insufficient OOS trades, no
fabricated percentile" guard path (this run's candidates all had 0-1 OOS trades) with zero console
errors — the "robust pick differs from raw pick" happy path is covered by the sandbox session's own
deliberate `test_walk_forward.py` fixture instead, which controls trade counts directly rather than
depending on what a real market window happens to produce.

**Files changed:** `engine/services/monte_carlo.py`/`walk_forward.py` (independently-written, later
found to already match the concurrent session's own implementation of the same design — reconciled,
no conflict). Docs: `workspace/docs/state/CURRENT_STATE.md` (new changelog entry + Strategy Lab
section), `10_monte-carlo-strategy-lab.md` (new "Real Docker verification" section), `engine/
CLAUDE.md` (services-table entries for `monte_carlo.py`/`walk_forward.py`/`optimizer.py`/
`test_risk_leverage_search.py`), this file.

**Open questions:** PBO remains the only unshipped Plan 10 item — still needs its own design pass
(does real per-trial OOS trade data exist anywhere to resample over, or does it need new
persistence — see the scoping notes in `10_monte-carlo-strategy-lab.md`). The TimescaleDB candle
gap found during golden-master investigation is real and worth a full backfill before the next
golden-master baseline capture, but is an infra/data task, not a code task — separate from Plan 10.

---
## 2026-07-19 — Plan 10 Phase 4a wired end-to-end — resumed from a corrupted pasted transcript, found and fixed a dead-code gap

**Goal:** a prior session (this one's own context window had run out mid-work — "your session limit ·
resets 11pm") had already built the full engine side of Phase 4a (MC-scored trial selection) in
`services/walk_forward.py`/`services/monte_carlo.py`. This session's user pasted that prior
session's transcript, truncated mid-word and unreliable as an instruction source, asking to
"continue from below state." Rather than trust the garbled paste, this session read every real
file directly to establish ground truth first.

**Verified (engine side was already correct and complete):** `walk_forward.py`'s `_eligible_trials`/
`_mc_score_fold`, `monte_carlo.py`'s `compute_mc_stats`/`returns_from_trades` extraction,
`optimizer.py`'s Bayesian dispatch + `_decode_combo_index` fix, `services/stats.py`'s DSR/normal-CDF
primitives, and their respective test files (`test_stats.py`, `test_walk_forward.py`'s existing
3a/3b/3d/3e coverage) — all read in full, all internally consistent, no changes needed.

**Real gap found: the engine feature was completely unreachable via the API.** A full-codebase
grep for `mcScoring`/`mcTopK` matched ONLY inside `walk_forward.py` —
`server/src/utils/labConfig.js`'s `buildWalkForwardConfig()` never read either field from the
request body at all. No client request could ever actually enable the feature. This is exactly the
class of gap a corrupted, code-only transcript wouldn't surface — it only shows up from tracing the
request path end to end.

**Shipped to close the gap:** `labConfig.js` validation for `mcScoring`/`mcTopK` (new
`MAX_MC_TOP_K=10`/`DEFAULT_MC_TOP_K=3`, mirroring the engine's own guardrails) + 5 new
`labConfig.test.js` cases; `WalkForwardWizard.jsx` mcScoring checkbox + mcTopK input + corrected
cost-estimate math; new `client/src/components/lab/RobustPickPanel.jsx` (per-fold candidates table,
raw-pick-vs-robust-pick divergence banner) wired into `StrategyLab.jsx`; new
`test_walk_forward.py` coverage that didn't exist before (`_eligible_trials` unit tests + an
end-to-end `mcScoring=True` run confirming the raw pick's OOS backtest is reused not re-run, and
that the MC-robust pick can diverge from it).

**UPDATE, same session: actually got real engine pytest execution — a first this week.** No
Docker in this sandbox, but the engine's Python deps have no hard OS-level requirement beyond
TA-Lib (which nothing in `test_walk_forward.py`'s own dependency chain needs), so the missing
packages were installable directly (`pip install pytest motor asyncpg redis fastapi httpx optuna
pandas-ta-classic pyopenssl` — none of this touches the actual Docker image or `requirements.txt`).
The one real blocker: every strategy file does `from engine.core... import ...` relying on a
`/engine → /app` symlink that `main.py` creates at container boot — invisible until you go looking,
since no test file creates it itself (a handful, e.g. `test_bestsupertrend_htf_parity.py`, replicate
it defensively, most don't). Replicated with a writable-path shim (`/tmp/pyshim/engine` symlink +
`PYTHONPATH`) since this sandbox has no root write access for the real `/engine` path.

**Result: 534 tests collected, 530 passed, 4 failed — every failure is the same pre-existing,
unrelated cause.** `test_execute_entry_risk_check_event.py` (2) and `test_reconcile_fixes.py` (2)
each hit a real, unmocked `EventLog` Mongo write against the hostname `mongodb`, which only
resolves inside the actual docker-compose network — DNS failure/hang in this sandbox, not a code
bug. Every Phase 4a-relevant file passed for real: `test_walk_forward.py` 22/22 (the 5 new mcScoring
tests confirmed the raw pick's OOS backtest is reused not duplicated, and the MC-robust pick
genuinely diverges from the raw pick as designed — not just asserted, actually computed via the
real `compute_mc_stats`), `test_stats.py`/`test_lab_simulation.py`/`test_bayesian_optimizer.py`/
`test_monte_carlo.py` 57/57.

**Also confirmed, not previously known precisely:** `server/node_modules` is equally broken in this
sandbox, not just `client/node_modules` — entire packages (`jest`, `express`) exist as directories
with zero files inside, a different failure mode than the previously-diagnosed Windows/Linux native
binary mismatch. Did not attempt `npm install`/reinstall (same "don't alter node_modules on host"
constraint) — jest/`vite build` remain unverified, but the gap is now precisely diagnosed rather
than just disclosed as blocked.

**Files changed:** `server/src/utils/labConfig.js` (+mcScoring/mcTopK validation + constants),
`server/src/utils/__tests__/labConfig.test.js` (+5 tests), `client/src/components/lab/
WalkForwardWizard.jsx` (+mcScoring UI + cost-estimate fix), new `client/src/components/lab/
RobustPickPanel.jsx`, `client/src/pages/StrategyLab.jsx` (wire in RobustPickPanel),
`engine/tests/test_walk_forward.py` (+5 tests: `_eligible_trials` x2, mcScoring-disabled-by-default,
end-to-end mcScoring e2e, module docstring update). Docs: `10_monte-carlo-strategy-lab.md`
(new Phase 4a shipped section), `0_tracker.md`, this file.

**Same session, continued: shipped a Phase 4b slice — robust-pick copy-to-backtest action
(§4.3 item 5).** `RobustPickPanel.jsx` gained a "Copy robust pick → Backtest" button; clicking it
deep-links to `/backtest?prefillStrategyId=...&prefillSymbol=...&prefillTimeframe=...&
prefillExchange=...&prefillParams=<json>` (prefixed `prefill*` names — deliberately not bare
`symbol`/`timeframe`, which `Backtest.jsx`'s existing history-filter UI already owns as query
params; reusing those names would have silently corrupted list filtering instead of seeding the
wizard — caught by reading `Backtest.jsx` in full before writing the query-param names, not by
trial and error). `Backtest.jsx` reads the new params once (ref-guarded) and auto-opens
`NewBacktestWizard`, which gained an additive `initialConfig` prop (every existing caller passes
nothing, unchanged behavior). Resolves the optimization job's persisted `config.strategyFile`
(a filePath, not a Mongo id) against `useStrategies()` client-side to get a real `strategyId` —
same join key the rest of the codebase already uses. Verification: all 4 touched files parse as
valid JSX (`@babel/parser`, same real check as the rest of this session), reviewed against each
file's existing conventions, but — same gap as ever — no working `vitest`/`vite` here to actually
render/click it (this sandbox's `client/node_modules/.bin/*` are Windows-format shims that don't
execute under this Linux sandbox's `sh`).

**Same session, continued again: shipped the last item of Phase 4b's §4.4 scope — the
backtest-page MC summary auto-enqueue strip.** New `client/src/features/backtest/
MCSummaryStrip.jsx`, wired into `Backtest.jsx`'s Overview tab right after the metrics grid. Fires
`useRunMonteCarlo({ sourceJobId })` (server/engine defaults, no new config) once per completed
backtest's jobId, deliberately relying on Phase 1's already-shipped `configHash` cache
short-circuit for idempotency rather than adding a new "does one exist?" client check — remounting
just returns the cached doc instantly. Polls the existing `useSimulation` hook + the same
`simulation:complete`/`simulation:error` socket events `RobustnessTab` already listens for; no
progress bar since these jobs finish in under a second (documented reason already in the plan
doc). Renders p5/median/p95/P(ruin) + a "Full analysis in Lab" deep link, or nothing at all on
failure (quiet, not alarming — it's a bonus strip). Zero engine/server changes — purely additive
client code reusing already-tested infra. Same verification method as everything else this
session: `@babel/parser` JSX-valid, reviewed against `RobustnessTab`'s existing socket/query
patterns, not rendered (no working `vitest` here).

**This closes out Phase 4b except its one materially-larger remaining piece: risk_pct search and
leverage bands, which need a genuine engine-side optimizer extension (new searchable dimensions
beyond strategy PARAMS), not a client-only slice like the two shipped today.**

**Same session, continued once more: scoped (planning only, no code) both remaining Plan 10
items — risk_pct/leverage search and PBO.** Per this session's own planning-task convention,
produced a "Scoping notes" section in `10_monte-carlo-strategy-lab.md` grounded in actually reading
`optimizer.py`/`walk_forward.py`/`backtest_runner.py`/`labConfig.js`, not guessed at. Key findings,
condensed:

- **risk_pct/leverage** can't simply be added as extra keys to the existing `param_grid` dict —
  `alpha_params` is validated strictly against the strategy's own `PARAMS` schema in
  `backtest_runner.py`, so a `risk_pct` key would error out every trial, not get silently ignored.
  Two real design options identified (tag/prefix keys in the same grid vs. a separate grid
  cartesian-produced against it) with a recommendation (the latter, matching the wizard's existing
  separation of concerns) but an explicit note that it needs a NEW combinatorics guardrail —
  the existing `max_combinations` cap only protects the strategy-grid side, not an externally
  multiplied risk/leverage dimension.
- **PBO** is a materially larger, different piece of work than anything else in this plan — CSCV
  needs OOS evaluation across combinatorial train/test SPLIT combinations (not just more trials per
  one fixed fold boundary, which is all Phase 4a's `mcScoring` machinery does). Real open question
  not yet resolved: does it reuse walk-forward's fold boundaries as CSCV subsamples, or need its
  own independent partitioning? Also flagged: whether per-trial trade-level data is even persisted
  anywhere today (Phase 3d's `fold.trials` carries metrics, not raw trades) is unconfirmed and is
  the first thing a real PBO session needs to check.

Neither was implemented — deliberately, per Rule D (planning tasks produce docs, not code stubs),
and because writing an unverified cost/data-shape assumption into code risks exactly the
"shipped-but-unreachable" class of gap this session already found once (Phase 4a's dead
`labConfig.js` gap).

**Same session, continued once more: user answered the 4 scoping questions (separate grid
cartesian-multiplied against `param_grid`; searched independently per fold; PBO uses independent
partitioning, not walk-forward's fold boundaries; build risk_pct/leverage search first) — shipped
risk_pct/leverage search in full, engine tested 537/537 with real pytest execution.**

**Engine:** new `_build_combined_grid()` in `optimizer.py` — cartesian-multiplies the strategy's
`param_grid` against an optional `risk_leverage_grid` (keys `risk_pct`/`leverage`), returning
`{"alphaParams": {...}, "riskLeverage": {...}}` per combo — a genuinely separate namespace, NOT a
merged dict, because `backtest_runner.py` validates `alpha_params` strictly against the strategy's
own `PARAMS` schema and would hard-error on an unrecognized `risk_pct` key. Reuses
`_decode_combo_index` so the combinatorics guardrail samples over the TRUE combined total, closing
the exact explosion risk flagged in this session's own scoping notes (verified with a dedicated
test: 50-value grid × 3 leverage values = 150 combined, correctly capped to 50, not to the
strategy-grid's own 50). Both `run_optimization` and `run_bayesian_optimization` now accept
`risk_leverage_grid` and override `leverage`/`risk_params.risk_pct` per combo before calling
`run_backtest_simulation`. `walk_forward.py` gained `_override_bt_common()` so a fold's winning (or
MC-scored candidate) trial is OOS-tested at its OWN searched risk_pct/leverage, not the job's flat
default — `fold_result.bestRiskLeverage` and each MC candidate's `riskLeverage` now persist this.
`risk_pct` is a fraction of equity (matches `risk_budget_qty()`'s existing convention), capped at
20% engine-side regardless of input.

**Server:** `labConfig.js`'s `buildWalkForwardConfig` validates `riskLeverageGrid` (object, keys
restricted to `risk_pct`/`leverage`, each a range-or-values spec, rejects collision with a
same-named `paramGrid` key) and passes it through unchanged.

**Client:** `WalkForwardWizard.jsx` gained a risk_pct/leverage search toggle + min/max/steps inputs,
with the cost estimate now multiplying strategy-grid combos by risk/leverage combos (was
undercounting before this). `TrialsExplorer.jsx` conditionally renders Risk%/Leverage columns only
when a run actually searched them. `RobustPickPanel.jsx`'s copy-to-backtest action now carries the
robust pick's own searched `prefillLeverage`/`prefillRiskPct` forward (risk_pct ×100 for the
wizard's percentage convention) so a pick that won because of a specific leverage doesn't silently
lose that half of its identity en route to the backtest wizard. `Backtest.jsx`/
`NewBacktestWizard.jsx` consume the two new prefill params.

**Real race-condition bug caught and fixed before shipping (not present before this slice):**
`NewBacktestWizard.jsx`'s pre-existing `exchangeSettings` prefill effect and the new Phase 4b
prefill effect both write `leverage`/`risk` state from two independent, unordered async React Query
fetches — whichever resolved last would silently overwrite the other's value. Fixed by hardening
the `exchangeSettings` effect to defer to a pending prefill (`if (!initialConfig?.leverage)
setLeverage(...)`, preserving `prev.riskPct` when a riskPct prefill is pending), guaranteeing
deterministic precedence regardless of async ordering.

**Verification:** engine 537/537 via the same real-pytest sandbox reconstruction as earlier this
session (7 new tests in `test_risk_leverage_search.py`, including an autouse fake-database fixture
to stop `_finalize_optimization`'s real Mongo call from hanging in this sandbox; 2 new tests in
`test_walk_forward.py` confirming the OOS call uses the winning trial's own risk/leverage not the
job default, and that omitting the feature is zero-behavior-change; 8 pre-existing test fakes fixed
via `**kwargs` after they broke on the new `risk_leverage_grid` kwarg). `labConfig.js` verified via
a standalone Node script (no jest here) exercising the real file with `require()`/`assert`. Client
files verified via `@babel/parser` JSX-valid parsing only (no working `vitest`/`vite` in this
sandbox) — not rendered/clicked.

**This closes out Plan 10's risk_pct/leverage search scope item entirely. Only PBO remains scoped
but not started** (see the scoping notes above — needs its own design pass: does it reuse
walk-forward's fold boundaries or need independent partitioning was answered — independent — but
whether per-trial trade-level data is even persisted anywhere today is still unconfirmed and is the
first thing a real PBO session needs to check).

**Next session:** (1) PBO is the last open Plan 10 item — before writing code, confirm whether
per-trial trade-level data is persisted anywhere (Phase 3d's `fold.trials` carries metrics, not raw
trades) since CSCV needs OOS evaluation across combinatorial train/test splits. (2) The FIRST
session with real Docker/browser access should run the actual `docker compose` container suite (not
this sandbox's hand-reconstructed one) AND click through this session's UI changes live — the
mcScoring toggle, copy-to-backtest button, MC summary strip, AND the new risk_pct/leverage search
toggle + its cost estimate + the robust-pick prefill carrying leverage/risk_pct forward. (3)
`server`/`client` jest/vite build are still genuinely unverified — both `node_modules` dirs in this
sandbox are broken (packages present as empty directories, `.bin/` shims are Windows-format), a real
session with working `npm install` access should run them. (4) Untouched backlog: 21.5c (batched
reconcile, P2/small), Plan 6/7 (engine/server decomposition, P2), Plan 23 (MarginSurge strategy),
Plan 8 (governance cleanup, P3), Plans 5/22/24 (shipped, waiting on human-observed live Testnet
re-verification).

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
