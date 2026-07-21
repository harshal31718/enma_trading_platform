# Plan 8 — Governance, correctness & cleanup

**Status:** Ready · **Priority:** P3 (last) · **Depends on:** 3, 5, 6 · **Related:** all

> Source issues: SYS-3, SYS-4, SYS-7, ENG-8, ENG-14, ENG-15, ENG-18, SEC-8 (remainder),
> SEC-10. The trailing correctness fixes and the reconciliation of docs to the new reality.
> Last because much of it only makes sense once Plans 3/5/6 have changed what the docs should
> describe.

## Goal

Documentation matches the shipped architecture, the remaining correctness traps are closed,
and the smaller hardening items are done.

## Scope / what changes

### Step 8.1 — Reconcile governance docs to reality (issue SYS-4, SYS-3) · **✅ shipped 2026-07-16 (fixes-queue F6)**
- **Correction to this step's own premise:** the original SYS-4 finding ("Node's internal
  handlers place orders" / "no direct Binance calls outside engine is already false") was
  audited against the actual call graph and does **not** hold — `algo.controller.js`'s
  "internal handler" functions (`handleAlgoPlaceOrder` etc., called by the engine over
  `/internal/*`) only decrypt credentials and forward them back to the engine via
  `engineClient`; they never call Binance directly. `CLAUDE.md`/`AGENTS.md` Rule 2 was already
  literally true. What *was* genuinely stale: (a) the rule's phrasing didn't carve out the
  client's direct public Binance WebSocket for market data, creating a false-contradiction with
  the architecture doc — fixed by qualifying both to "no *signed/authenticated*" calls; (b) the
  source-of-truth hierarchy (`.claude/GOVERNANCE.md`) never mentioned Plan 5's `executionEvents`
  log — added a note; (c) several unrelated real drift items were found instead: `ARCHITECTURE.md`
  still said "invite-only" (Plan 1 shipped open login 2026-07-14) and "Mainnet not implemented"
  (mainnet read-only balance/verify has existed since Plan 4/20); `strategy-management/SPEC.md`'s
  "Key Invariants" section still asserted live code-editing validation (Plan 3.2 removed the
  feature 2026-07-15, but this one bullet was missed in that pass); `client/CLAUDE.md` still
  documented a stale `binanceWS.js` path (`/ws`/`/stream` instead of the real `/public/ws`,
  `/market/ws`); `DECISIONS.md` §6 never got an entry for the invite-only→open-login transition.
  All fixed same session — see `handoff.md`'s 2026-07-16 entry for the full file list.
- Document the strategy-asset model decided in Plan 3.2 (retired UI editing / sandboxed worker)
  including versioning and the prod named-volume divergence (`engine/strategies` volume makes
  deployed code differ from the image — SYS-3). **Not done this pass** — the SYS-3 named-volume
  divergence item is a distinct, still-open doc gap; carried forward, not part of F6's scope
  (which was strictly the truth-telling audit, not new documentation of undocumented behavior).
- Acceptance check: no invariant in the governance docs is contradicted by the code — confirmed
  via a dedicated audit subagent pass, findings applied same session.

### Step 8.2 — Application-layer request validation (issue SEC-10) · **✅ shipped 2026-07-21**
- Add a schema-validation layer (zod/joi/celebrate) to the Node API. Controllers stop
  destructuring raw `req.body`. Special attention to any handler writing user-influenced field
  paths into Mongo `$set` (the `positionDetails.${symbol}` pattern) — validate/whitelist keys.
- Acceptance check: malformed bodies are rejected at the edge with 400; injection-shaped keys
  are refused.
- **Surveyed before implementing** (Explore agent over every controller's actual validation
  state) rather than assuming every controller needed a rewrite: `settings.controller.js`,
  `risk.controller.js` (both large dynamic FIELD_RULES-driven validators), `admin.controller.js`,
  and `lab.controller.js` (via `utils/labConfig.js`'s `buildMonteCarloConfig`/etc.) already had
  adequate hand-rolled inline validation — throwing `ApiError(400, 'VALIDATION_ERROR', ...)` on
  every malformed field, same as a schema library would. Force-migrating those to zod would have
  been stylistic churn with real regression risk (some of that logic carries forward previous
  saved-settings values on a partial update — not a pure stateless schema shape), not a genuine
  gap closure — left as-is, documented rather than silently incomplete.
- **The actual load-bearing gap, found by the survey**: `server/src/services/algoSessionService.js`'s
  `processEngineStatsUpdate` (called from the *unauthenticated* internal engine-callback route
  `PATCH /internal/algo/sessions/:id/stats`, gated only by a shared `X-Internal-Key`, not per-user
  JWT) builds `positionDetails.${eventData.symbol}` / `lastSeqBySymbol.${seqSymbol}` Mongo
  `$set`/`$unset` path segments straight from the request body, with zero format check — exactly
  the pattern this step's own text calls out. Fixed with a new shared
  `server/src/utils/symbolFormat.js` (`SYMBOL_REGEX = /^[A-Z0-9]{5,20}$/`, matching real Binance
  USDT-M futures symbols, rejecting `.`/`$`/`__proto__`-shaped keys) and a whitelist guard at the
  top of `processEngineStatsUpdate` that throws `ApiError(400, 'VALIDATION_ERROR', ...)` on any
  invalid `eventData.symbol` or `positionDetails` key before either reaches a template-literal
  path. Same util applied to every other internal engine-callback handler in
  `algo.controller.js` (`handleAlgoPlaceOrder`/`ClosePosition`/`SetLeverage`/`GetPosition`/
  `GetOpenOrders`, via a new shared `_rejectIfInvalidSymbol` helper) and to the user-facing
  `startSession`/`startChaos` symbol arrays (same symbols later flow through the engine callback
  into the same `positionDetails` path) and `trade.controller.js`'s 6 order-placement/leverage/
  margin-type routes, closing the pattern uniformly rather than just at the one call site the
  survey happened to name.
- **New schema-validation layer**: `zod` added as a dependency (`express-validator` stays a listed
  but genuinely dead dependency — already true before this step, not newly introduced), new
  generic `server/src/middleware/validate.js` (`validate(schema, source='body')` — parses,
  replaces `req[source]` with the typed result on success, throws the same
  `ApiError(400,'VALIDATION_ERROR',...)` shape as every other validation failure in this codebase
  on failure) and `server/src/validators/strategy.validators.js`. Applied to `POST /strategies`
  (`createStrategy`) — the one route with genuinely **zero** prior validation (raw destructure,
  forwarded straight to the engine).
- **Verified**: real `docker compose build server` + container restart (zod installed into the
  named `enma_server_node_modules` volume, host `node_modules` never touched), full jest suite
  252/252 (233 existing + 19 new: `symbolFormat.test.js`, `validate.test.js`,
  `strategy.validators.test.js`, 4 new `algoSessionService.test.js` cases for the symbol-key
  whitelist), `/health` 200 throughout, no regressions.

### Step 8.3 — Warmup/readiness math (issue ENG-8) · **✅ shipped 2026-07-21**
- Fix `_get_min_candles_required` vs `WARMUP_CANDLES` vs the 500-candle `_append_candle` cap so
  readiness is always reachable: reconcile the "×3" code with the "2x" docstring, stop
  conflating unrelated numeric params (an RSI threshold of 70 shouldn't demand 210 candles —
  drive warmup off declared lookback windows, not "largest numeric param"), and ensure the cap
  ≥ the requirement.
- Golden-master before/after (touches indicator warmup). Acceptance check: a strategy with a
  large lookback becomes ready deterministically; no permanent-warmup state.
- **Surveyed before designing**: the old `_get_min_candles_required` (`core/live_bot_manager.py`)
  scanned every `PARAMS` entry for the largest numeric value regardless of meaning, then applied
  a hardcoded ×3 buffer contradicting its own "2x" docstring. **Confirmed as a live, not
  hypothetical, bug**: with default config, `MicroMacroRSIDivergence`'s `max_pivot_bars=500` (a
  bar-distance sanity cap, not a lookback) dominates the scan → 500×3=1500 required; separately,
  `AdaptiveTrend`'s genuine `trend_period=200` lookback → 200×3=600 required. Both exceed the
  hardcoded 500-candle `append_candle` retention cap — **2 of the 5 seeded strategies were
  already permanently stuck in "warming up" with stock defaults**, never trading, before this fix.
- **Found the real fix while investigating, not invented**: every strategy already declares its
  own correct warmup requirement via `BaseStrategy.MIN_WARMUP_CANDLES` (`core/strategy.py`,
  default 50) — hand-tuned per strategy (MicroScalper 25, MicroMacroRSIDivergence 30,
  MultiDivergence 60, BestSupertrend defaults to 50, AdaptiveTrend 210) and **already the exact
  value `services/backtest_runner.py:1213` uses** (`max(strategy.MIN_WARMUP_CANDLES, min(50,
  len(rows)-2))`) to size the backtest's own warmup period. The live path's PARAMS-scanning
  function was a second, independently-wrong computation of a concept the strategy already
  declares correctly — not a case needing a new metadata flag (no `lookback=True` param
  attribute needed). Rewrote `_get_min_candles_required` to `max(50, strategy.MIN_WARMUP_CANDLES)`
  — same floor backtest_runner applies, now genuinely at parity with backtest's warmup semantics.
- **Cap ≥ requirement, made checkable rather than assumed**: extracted the `append_candle` magic
  number into a named `MAX_CANDLES_RETAINED = 500` (`core/market_data_feed.py`). All 5 seeded
  strategies' declared values now sit safely under it (max is AdaptiveTrend's 210). For any
  future strategy that declares more, added a session-start check (mirrors the existing
  HTF-insufficient-candles session-visible-error pattern a few lines below it in
  `live_bot_manager.py`) that logs + notifies the session with a clear message rather than
  silently sitting in unreachable "warming up" forever — the failure stays possible for a
  misconfigured future strategy, but is now diagnosable instead of a silent black box.
- **Verified**: new `engine/tests/test_min_candles_required.py` (6 cases — declared-value read,
  the 50-floor, the missing-attribute fallback, the unrelated-large-param-ignored regression
  case, all 5 seeded strategies' values staying under the cap, and the over-cap case still
  computing correctly for the visibility check to catch). Full container pytest 659/659 (653 + 6
  new), golden-master byte-identical (`MultiDivergence trades=55 netProfit=-1784.02 winRate=0.36
  cagr=-71.32 sqn=-2.08` — expected, this is a live-only code path, zero backtest overlap). Real
  `docker restart` on the engine container: clean boot, all 5 strategies seeded, `/health` 200.

### Step 8.4 — Candle column-order safety (issue ENG-15) · **✅ shipped 2026-07-21**
- Replace positional `candle[1..5]` indexing and the per-fetcher OHLC remap with named
  constants/accessors (or a typed candle struct) so the nonstandard
  `[ts, open, close, high, low, volume]` layout can't be silently mis-mapped.
- Golden-master before/after. Acceptance check: column access is by name; a remap mistake is a
  test failure.
- **Surveyed before designing**: found a working precedent already existed — `engine/indicators/base.py`
  had its own `OPEN, CLOSE, HIGH, LOW, VOLUME = 1, 2, 3, 4, 5` and every indicator adapter already
  used it correctly. The bug wasn't absence of named constants; it was that **every other
  consumer re-derived the same mapping independently with bare literals** — surveyed blast
  radius: ~50-55 production call sites across `core/kernel.py` (~14), `core/market_data_feed.py`
  (~19), `core/strategy.py` (the `self.open/high/low/close/volume` properties every strategy
  author relies on), `core/live_bot_manager.py` (live-WS kline handling), `services/backtest_runner.py`
  (3 near-identical `column_stack` remap blocks), `core/models/cost.py`, and 2 seeded strategy files
  reading columns directly. **Confirmed as a real (if latent) risk, not hypothetical**: the
  duplication is exactly how a copy-paste remap mistake stays silent — one wrong literal in any
  one of ~50 sites has zero cross-check against any other.
- **New `core/candle_columns.py`** — canonical `TIMESTAMP, OPEN, CLOSE, HIGH, LOW, VOLUME = 0..5` +
  `NUM_COLUMNS = 6` + a shared `build_candle_array(timestamps, opens, highs, lows, closes,
  volumes)` builder (named args state the *source* order explicitly, not just the *target*
  order). `engine/indicators/base.py` now imports the constants from here instead of
  re-declaring them — one definition, not two. Every production call site above migrated to
  import and use these constants (`market_data_feed.py`'s 3 fetchers + `append_candle`,
  `kernel.py`'s ~14 sites, `strategy.py`'s 5 properties + `htf()`'s timestamp alignment,
  `live_bot_manager.py`'s reconcile/time_t/HTF-append read sites, `models/cost.py`'s 2 sites,
  `MultiDivergence`/`MicroMacroRSIDivergence`'s direct column reads). `backtest_runner.py`'s 3
  `column_stack` blocks now call the shared `build_candle_array` instead of each hand-rolling its
  own column order — a wrong order there now breaks identically for all 3 callers instead of
  silently diverging between them. Strategy files import via `engine.core.candle_columns` (the
  documented alias path every strategy author already uses for `engine.core.strategy`/
  `engine.core.models`), not `core.candle_columns` directly.
- **Found and closed a real test gap while surveying, not just adding new tests**:
  `test_fetch_candles_from_rest_excludes_open_candle` was the ONLY existing test that actually
  verified the Binance-kline-to-engine-layout swap (close=kline idx4, high=kline idx2, low=kline
  idx3) — the structurally-identical `fetch_htf_candles` had zero swap coverage, and
  `fetch_warmup_candles`'s existing test reused `open=high=low=close` in its fixture, which can't
  distinguish column positions at all. Added `test_fetch_warmup_candles_column_order` (distinct
  O/H/L/C values) and strengthened `test_fetch_htf_candles_same_shape_as_base` with the same
  swap assertions the REST test already had.
- **Verified**: full container pytest 660/660 (659 + 1 new — `test_min_candles_required.py`'s 6
  cases from 8.3 already counted; this step adds 1 net new test plus 2 strengthened existing
  ones), golden-master byte-identical before/after (`MultiDivergence trades=55 netProfit=-1784.02
  winRate=0.36 cagr=-71.32 sqn=-2.08`), real `docker restart` on the engine container — clean
  boot, all 5 strategies seeded without error across 4 consecutive restarts, `/health` 200.

### Step 8.5 — Make embedded policy choices explicit (issue ENG-18, ENG-14)
- Document (and make configurable where reasonable) the SL-before-TP same-candle exit ordering
  in `check_exits` — currently a silent pessimism bias in branch order.
- Validate `strategy_name` in the live path (`start_session`) the same way the strategies
  router does; ensure a strategy load/param failure notifies Node and marks the symbol/session
  failed instead of silently killing the task.
- Acceptance check: invalid strategy/params surface as a visible session error; the exit-order
  policy is documented at the decision point.

### Step 8.6 — Multi-session same-account modelling (issue SYS-7) · **✅ verified-already-shipped 2026-07-18**
- **Correction to this step's own premise:** checked the actual code before deciding anything
  (per the user's explicit "forbid overlapping symbols per account" choice) and found the
  conflict this step worries about is already structurally impossible — `services/symbolLock.js`
  wraps every symbol in an atomic Redis `SET NX` lock, and both `startSession` and `startChaos`
  (`controllers/algo.controller.js`) already acquire it (reason `"bot"`, tagged with the owning
  `sessionId`) before ever calling the engine, with rollback (session doc deleted, any
  already-acquired locks released) on any failure including a `SYMBOL_LOCKED` 409 from a losing
  concurrent attempt. A second session — same account or not — cannot acquire a symbol the first
  already holds; the acceptance check ("starting two sessions that would trade the same symbol...
  is prevented") was already true. **Bonus finding, out of this step's stated scope**: the lock
  key isn't scoped by `userId` at all, so it's actually stricter than asked — it also prevents
  two *different* users' sessions from trading the same symbol simultaneously, which has nothing
  to do with SYS-7's actual concern (shared margin on ONE account) since different users trade
  through different Binance accounts. Left as-is — over-restrictive-but-safe, not a correctness
  bug, and narrowing it to per-account scoping is a separate, smaller follow-up if the UX
  friction of it ever comes up (unlikely in practice: Chaos Mode already round-robins ~120
  symbols across up to 10 concurrent bots per account, so real cross-user contention on a specific
  symbol is rare).
- **Verified:** new `server/src/services/__tests__/symbolLock.test.js` (5 cases, `ioredis-mock`)
  — a second session cannot lock a symbol the first holds (409 `SYMBOL_LOCKED`), the lock records
  its owning `sessionId`, a non-owning session's release call is a no-op, the symbol becomes
  available again after the true owner releases it, and a genuine concurrent race (`Promise.
  allSettled` on two simultaneous lock attempts) resolves to exactly one winner. Full server
  suite: 94 → **99/99 passed**.
- Acceptance check: starting two sessions that would trade the same symbol on one account is
  prevented or explicitly warned. **Already true — no code change needed.**

### Step 8.7 — Remaining small hardening (issue SEC-8) · **✅ shipped 2026-07-21**
- Finish any constant-time-compare / health-endpoint items not already covered by Plans 2/3
  (e.g. the `/health` Redis new-connection-per-request churn).
- Acceptance check: health check reuses a connection; no timing-unsafe secret compares remain.
- **Surveyed before implementing**: constant-time compares were already fully closed by Plan 3
  Step 3.5 — `requireInternalKey.js` (Node) uses `crypto.timingSafeEqual`, engine's `X-API-Key`
  check uses `hmac.compare_digest`, no manual JWT/raw-token string comparison exists anywhere.
  Engine's own `/health` already reuses its pooled Mongo/TimescaleDB clients (motor singleton,
  asyncpg pool) — no fix needed there. **The only real gap**: `server/src/app.js`'s `/health`
  opened (and tore down) a brand-new `ioredis` connection on every single request instead of
  reusing the shared `config/redis.js` singleton.
- Fixed by reusing the shared singleton, wrapped in a 2s timeout — the singleton is created with
  `maxRetriesPerRequest: null` (BullMQ's own requirement), so a queued command on an unreachable
  Redis would otherwise wait indefinitely instead of rejecting, turning a health check into a
  hang. Extracted the check logic into new `server/src/utils/healthCheck.js`
  (`checkMongoHealth`/`checkRedisHealth`) specifically so it's unit-testable without requiring
  the whole `app.js` — found while writing the test that `app.js` transitively opens its own
  real Redis connections via `socketEmitter.js`'s pub/sub subscriber and the 4 BullMQ queue
  definitions, and that `ioredis-mock` doesn't implement the `.call()` method `rate-limit-redis`'s
  `RedisStore` needs — both made a full-`app.js`-via-supertest test hang/fail for reasons
  unrelated to the actual fix. The extracted-module approach sidesteps both.
- **Verified**: new `server/src/utils/__tests__/healthCheck.test.js` (6 cases: reuses the given
  client, `.ping()` failure returns `'error'`, a never-resolving `.ping()` still returns `'error'`
  within the timeout rather than hanging, Mongo disconnected/connected/erroring). Full server jest
  suite 258/258 (252 + 6 new), 100% coverage on the new file. Real `docker restart` on the server
  container, `curl /api/v1/health` → `{"status":"ok","mongo":"connected","redis":"connected"}`.

## Out of scope
- New features. This plan closes gaps and truth-tells the docs.

## Acceptance criteria (phase)
- Governance docs contain no invariant the code contradicts.
- API validates request bodies; injection-shaped keys refused.
- Warmup readiness is always reachable; candle access is by name.
- Embedded policy choices are documented/configurable; live strategy failures are visible.
- Multi-session account conflict is prevented or warned.
- Golden-master identical or explained; CI green.

## Open questions
- ~~8.6 is partly a product decision (allow overlapping-symbol sessions at all?)~~ — resolved
  2026-07-18: the existing atomic symbol lock already forbids it; no code change needed
  (see Step 8.6 above).

## Handoff note template
`Next session: [steps done 8.x], [next step], [golden-master result], [files changed]`
