# 0 — Roadmap: Phased Execution Blueprint

**Role:** the *phase view* over the plan catalog — what to build, in what order, with per-step
objective/implementation/verification. Plan files (`N_<slug>.md`) remain the source of truth
for scope and acceptance; this file sequences them and carries the concrete pattern/tooling
choices from the research shelf (`research_*.md`, `audit_*.md`).
**History:** supersedes `refinements/04_improvement_roadmap.md` (folder dissolved 2026-07-14);
extended with Phase 0 and Phases 7–8 from the quant-core audit (`audit_2_quant-core.md`) and
Plan 10.

**Rules that bind every phase:** golden-master before/after any pipeline-touching change
(CLAUDE.md Rule C) · `handoff.md` entry after each phase (Rule G) · docs sync after each phase.
**Phases are decoupled:** each ends in a shippable, verifiable state.

**Tracks:** Phases 1→2→3 are strictly sequential (the platform-hardening track). Phase 0 is an
immediate parallel track. Phases 4–6 interleave once 3 is done. Phases 7–8 (quant track)
depend on Phase 0 + Phase 1's CI, not on the live-side phases. Phase 9 (feature-gap track,
plans 11–19, folded in 2026-07-15 — see `mergeContext.md`) is independent of all of the above;
it only needs its own V0 gate (11).

## Status snapshot (2026-07-16)

| Phase | Status | Remaining |
|-------|--------|-----------|
| 0 | ✅ **Shipped 2026-07-15** | — |
| 1 | ✅ **Shipped 2026-07-15** (Plans 2/3/4) | Redis `requirepass` (fixes-queue F8) |
| 2 | ✅ **Shipped 2026-07-15** (2.1/2.2 via Plan 3's RCE-path *removal*; 2.3 via Plan 2) | 2.4 (full OTel) — optional, deferred |
| 3 | 🟡 **Partial** — 3.1–3.4 shipped (as Plan 5 steps 5.3/5.2/5.4/5.1-scoped) | 3.5 (=5.5 Decimal), 5.6 (restart recovery), **Phase 3b below** |
| 3b | 🔴 **Unstarted** (added 2026-07-16, Plans 21+22) | All — the current P0 track |
| 4–6 | 🔴 Blocked on Phase 3 (Plan 5) fully landing | All (8.1 of Phase 6.3's Plan-8 scope shipped as F6) |
| 7 | 🟡 7.1 (=9.5) shipped | 7.2–7.5 (each golden-master re-baseline) |
| 8 | 🟡 8.1 core math (Plan 10 Phase 1a) shipped | 8.1 job plumbing, 8.2–8.4 |
| 9 | 🟡 9.1/9.2/9.4/9.5 shipped/verified | 9.3 (=Plan 13), 9.6 (=Plan 17) |

Completed-phase sections below are kept for reference (per-step verification detail); work
top-down from the snapshot + `0_tracker.md`'s Execution order.

---

## Phase 0 — Quant-Core P0 Bug Fixes (Plan 9 · steps 9.1–9.3) · ✅ **SHIPPED 2026-07-15**

Shipped-behavior bugs invalidating results users act on today. Full steps + acceptance:
[`9_backtest-and-optimizer-correctness.md`](9_backtest-and-optimizer-correctness.md) §9.1–9.3.
Evidence: [`audit_2_quant-core.md`](audit_2_quant-core.md) QNT-1/2/17.

- **0.1 (=9.1)** Multi-symbol exit-check fix — SL/TP/liquidation/funding never fire in
  portfolio backtests (`_entered_this_candle` never cleared in `_run_shared_portfolio`).
  Includes cash-conservation property test + 2-symbol golden-master scenario + stale-result
  flagging for existing multi-symbol `backtestResults`.
- **0.2 (=9.2)** Exec-algo close/flip pass-through — kernel erases `_close_at_open` /
  `_pending_flip` when a TWAP/VWAP/Iceberg algo is active.
- **0.3 (=9.3)** Persist full run config in `backtestResults`; leverage-sensitivity reads it
  back (today it re-runs with default params).

**Gate to exit:** multi-symbol bracket test green; exec-algo close/flip test green;
re-run-from-persisted-config reproduces the parent trade list.

## Phase 1 — Fail-Closed Foundations (Plans 2 + 3 + 4) · ✅ **SHIPPED 2026-07-15** (residual: F8 Redis auth)

### 1.1 Fail-closed encryption
- **Objective:** Missing/invalid `ENCRYPTION_KEY` must crash the server at boot; `decrypt()`
  must throw on failure, never return its input. Add `keyVersion` field to every encrypted
  record (SEC-3, SEC-9).
- **Implementation:** `server/src/utils/encryption.js` — remove the `scryptSync` fallback;
  validate key length at module load and `process.exit(1)` with a clear message. Wrap stored
  ciphertexts as `{v: 1, data: …}`; write a one-off migration script for existing `Settings`.
- **Verification:** Boot with no key → process exits non-zero with message. Unit tests:
  round-trip, tampered ciphertext throws, legacy-format record migrates. Existing users' keys
  still decrypt after migration (test against a copied dev DB).

### 1.2 Per-service environment scoping
- **Objective:** Each container sees only its own secrets; client container sees none (SEC-4).
- **Implementation:** Split `.env` into `env/server.env`, `env/engine.env`, `env/client.env`
  (client: only `VITE_*`); update both compose files' `env_file` entries. Delete dead
  `BINANCE_API_KEY`/`BINANCE_SECRET` entries and the `keys/binance_testnet.env` file path
  (SEC-9); document per-user Settings as the only credential source. Adopt SOPS for the env
  files if they are to be committed anywhere.
- **Verification:** `docker compose exec client printenv | grep -iE 'jwt|encryption|google|mongo'`
  returns nothing. Full stack boots; login + backtest + manual order smoke test passes.

### 1.3 Authenticate `/internal/*` + bind internally
- **Objective:** Engine→Node callbacks require a shared secret; routes unreachable from outside
  the compose network (SEC-1, SYS-1).
- **Implementation:** `X-Internal-Key` middleware on `internal.routes.js` (constant-time
  compare); engine's `_notify_node` sends it; key lives only in server+engine env files. Remove
  host port publishing for server in dev where feasible, or at minimum reject non-keyed
  internal calls. Fix the engine's `require_api_key` to constant-time compare while there
  (SEC-8).
- **Verification:** `curl PATCH /internal/algo/sessions/x/stats` without key → 401; engine
  stats still flow during a live session (Socket.IO updates visible). Add a supertest case.

### 1.4 Zod validation at Node boundaries
- **Objective:** No controller reads `req.body` unparsed; `/internal/*` payloads
  whitelist-validated — kills the `positionDetails` `$set` dotted-path injection (SEC-10, SRV-3).
- **Implementation:** Add `zod`; `validate(schema)` middleware; start with the highest-risk
  routes: internal stats, algo session start, trade order placement, settings/keys. Explicit
  field whitelist + numeric coercion for `positionDetails`.
- **Verification:** Malformed bodies → 400 with field errors (supertest); fuzz the internal
  stats route with unexpected keys → they never appear in the Mongo doc.

### 1.5 Rate limiting & auth hardening (small)
- **Objective:** Realistic global limiter + strict auth-route limiter (SEC-5); `verifyJWT`
  distinguishes DB outage (503) from bad token (401) and caches the user lookup briefly (SRV-4).
- **Implementation:** `express-rate-limit`: drop global to ~600/15min per IP (tune), add
  20/15min on `/auth/*`. 30s in-memory user cache keyed by id, invalidated on admin
  grant/revoke (grant latency ≤30s is acceptable; document it).
- **Verification:** Hammer auth route → 429. Stop Mongo → authenticated request returns 503
  not 401. Grant/revoke reflected within cache TTL (integration test).

### 1.6 Test harness + CI gate (Plan 2's scaffolding)
- **Objective:** Make later phases verifiable: server supertest harness, client vitest+msw
  harness (deps already present), GitHub Actions running engine pytest + server + client suites
  (SRV-2, SYS-5).
- **Implementation:** `.github/workflows/ci.yml` — three jobs, fail on red; seed with the tests
  written in 1.1–1.5 and Phase 0's new engine tests. Add golden-master as a manual/dispatch job
  (needs candle fixtures).
- **Verification:** CI red on an intentionally broken PR; green on main.

## Phase 2 — Strategy Ownership & Observability (Plans 3 + 2) · ✅ **SHIPPED 2026-07-15** (2.4 OTel optional, deferred; 2.1 satisfied by outright *removal* of the code-edit path, not admin-gating)

### 2.1 Strategy editing → operator-owned artifacts *(product decision — sign-off required, per Plan 3 §3.2)*
- **Objective:** Close the any-user-RCE path: `PUT /strategies/:id/code` becomes admin-only;
  strategies are git-versioned files (SEC-2, SYS-3).
- **Implementation:** `requireAdmin` on the code-edit route (client hides the editor for
  non-admins, shows read-only source + "clone" affordance if desired). Remove the prod-compose
  named volume over `engine/strategies` so deployed code matches the image. Stamp a strategy
  content hash into every session/backtest record.
- **Verification:** Non-admin PUT → 403; editor hidden in UI for non-admin (RTL test). New
  backtest records carry `strategyHash`. Redeploy → strategies match repo (hash check).

### 2.2 Strategy version pinning at runtime
- **Objective:** Running sessions execute the code they started with — no `importlib.reload`
  skew (SEC-2 tail).
- **Implementation:** Sessions hold their instantiated strategy object for their lifetime
  (already true); reject code edits for strategies with active sessions, or queue reload until
  sessions end. Log hash at session start.
- **Verification:** Edit strategy while session runs → session log shows original hash; new
  session shows new hash.

### 2.3 Correlation IDs + structured logging (OTel step 1)
- **Objective:** Every log line across client→Node→engine carries a request/trace ID (SYS-6);
  prerequisite for verifying Phase 3.
- **Implementation:** Node: `pino` + `pino-http` with W3C `traceparent` passthrough, replace
  `morgan`. Engine: JSON logging config + ASGI middleware reading/creating `traceparent`;
  `engineClient` forwards the header; `_notify_node` includes it. Session/symbol IDs as
  standard log fields in the live manager.
- **Verification:** One manual order → grep a single trace ID through server and engine logs.
  Log lines parse as JSON (jq in CI smoke).

### 2.4 Full OTel traces + metrics (optional within phase, can defer)
- **Objective:** Spans for HTTP hops + Binance calls; counters for reconcile divergence,
  order latency, rate-budget use, WS reconnects.
- **Implementation:** `@opentelemetry/auto-instrumentations-node` + FastAPI OTel
  instrumentation; OTLP exporter to a local collector (compose service) or console in dev.
- **Verification:** A backtest request produces a connected multi-service trace in the viewer.

## Phase 3 — Live-Trading State Integrity (Plan 5 · **gate for any future mainnet**) · 🟡 **PARTIAL — 3.1–3.4 shipped as Plan 5's 5.3/5.2/5.4/5.1-scoped; 3.5 (Decimal) + 5.6 (restart recovery) remain**

> Golden-master before/after each step. Decimal (3.5) intentionally changes outputs —
> re-baseline with sign-off.

### 3.1 Client-order-ID idempotency
- **Objective:** Every entry/exit order carries deterministic `newClientOrderId`
  (`enma_<sessionId>_<seq>`); timeouts resolved by ID query, never guessed (ENG-10).
- **Implementation:** ID generator in the session (monotonic seq persisted in session state);
  attach to all MARKET/LIMIT placements in `live_bot_manager` + kernel entry/exit paths; on
  httpx timeout, `GET /fapi/v1/order?origClientOrderId=` before deciding not-filled.
- **Verification:** Unit: same intent → same ID; timeout-then-query path covered with a mocked
  filled response → no duplicate order placed (test double for Binance).

### 3.2 Typed order state machine + user-stream-driven fills (Hummingbot `InFlightOrder` pattern)
- **Objective:** Order state transitions driven by `ORDER_TRADE_UPDATE` events keyed by client
  order ID; real `avgPrice`/fees recorded — no more trigger-price or candle-close estimates
  (ENG-2b/c).
- **Implementation:** `engine/core/orders.py`: `InFlightOrder` dataclass
  (NEW→SUBMITTED→PARTIALLY_FILLED→FILLED/CANCELED/EXPIRED/FAILED) + `OrderTracker` per session.
  `user_data_stream.py` routes events to the tracker; tracker emits typed callbacks the manager
  consumes. `trade_recorder` reads fill data from the tracker. Where the stream is silent
  (conditional-order gap noted in CURRENT_STATE.md), fall back to `GET /fapi/v1/userTrades` for
  the exact fill — closing the documented debt item.
- **Verification:** Testnet session: place + SL-close a position; recorded exit price equals
  exchange `avgPrice` (compare against `GET /fapi/v1/userTrades`). State-machine unit tests for
  every legal/illegal transition.

### 3.3 Per-symbol locking + honest exit accounting
- **Objective:** Kill the fill-callback vs candle-loop race (ENG-3); `execute_exit` never
  records a close the exchange didn't confirm (ENG-2a).
- **Implementation:** `asyncio.Lock` per (session, symbol) around reconcile + position
  mutation. `execute_exit`: on close-order failure → position stays open locally, alert
  emitted, retry policy; only tracker-confirmed closes credit PnL.
- **Verification:** Race test: simulate concurrent fill-event + candle-close on one symbol
  (asyncio test with fake streams) → exactly one trade record. Forced close-order failure →
  position remains open + alert, no PnL credit.

### 3.4 Append-only trade-event log
- **Objective:** One ordered source of truth for live state; Node/Mongo becomes a projection —
  no more last-write-wins PATCH ordering (SYS-2, ENG-16).
- **Implementation:** Engine appends every order/position/PnL transition to a Mongo
  `tradeEvents` collection (monotonic per-session seq). `_notify_node` sends seq-stamped
  events through one pooled httpx client with retry; Node's internal handler rejects
  out-of-order seq (or Node subscribes via Redis stream — decide in-plan; Redis already
  present). Session PnL recomputed as a fold over events.
- **Verification:** Replay test: fold events → equals session PnL displayed. Kill engine
  mid-session, restart → state reconstructed from log + exchange query, no orphan positions.

### 3.5 Decimal ledger path
- **Objective:** `Decimal` for prices/quantities/fees/PnL accumulation; floats only in numpy
  indicator space (ENG-11).
- **Implementation:** Convert at the exchange boundary (Binance returns strings — parse
  straight to Decimal); quantize with `tickSize`/`stepSize` from exchange filters; kernel and
  models' money arithmetic converted; entry-fee tracking added while touching PnL (closes the
  known-debt item).
- **Verification:** Golden-master diff reviewed + re-baselined. Property test: ledger sums
  associative regardless of order. `test_risk_math.py` extended for Decimal.

## Phase 3b — Live Fill-Path Correctness & Risk Governor (Plans 21 + 22 · added 2026-07-16 · **the current P0 track**)

Grew out of the 2026-07-16 industry-standard audit (`21_live-algo-industry-standard-audit.md`)
and the risk-management consolidation (`22_risk-management-industry-standard.md`). Sits between
Phase 3's shipped steps and 3.5/5.6: it fixes the fill-detection machinery Phase 3's remaining
work will build on, then layers session-scoped risk enforcement over the corrected state.

- **3b.1 (=21.1)** Three surgical fill-path fixes — userTrades credentials (A-1), `_on_fill`
  crash (A-2), LISTEN_KEY_EXPIRED stream-kill (A-3). Prerequisite for any further F7 diagnosis.
- **3b.2 (=21.2)** ACCOUNT_UPDATE-driven reconcile — closes the ~60s staleness window
  event-type-agnostically.
- **3b.3 (=21.3)** Cancel resting SL/TP conditionals on every close path (stale
  `closePosition:true` triggers are a live wrong-money hazard).
- **3b.4 (=21.4)** Emergency-exit truth + naked-position detector/re-arm.
- **3b.5 (=22.1–22.3)** Session Risk Governor hard checks: aggregate drawdown kill-switch,
  daily loss limit, true cross-symbol open-risk budget, margin ceiling, liq-buffer wiring,
  protections parity. (21.6 merged into 22.1.)
- **3b.6 (=22.4–22.7)** Enforced VaR/CVaR + correlation caps + inverse-vol allocation
  (config-gated, golden-master-inert at defaults) + platform surface.
- **Deferred within 3b:** 21.5 (rate-limit/weight hygiene — pairs naturally with Phase 4.2's
  budget work), 21.7 (P3 notes/decisions).

**Gate to exit:** a conditional SL/TP fill reflects in session state in seconds, not ~60s; no
open algo orders survive any close path; a governor breach demonstrably auto-sets
`trading_state` and blocks entries; Zone 1 VaR number and enforced VaR number come from the
same function.

## Phase 4 — Exchange Abstraction & Transport Efficiency (Plan 6 · effort M · risk medium)

### 4.1 `Exchange` interface
- **Objective:** One interface (native httpx impl behind it); testnet/mainnet + venue name
  injected at construction — zero mode literals at call sites (ENG-4/5).
- **Implementation:** `engine/exchange/` package: `Exchange` protocol (orders, positions,
  klines, streams, filters), `BinanceFutures(mode=…)` impl absorbing `binance_testnet.py`.
  Manager/kernel/adapters take an `Exchange` instance. Fix the warmup-data split: warmup and
  execution use the same venue's data (or the mainnet-data choice becomes an explicit,
  documented constructor arg).
- **Verification:** `grep -rn '"testnet"' engine/` → config/construction sites only.
  Golden-master byte-equivalence (pure refactor). Boundary suite green.

### 4.2 Combined WS streams + global signed-call budget
- **Objective:** One market-stream socket per session via `/stream/` multiplexing (not one per
  symbol); every signed REST call passes one weight-aware limiter (ENG-9).
- **Implementation:** Combined-stream client with resubscribe-on-reconnect; extend
  `OrderRateLimiter` into a global weight budget (reads `X-MBX-USED-WEIGHT-1M` response
  headers) wrapping all signed calls — exits get priority lanes rather than bypass;
  reconciliation batched (`GET /fapi/v2/account` once per boundary instead of per-symbol).
- **Verification:** 20-symbol chaos session on testnet: socket count ≤ 2–3 (`ss` in container);
  used-weight header stays under budget at candle boundaries; no 429s in a 1-hour soak.

### 4.3 Candle-stream gap integrity (QNT-10)
- **Objective:** A WS reconnect never leaves a hole in the candle series; indicators never
  compute across an undetected discontinuity.
- **Implementation:** On (re)connect, REST-backfill klines since the last stored candle before
  processing stream events; timestamp-continuity assertion in the candle buffer
  (`ts[i+1] − ts[i] == timeframe` or backfill+log). Natural fit inside 4.2's combined-stream
  client.
- **Verification:** Kill the WS mid-session (testnet), reconnect after ≥2 closed candles →
  series is continuous, a gap-backfill log line exists, strategy saw every candle exactly once.

### 4.4 `LiveBotManager` decomposition (behaviour-preserving)
- **Objective:** Split the 2,002-line god class along the seams Phase 3 created:
  `SessionManager`, `SymbolWorker`, `Reconciler`, `WarmupService`, `NodeNotifier` (ENG-1,
  ENG-5/6/7 partially).
- **Implementation:** Extract in that order, one PR each, golden-master + soak test between.
  Session dict → typed dataclass while extracting (ENG-7). Introduce a typed `Signal` object
  kernel↔strategy to replace attribute pokes (ENG-6) as the final step.
- **Verification:** Golden-master after each extraction; `wc -l` ceiling per module (~500);
  race test from 3.3 stays green.

## Phase 5 — Server & Client Structure (Plan 7 · effort M–L · risk low)

### 5.1 Node service layer + jobs-not-timeouts
- **Objective:** Controllers thin; business logic in testable services; long engine calls
  become BullMQ jobs + progress events instead of 1-hour HTTP hangs (SRV-1/5).
- **Implementation:** Extract `algoSession.service.js` (dedupe session/chaos credential
  assembly), `trade.service.js`; `engineClient` timeout → 30s except candle-import, which
  becomes a queued job emitting Socket.IO progress.
- **Verification:** Supertest suite green with services mocked; candle import of a fresh symbol
  shows progress events and survives a server restart (job resumes/requeues).

### 5.2 Client decomposition + single realtime owner
- **Objective:** Break up `Trade.jsx` (1,760 ln / 29 useState) into container + feature panels;
  one market-data store as the sole owner of "current price" (CLI-1/2/3).
- **Implementation:** Extract panels (OrderForm, Positions, OrderBook, Chart, Histories) with
  co-located state; Zustand `marketStore` fed by the Binance WS lib — components subscribe to
  the store, never the socket directly; shared query factory for the 15 hooks' fetch/toast
  conventions.
- **Verification:** RTL tests per panel with msw; one price source asserted (no component
  imports `binanceWS` directly — lint rule); manual trade smoke on testnet.

## Phase 6 — Data-Layer & Correctness Cleanup (Plans 6/8 · effort M · risk low)

### 6.1 TimescaleDB continuous aggregates + compression
- **Objective:** HTF candles (5m/1h/4h/1d) derived in-DB via hierarchical continuous
  aggregates; compression on chunks older than ~7 days.
- **Implementation:** Migration SQL in `docker/timescale/`; engine reads HTF from the caggs
  instead of separate REST fetches; refresh policies per level.
- **Verification:** Cagg 1h candles byte-match Binance 1h klines for a sample month; disk
  usage before/after compression recorded; backtest golden-master unchanged (same data path
  contract).

### 6.2 Warmup math + candle-column safety + packaging
- **Objective:** Warmup requirement computed from declared indicator lookbacks (not
  largest-numeric-param×3), history cap ≥ requirement (ENG-8, QNT-9/16); named candle-column
  accessors replace positional indexing (ENG-15); proper package layout kills the
  `/engine → /app` symlink + dual-import dance (ENG-12). Include the small quant perf fixes
  while here (QNT-15: incremental ATR-history sort, O(N) trail-stop ATR).
- **Implementation:** Strategies declare `warmup_candles` (validated ≥ max indicator lookback);
  `Candle` named-tuple/enum for column access with a single remap point per fetcher;
  `pyproject.toml` + absolute `engine.*` imports, remove `sys.path` hacks.
- **Verification:** Param > 166 no longer bricks readiness (regression test); backtest with
  insufficient candles fails loudly instead of completing with 0 trades; grep shows zero
  positional `candle[N]` indexing outside the accessor; container boots without symlink;
  golden-master green.

### 6.3 Docs truth-telling (Plan 8)
- **Objective:** Governance docs match shipped architecture — fix the "server only proxies" /
  internal-orders contradiction (SYS-4); update DECISIONS.md with the choices made in Phases
  0–5 (event log, Decimal, Exchange interface, strategy ownership, quant fixes).
- **Implementation:** `/sync-spec` pass over `docs/core/` + affected feature SPECs; retire dead
  env vars from `.env.example`.
- **Verification:** `drift-reviewer` subagent audit reports zero drift across its 6 vectors.

## Phase 7 — Quant Methodology Upgrades (Plan 9 · steps 9.4/9.5/9.7/9.8/9.10 · effort M · risk low-medium)

> Every step here **changes backtest outputs by design** → golden-master re-baseline with
> sign-off per step (Rule C). Full detail: [`9_backtest-and-optimizer-correctness.md`](9_backtest-and-optimizer-correctness.md).

- **7.1 (=9.5)** Lookahead sentinel in CI — expanding-window vs full-array `prepare()` diff for
  all seeded strategies (QNT-12; doubles as the live-parity detector for QNT-9). Only needs
  Phase 1.6's CI; can land early. **Shipped 2026-07-15**
  (`engine/scripts/lookahead_sentinel.py`, wired into CI). Supersedes Plan 16's proposed
  per-trade lookahead diff (`16_lookahead-analysis.md`, now `Merged→9`) — reopen 16 only if this
  sentinel ever flags a strategy and the failure needs per-indicator-column localization.
- **7.2 (=9.4)** Entry-candle exit evaluation (QNT-3) — opt-in, then default after re-baseline.
- **7.3 (=9.7)** Historical funding-rate ledger in TimescaleDB; boundary-priced signed funding
  (QNT-5). Pairs with 6.1's Timescale work.
- **7.4 (=9.8)** Detail-timeframe intrabar simulation (ENG-18, QNT-3 residual) — opt-in 1m
  sub-candle exit loop.
- **7.5 (=9.10 + 9.9 stats)** Fill-model ladder (spread → vol-scaled → √-impact), liquidation
  fee, fail-loud metric registry, no `"inf"` strings, leg-vs-round-trip statistics (QNT-4/11/
  13/14).

**Gate to exit:** each landed step has a signed-off re-baseline; lookahead sentinel green in CI.

## Phase 8 — Strategy Lab (Plan 10 · effort M–L · risk low · **product surface**)

Job-based Monte Carlo robustness simulator + optimizer UI. Full phases, API contracts, UI spec:
[`10_monte-carlo-strategy-lab.md`](10_monte-carlo-strategy-lab.md). Absorbs Plan 9 steps
9.6/9.9(MC).

- **8.1 (=Plan 10 Phase 1)** Vectorized block-bootstrap MC engine + `labResults` +
  `simulationQueue` job plumbing; retire the synchronous `GET …/simulation` path.
- **8.2 (=Phase 2)** Strategy Lab page, MC tab (fan chart, DD exceedance, ruin card); retire
  `SimulationResults.jsx`.
- **8.3 (=Phase 3)** Optimizer exposure (Node proxy for the currently-unreachable `/optimize`),
  walk-forward + DSR/PBO + Optuna, Optimizer tab. Build from, don't duplicate:
  `18_walk-forward-analysis.md` and `19_bayesian-hyperopt.md` are `Merged->10` stubs (folded
  2026-07-15) — their fold-split math and Optuna search-space adapter design are the detail
  source for this step; do NOT build their standalone synchronous `/optimize/walk-forward`
  endpoint or separate `walkForwardResults` collection, which conflict with this phase's
  job-based `labResults` architecture.
- **8.4 (=Phase 4)** MC-scored selection, drawdown-constrained `risk_pct`, MC-banded leverage,
  Backtest-page MC summary strip.

**Gate to exit:** Plan 10's per-phase acceptance criteria; old endpoints retired (410).

## Phase 9 — Freqtrade/Nautilus Feature Gaps (Plans 11-15, 17 · independent track) · 🟡 **MOSTLY SHIPPED — 9.1 (=11) verified, 9.2 (=12), 9.4 (=14), 9.5 (=15) shipped; remaining: 9.3 (=13), 9.6 (=17)**

Ported from `workspace/next_phase/` on 2026-07-15 (`mergeContext.md`); reconciled against
plans 1-10 and shipped work the same day. Additive engine/server features, no trust/state or
quant-simulation-core overlap — can run any time, gated only by its own V0 (9.1/=11). Plans 16,
18, 19 are NOT separate steps here — they are `Merged->9`/`Merged->10` stubs, folded into
Phase 7.1 and Phase 8.3 respectively (see those sections).

- **9.1 (=11)** V0 verification — confirm Dashboard/Risk-Dashboard/Monte-Carlo are actually
  wired end-to-end (an old deleted `INDEX.md` called them "missing"; audit found them built).
  Gate for the rest of this phase, not a build item.
- **9.2 (=12)** Max position per asset. **Scope already narrowed 2026-07-15**: sub-item 1a
  (per-asset notional cap) confirmed already shipped via `max_qty()`/`max_exposure_notional`
  (`engine/core/strategy.py:353`) — only 1b (session-level `max_open_positions` count gate in
  `live_bot_manager.py`) remains to build.
- **9.3 (=13)** Informative/multi-timeframe contract — `self.htf(timeframe)` helper, as-of
  aligned + lookahead-safe by construction. Run Phase 7.1's lookahead sentinel against any
  strategy that adopts it (no new tooling needed — 7.1 already generalizes to any strategy).
- **9.4 (=14)** Webhook notifications — independent, server-only, no golden master.
- **9.5 (=15)** Data conversion CLI — independent, engine-only, stdlib, no golden master.
- **9.6 (=17)** Recursive-formula (warmup-insufficiency) analysis — sequence after 9.3 so it
  also sweeps multi-TF indicators. Real, unaddressed gap; most likely tool to catch an actual
  live/backtest divergence given the live path's rolling 500-candle replay window.

**Gate to exit:** 9.1's checklist green; 9.2's 1b count-gate test green; 9.3's alignment test +
Phase 7.1 sentinel green for any strategy using `htf()`; 9.6 run against all 5 seeded strategies
with a recorded min-warmup recommendation per strategy.

---

## Sequencing & gates

| Phase | Depends on | Gate to exit |
|-------|-----------|--------------|
| 0 | — (immediate, parallel) — **✅ shipped** | Multi-symbol bracket + exec-algo close/flip + config-persistence tests green |
| 1 | — | CI green incl. new security tests; stack boots with scoped env |
| 2 | 1 (CI) | Non-admin RCE path closed; one trace ID spans a request end-to-end |
| 3 | 1, 2.3 — **🟡 partial (3.5, 5.6 remain)** | Soak: 24h testnet session, recorded PnL == exchange-derived PnL; replay test green |
| 3b | 3.1–3.4 shipped — **🔴 current P0** | Phase 3b gate above (fill-path seconds-not-minutes; no surviving brackets; governor auto-trip) |
| 4 | 3 **and 3b.3/3b.4** | Golden-master equivalence; 1h soak, zero 429s; gap-backfill test green |
| 5 | 1 (harness); parallel with 4 | Supertest + RTL suites green in CI |
| 6 | 4 (6.1); anytime (6.2/6.3) | drift-reviewer zero-drift report |
| 7 | 0; 1.6 (CI) — parallel with 2–6 | Signed-off re-baselines; lookahead sentinel green |
| 8 | 0 (9.1/9.3); 1.6 recommended — parallel with 3–6 | Plan 10 acceptance; legacy sim endpoint retired |
| 9 | — (independent) — parallel with everything | 9.1 checklist; 9.2 count-gate test; 9.3 alignment + sentinel; 9.6 per-strategy warmup report |

**Mainnet remains gated on Phase 3 AND Phase 3b shipped** — Plan 21 proved the live fill path
misses conditional fills and Plan 22's governor doesn't exist yet; neither state is
mainnet-acceptable. **Backtest-trust gate (Phase 0) is satisfied** — shipped 2026-07-15.

*This file sequences plans 1–22; it does not replace them. Update `0_tracker.md` when a phase
starts or ships.*
