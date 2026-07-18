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

### Step 8.2 — Application-layer request validation (issue SEC-10)
- Add a schema-validation layer (zod/joi/celebrate) to the Node API. Controllers stop
  destructuring raw `req.body`. Special attention to any handler writing user-influenced field
  paths into Mongo `$set` (the `positionDetails.${symbol}` pattern) — validate/whitelist keys.
- Acceptance check: malformed bodies are rejected at the edge with 400; injection-shaped keys
  are refused.

### Step 8.3 — Warmup/readiness math (issue ENG-8)
- Fix `_get_min_candles_required` vs `WARMUP_CANDLES` vs the 500-candle `_append_candle` cap so
  readiness is always reachable: reconcile the "×3" code with the "2x" docstring, stop
  conflating unrelated numeric params (an RSI threshold of 70 shouldn't demand 210 candles —
  drive warmup off declared lookback windows, not "largest numeric param"), and ensure the cap
  ≥ the requirement.
- Golden-master before/after (touches indicator warmup). Acceptance check: a strategy with a
  large lookback becomes ready deterministically; no permanent-warmup state.

### Step 8.4 — Candle column-order safety (issue ENG-15)
- Replace positional `candle[1..5]` indexing and the per-fetcher OHLC remap with named
  constants/accessors (or a typed candle struct) so the nonstandard
  `[ts, open, close, high, low, volume]` layout can't be silently mis-mapped.
- Golden-master before/after. Acceptance check: column access is by name; a remap mistake is a
  test failure.

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

### Step 8.7 — Remaining small hardening (issue SEC-8)
- Finish any constant-time-compare / health-endpoint items not already covered by Plans 2/3
  (e.g. the `/health` Redis new-connection-per-request churn).
- Acceptance check: health check reuses a connection; no timing-unsafe secret compares remain.

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
