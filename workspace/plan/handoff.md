# Session Handoff Log

Resume prompts for cross-session continuity (root `CLAUDE.md` Rule G / `AGENTS.md` → Session Handoff).

**Format rules:**
- Newest entry on top: `## <date> — <title> — <status>` with **Goal / Done / Files changed / Open questions**.
- Keep at most the **3 most recent entries**. When adding a new one, delete the oldest — git history is the archive. This file must stay a short resume prompt, not a project log.

---
## 2026-07-21 (later same day) — Plan 23 (MarginSurge strategy) — VALIDATION FAILED, not shipped — Done

**Goal:** user said "proceed and start working on plan23 and work non-stop... use recommended
paths, do not stop" — full autonomy, no mid-session questions, respecting the plan's own
pre-resolved open questions (validate both 5m/15m, fixed majors BTC/ETH/SOL/BNB, respect a losing
verdict).

**Implemented** `engine/strategies/MarginSurge/__init__.py` per the plan's §2/§3/§5 spec: Donchian
breakout from a BB(20) squeeze (bottom `squeeze_pct` of a rolling-200 bandwidth-percentile
history — vectorized via `sliding_window_view`, verified bit-identical to a naive loop before use),
ADX(14) rising + MFI(14) flow + EMA(200) trend confirmation; `AtrBracketRiskModel` +
`RiskBudgetPortfolio` for the SL/breakeven/trail/ATR-percentile-veto and sizing (no new model
classes, as the plan specified). One real engineering finding along the way: the time-stop
(`max_hold_candles`) can't use `on_open_position()` for entry-index tracking because `LiveAdapter`
never calls that hook (only `BacktestAdapter` does) — used `self.is_open`/`self.index`/`self.vars`
instead, which both adapters keep consistent. Registered in `strategy_seeder.py`, added to
`test_boundaries.py` (24/24 boundary cases now, 6 strategies) and `lookahead_sentinel.py` (PASS —
no divergence between full-array and expanding-window `prepare()`).

**Ran the plan's own validation gates 1-4, then stopped per the plan's own explicit framing.**
Gate 1 (cost-realism, default params) and a diagnostic re-run (isolating alpha quality from
margin-rejection noise) both showed **negative expectancy on every tested symbol/timeframe combo**
— not a marginal miss, -18 to -114 $/trade across the board. Gate 4 (grid-optimize 64 combos +
manual OOS split) made this unambiguous: the best in-sample combo (Sharpe 1.76, +7.3%) **inverted
sign out-of-sample** (-17.8%, win rate 22%) — textbook overfitting, exactly what the plan's QNT-6
warning anticipated. Gates 5-6 (Monte Carlo/leverage selection, chaos stress) were deliberately
**not run** — gate 4's OOS failure is itself a kill per the plan's own gate ordering; spending more
compute there would manufacture false confidence from an already-disproven trade sample, not
produce real signal.

**Verdict: DO NOT SHIP — a valid, fully-documented terminal outcome per the plan's own explicit
framing** ("the correct outcome of this plan is 'don't ship it' — that is a success of the process,
not a failure"). The code stays in the codebase as a boundary-clean, lookahead-clean reference
implementation (the engineering is correct; the specified alpha has no edge) — seeded with its
validation outcome stated explicitly in the description so it's never mistaken for a
ready-to-trade strategy. This is the first strategy this codebase has run through a full formal
gate sequence and rejected; recorded as `DECISIONS.md` #29 to set the precedent that this is a
legitimate outcome, not an abandoned task.

**Verified:** engine pytest 670/670, golden-master byte-identical (additive-only, zero impact on
the 5 existing strategies), engine container restarted clean with all 6 strategies seeded across
multiple restarts. No browser/UI verification was performed — no browser-automation tool was
available in this session; verified instead via direct MongoDB reads and the engine's own health
endpoint, which the user should be aware of if they specifically wanted a visual Strategies-page
check.

**Files changed:** new `engine/strategies/MarginSurge/__init__.py`, new
`workspace/docs/strategies/MarginSurge.md`, `engine/services/strategy_seeder.py`,
`engine/tests/test_boundaries.py`, `engine/scripts/lookahead_sentinel.py`,
`workspace/docs/strategies/INDEX.md`, `workspace/docs/features/strategy-management/SPEC.md`,
`workspace/docs/state/CURRENT_STATE.md`, `workspace/docs/core/DECISIONS.md` (#29),
`workspace/plan/23_high-risk-leverage-strategy.md`, `workspace/plan/0_tracker.md`, this file.
Several throwaway validation scripts (`engine/scripts/_plan23_*.py`, `_smoke_marginsurge.py`) were
written, run, and deleted — not part of the permanent codebase.

**Open questions:** none — the plan's own §8 open questions were all pre-resolved by the user's
"do not stop" instruction and are now moot given the don't-ship verdict. If a future session wants
to revisit MarginSurge's alpha (different entry logic, different symbols/timeframes), start from
this file's implementation and re-run the full gate sequence — do not assume the current entry
conditions have any edge just because the code passes boundary/lookahead checks.

---
## 2026-07-21 — Plan 6 closed (d5) + Plan 8 FULLY SHIPPED (8.2–8.5, 8.7 + SYS-3 doc close-out) — Done

**Goal:** user asked to continue with `workspace/`. Surveyed the tracker, found three
not-`Done` items (Plan 6's d5, Plan 8's 8.2–8.5/8.7, Plan 23 draft), asked which to continue —
user picked Plan 6 d5. Per its own scoping note (`d5 ... needs its own separate DECISIONS.md
entry`), argued against doing it before writing any code (d1-d4 already deliver the actual
technical goal — every internal consumer reads `active_bracket`; retiring
`self.stop_loss`/`self.take_profit` as the strategy-facing *write* API on top of that adds zero
functional benefit for real cost: every seeded strategy + `trail_stop()`/`move_to_breakeven()` +
`engine/CLAUDE.md`'s public contract would need touching). User agreed — **d5 dropped, Plan 6 has
no remaining scope.** Then proceeded to Plan 8 per the user's explicit "proceed with plan 8."

**Plan 6 d5 close-out**: updated `6_engine-decomposition-and-exchange-abstraction.md` (d5 marked
dropped with rationale), `0_tracker.md` (Plan 6 row → **Done**), `DECISIONS.md` (fourth addendum
to the #28 chain recording the drop + rationale).

**Plan 8 Step 8.2 (SEC-10, schema-validation layer) shipped.** Surveyed every controller's actual
validation state via an Explore agent before writing anything (not assumed) — found most
controllers (`settings.controller.js`, `risk.controller.js`, `admin.controller.js`,
`lab.controller.js` via `utils/labConfig.js`) already had adequate hand-rolled inline validation;
force-migrating those to zod would have been stylistic churn with real regression risk, not a
genuine gap closure, so left as-is (documented, not silently incomplete). **The actual load-bearing
gap**: `algoSessionService.js`'s `processEngineStatsUpdate` (reached via the *unauthenticated*
internal engine-callback route `PATCH /internal/algo/sessions/:id/stats`, gated only by a shared
key, not per-user JWT) builds `positionDetails.${eventData.symbol}` / `lastSeqBySymbol.${symbol}`
Mongo `$set`/`$unset` paths straight from the request body with zero format check — exactly SEC-10's
own named pattern. Fixed with new `server/src/utils/symbolFormat.js`
(`SYMBOL_REGEX = /^[A-Z0-9]{5,20}$/`) + a whitelist guard at the top of `processEngineStatsUpdate`
that throws `ApiError(400,'VALIDATION_ERROR',...)` before any invalid symbol reaches a
template-literal path. Same util applied uniformly to every other internal engine-callback
handler in `algo.controller.js`, `startSession`/`startChaos`'s symbol arrays, and
`trade.controller.js`'s 6 order/leverage/margin routes — not just the one site the survey named.
Also added the actual "schema-validation layer" the step calls for: `zod` dependency, generic
`server/src/middleware/validate.js`, and `server/src/validators/strategy.validators.js` wired onto
`POST /strategies` (the one route with genuinely zero prior validation).

**Verified**: real `docker compose build server` (zod installed into the named
`enma_server_node_modules` volume, host `node_modules` untouched) + container restart, full jest
suite 252/252 (233 existing + 19 new), `/health` 200 throughout.

**Files changed:** new `server/src/utils/symbolFormat.js` (+ test), new
`server/src/middleware/validate.js` (+ test), new `server/src/validators/strategy.validators.js`
(+ test), `server/src/services/algoSessionService.js` (+ 4 new tests),
`server/src/controllers/algo.controller.js`, `server/src/controllers/trade.controller.js`,
`server/src/routes/strategy.routes.js`, `server/package.json` (added `zod`), `server/CLAUDE.md`.
Docs: `6_engine-decomposition-and-exchange-abstraction.md`, `8_governance-correctness-and-cleanup.md`,
`0_tracker.md`, `DECISIONS.md`, this file.

**Plan 8 Step 8.3 (ENG-8, warmup/readiness math) shipped, user said "proceed."** Surveyed the
actual code (Explore agent) before designing — found the bug was already live, not hypothetical:
`_get_min_candles_required` (`core/live_bot_manager.py`) scanned every strategy `PARAMS` entry for
the largest numeric value regardless of meaning, then applied a hardcoded ×3 buffer contradicting
its own "2x" docstring. With default config this left **2 of the 5 seeded strategies permanently
stuck in "warming up," never trading**: `MicroMacroRSIDivergence`'s `max_pivot_bars=500` (a
bar-distance cap, not a lookback) dominated the scan → 1500 required; `AdaptiveTrend`'s genuine
`trend_period=200` → 600 required — both past the hardcoded 500-candle `append_candle` retention
cap. **Found the real fix while investigating, not invented**: every strategy already declares its
own correct warmup requirement via `BaseStrategy.MIN_WARMUP_CANDLES` — already the exact value
`services/backtest_runner.py` uses for the backtest's own warmup period. Rewrote
`_get_min_candles_required` to `max(50, strategy.MIN_WARMUP_CANDLES)`, giving live/backtest parity
instead of a second, independently-wrong computation — no new params.py metadata flag needed.
Extracted the 500 cap into a named `MAX_CANDLES_RETAINED` (`core/market_data_feed.py`) and added a
session-start visibility check (mirrors the existing HTF-insufficient-candles pattern) that logs +
notifies the session if a strategy's declared requirement ever exceeds the cap, rather than a
silent unreachable state.

**Verified**: new `engine/tests/test_min_candles_required.py` (6 cases), full container pytest
659/659 (653 + 6 new), golden-master byte-identical (live-only change, zero backtest overlap —
confirmed via before/after `golden_master.py run` + `compare`), real `docker restart` on the
engine container (clean boot, all 5 strategies seeded, `/health` 200).

**Files changed:** `engine/core/live_bot_manager.py`, `engine/core/market_data_feed.py`, new
`engine/tests/test_min_candles_required.py`. Docs: `8_governance-correctness-and-cleanup.md`,
`0_tracker.md`, this file.

**Plan 8 Step 8.4 (ENG-15, candle column-order safety) shipped, user said "proceed."** Surveyed
first (Explore agent) — found `engine/indicators/base.py` already had working named constants
(`OPEN, CLOSE, HIGH, LOW, VOLUME`) used correctly by both indicator adapters, but every OTHER
consumer independently re-derived the same `[ts, open, close, high, low, vol]` mapping with bare
integer literals — ~50-55 production call sites across `core/kernel.py` (~14),
`core/market_data_feed.py` (~19), `core/strategy.py` (the `self.open/high/low/close/volume`
properties every strategy relies on), `core/live_bot_manager.py`, `services/backtest_runner.py`
(3 near-identical `column_stack` blocks), `core/models/cost.py`, and 2 seeded strategy files. New
`core/candle_columns.py` — canonical constants + a shared `build_candle_array()` builder —
migrated every one of those sites onto it; `indicators/base.py` now imports from it instead of
re-declaring. **Found and closed a real test gap while surveying**: `fetch_htf_candles` (a
structural duplicate of the one fetcher that WAS tested for the OHLC swap) had zero swap
coverage, and `fetch_warmup_candles`'s existing test used `open=high=low=close` in its fixture,
which can't distinguish column positions at all — added/strengthened both.

**Verified**: full container pytest 660/660 (1 net new test — `test_fetch_warmup_candles_column_order`
— plus 2 existing tests strengthened with real O≠H≠L≠C fixture values), golden-master
byte-identical before/after, real `docker restart` on the engine container across 4 consecutive
restarts — clean boot, all 5 strategies seeded every time, `/health` 200.

**Files changed:** new `engine/core/candle_columns.py`, `engine/core/kernel.py`,
`engine/core/strategy.py`, `engine/core/market_data_feed.py`, `engine/core/live_bot_manager.py`,
`engine/services/backtest_runner.py`, `engine/core/models/cost.py`,
`engine/strategies/MultiDivergence/__init__.py`,
`engine/strategies/MicroMacroRSIDivergence/__init__.py`,
`engine/indicators/base.py`, `engine/tests/test_market_data_feed.py`, `engine/CLAUDE.md`. Docs:
`8_governance-correctness-and-cleanup.md`, `0_tracker.md`, this file.

**Plan 8 Step 8.7 (SEC-8, health/timing hardening) shipped.** Surveyed first — constant-time
compares were already fully closed by Plan 3 Step 3.5 (Node `requireInternalKey.js` uses
`crypto.timingSafeEqual`, engine's `X-API-Key` check uses `hmac.compare_digest`), and engine's own
`/health` already reuses pooled Mongo/TimescaleDB clients. The only real gap: `server/src/app.js`'s
`/health` opened (and tore down) a brand-new `ioredis` connection every request instead of reusing
the shared `config/redis.js` singleton. Fixed, bounded by a 2s timeout (the singleton's
`maxRetriesPerRequest: null` would otherwise let an unreachable Redis hang the check indefinitely).
Extracted the check logic into new `server/src/utils/healthCheck.js` specifically so it's testable
without requiring the whole `app.js` — found while writing the test that `app.js` transitively
opens its own real Redis connections via `socketEmitter.js`/BullMQ queues, and `ioredis-mock`
doesn't implement the `.call()` method `rate-limit-redis` needs; both made a full-app supertest
hang/fail for reasons unrelated to the fix. Verified: new `healthCheck.test.js` (6 cases), full
server jest 258/258, real `docker restart`, `curl /api/v1/health` correct.

**Plan 8 Step 8.5 (ENG-18/ENG-14) shipped, closing out Plan 8 entirely.** ENG-18 (SL-before-TP
same-candle exit ordering) turned out **already fully satisfied** by a prior session's Plan 9 Step
9.8 work — verified via survey rather than assumed: already documented in 3 places (kernel.py
docstring, the exact decision-point comment, `engine/CLAUDE.md`) and already configurable via the
opt-in `intrabar_detail` resolution, with existing test coverage. No code change needed — reported
the finding rather than silently claiming new work. ENG-14 was the real gap: `start_session` never
validated `strategy_name` (unlike the strategies router) and its dynamic strategy import/param
validation had zero failure visibility — since `start_session` runs as a fire-and-forget FastAPI
background task, the only way a load failure could ever reach the user is an engine→Node
notification, and none existed; the session just stayed "starting" forever. New
`engine/utils/strategy_names.py` shares the same regex the router already used; `start_session` now
validates upfront and wraps the dynamic import, notifying Node with `status:'error'` +
`errorMessage` on failure (reusing infrastructure `processEngineStatsUpdate` already supported but
the engine never called). `_run_symbol_loop`'s per-symbol param-validation failure gets the same
treatment via the existing per-symbol log+notify pattern. Verified: new
`test_strategy_load_failure.py` (6 cases), full container pytest 666/666, golden-master
byte-identical, engine restarted clean.

**Also closed while wrapping up Plan 8**: Step 8.1's own explicitly-deferred SYS-3 doc item (the
prod `enma_engine_strategies` named-volume divergence — a strategy created via `POST /strategies`
persists in the volume across redeploys without ever being committed to the repo) — added as a new
Key Invariant in `workspace/docs/features/strategy-management/SPEC.md`. **Plan 8 is now fully
shipped — all of 8.1–8.7 done, no remaining scope.**

**Files changed (8.7):** `server/src/app.js`, new `server/src/utils/healthCheck.js` (+ test),
`server/CLAUDE.md`. **Files changed (8.5):** new `engine/utils/strategy_names.py`,
`engine/routers/strategies.py`, `engine/core/live_bot_manager.py`, new
`engine/tests/test_strategy_load_failure.py`. **Files changed (SYS-3 close-out):**
`workspace/docs/features/strategy-management/SPEC.md`. Docs:
`8_governance-correctness-and-cleanup.md` (Status → Done), `0_tracker.md` (Plan 8 row → Done),
this file.

**Open questions:** none. Plan 8 has no remaining scope. Per the tracker's Execution order
section, next unblocked work would be Plan 23 (MarginSurge strategy, Draft, backtest-gated work
can start now) or the Quant track's remaining items (9.7-9.10-adjacent follow-ups, if any resurface).

---
## 2026-07-20 (later same day, part 17) — Plan 7 COMPLETE: ChaosWizard.jsx + hooks factory

**Goal:** user said "proceed with completion of 7," then mid-task "do not stop without completing
plan 7." Finished the two remaining items from the prior entry: ChaosWizard.jsx's decomposition
and the "hooks share a factory" sub-item.

**ChaosWizard.jsx (677 lines, one ~600-line function + `ScopedSymbolPicker` helper) → 413 lines.**
Same pattern as Backtest.jsx's tabs: `ScopedSymbolPicker` moved as-is to `components/algo/`
(sibling to the existing `SymbolPicker.jsx`), the 4 wizard steps each became their own component
under `components/algo/chaos/`, all state/handlers/the allocation-preview `useMemo` stayed in
ChaosWizard.jsx as the container. Verified in a real browser, not just the smoke test: opened the
dialog from `/algo`'s "Chaos Mode" button, selected MicroScalper, toggled Manual on the Allocation
step (confirms `ScopedSymbolPicker` renders and responds inside `Step2Allocation`), advanced
through Parameters (confirms `RiskParamsFields` still wires correctly) to Review (confirms every
value — timeframe/capital/leverage/risk/deployment summary — reflects the actual selections made
2 steps earlier), zero console errors specific to the new components.

**Hooks factory — surveyed before designing, not assumed.** The plan's "collapse duplicated
loading/error/toast logic across the 15 per-domain hooks" reads like it wants ~15 files touched.
Grepped for the actual toast-mutation pattern first (`toast.success`/`onError: (err) =>`) and
found it concentrated in exactly 2 files: `useAlgoSessions.js` (5 near-identical mutations) and
`useAlgoAccess.js` (2, invalidate-only, no toast). Every other hook file's mutations either do
something genuinely different per call, or — like `useTrade.js`'s 9 mutations, all toast-free —
deliberately leave error handling to the calling component's local `errorMessage` state, which is
client/CLAUDE.md's own documented convention (`Always use local errorMessage state... rendered as
an inline error banner`). Building one factory and mechanically routing all ~15 files through it
would have blurred that intentional split, not fixed a real duplication.

**Done:** new `client/src/lib/apiMutation.js`'s `useApiMutation({ mutationFn, invalidateKeys,
successMessage, errorFallback })`. Both `successMessage` and `errorFallback` are optional
specifically so the factory never forces a toast onto a mutation that never had one (this mattered
in practice: `useAlgoAccess.js`'s 2 mutations invalidate but never toast — the factory has to
support that shape, not just the toast-having one). Migrated all 7 mutations across the 2 files;
removed both files' now-dead `useMutation`/`useQueryClient` imports.

**Tests:** new `client/src/lib/__tests__/apiMutation.test.jsx` (7 cases, using
`@testing-library/react`'s `renderHook`) — mutationFn receives its argument and resolves the
response, success toast fires only when `successMessage` is given, no success toast when omitted,
error toast prefers the server's own message when `errorFallback` is given, falls back to
`errorFallback` when the error carries no server message, no error toast when `errorFallback` is
omitted, and every key in `invalidateKeys` gets invalidated. One TanStack Query v5 gotcha hit and
fixed: `mutationFn` receives a second context-object argument now, so asserting
`toHaveBeenCalledWith('payload')` failed — switched to checking `mock.calls[0][0]` instead.

**Verified:** `vite build` stable bundle size, `vitest` 22/22 (15 existing + 7 new), real-browser
check of `/algo` (which uses the migrated `useAlgoSessions()` hook file) — hard-reloaded, zero
console errors, page renders correctly.

**Files changed:** new `client/src/components/algo/ScopedSymbolPicker.jsx`, new
`client/src/components/algo/chaos/{Step1Strategies,Step2Allocation,Step3Parameters,
Step4Review}.jsx`, `client/src/components/algo/ChaosWizard.jsx` (rewritten), new
`client/src/lib/apiMutation.js`, new `client/src/lib/__tests__/apiMutation.test.jsx`,
`client/src/hooks/useAlgoSessions.js` (5 mutations migrated), `client/src/hooks/useAlgoAccess.js`
(2 mutations migrated), `client/CLAUDE.md`. Docs: `0_tracker.md` (Plan 7 row now **Done**), this
file.

**Also this round:** the user asked for a background agent to independently verify the
pre-existing uncommitted Plan 6 Step 6.3 (d3/d4, `active_bracket` migration) + Plan 21.5c
(batched-reconcile) engine changes that had been sitting in the working tree since before this
session started (I'd deliberately left them uncommitted in earlier commits, since I hadn't
reviewed or verified them myself). The agent read every diff, ran the touched tests in the real
Docker container (68/68 targeted, 653/653 full suite), and re-ran the golden master fresh
(byte-identical to the documented baseline) — verdict: clean, complete, matches the docs exactly,
safe to commit. Committed together with this session's Plan 7 work per the user's explicit `git
add .` instruction (see commit `<hash filled in below>`).

**Open questions:** none. **Plan 7 (server & client structure) is now fully shipped** — all of
7.1–7.5's stated scope is done: thin controllers with a tested service layer (7.1), no engine call
inherits the 1-hour timeout budget (7.2), `verifyJWT` splits 503/401 with a cached lookup (7.3),
all 4 named god-components decomposed (7.4), one documented realtime-price source + the
concentrated hooks-toast duplication collapsed + `dist/` already untracked (7.5). Plan 7 was the
last item astride the "Server & client structure" track in `0_roadmap.md`; check that file plus
`0_tracker.md`'s Execution order section for what's next in priority order.

