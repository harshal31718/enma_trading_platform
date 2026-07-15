# Plan 2 — Safety net & guardrails

**Status:** Shipped 2026-07-15 · **Priority:** P0 (do first) · **Depends on:** — · **Related:** 3, 4, 5

## Shipped summary

All six steps landed in one session. Key deviations from plan-as-written, and why:

- **2.1** — Jest (not Vitest, see Open Questions) + Supertest + `mongodb-memory-server` +
  `ioredis-mock` installed, but the first tests (`encryption.test.js`, `chaosAllocator.test.js`,
  `risk.test.js`, `auth.middleware.test.js` — 39 tests) turned out to need none of the DB/Redis
  mocks (all four targets are pure functions or fully mockable at the module boundary) — they're
  still installed for the next session's controller/route-level tests. Coverage wired via Jest's
  built-in `collectCoverage`.
- **2.2** — the harness (Vitest/RTL/MSW deps + `vite.config.js` `test` block) already existed
  from an earlier session but was never wired — `src/tests/setup.js` didn't exist, so `npm test`
  would have failed immediately. Created it + one smoke test per page (11 pages) in
  `pages.smoke.test.jsx`, with jsdom stubs for `ResizeObserver`/`matchMedia`/canvas (lightweight-
  charts needs `HTMLCanvasElement.getContext` on unmount).
  **KNOWN GAP:** `msw` is a devDependency but is not actually wired up (no request handlers). All
  API calls in these smoke tests fail as real network errors against jsdom, which is caught by
  each page's existing error-state handling. Fine for a mount-only smoke test; a future session
  should add MSW handlers before writing tests that assert on fetched data.
- **2.3 — required an unplanned mid-session detour.** `ENCRYPTION_KEY` was unset in `.env`
  entirely (not just invalid) — shipping fail-closed as originally scoped would have crashed the
  server on next boot. Discovered mid-fix: this dev environment's `MONGO_URI` points at the
  **same shared production Atlas cluster** as the deployed VPS (see `DEPLOYMENT.md`), and the
  logged-in user's real Settings document is encrypted under **production's** `ENCRYPTION_KEY`,
  which is not available locally. Resolution (user-directed): generated a local-only
  `ENCRYPTION_KEY`, ran a one-off migration (`server/scripts/migrate-encryption-key.js` — decrypts
  under the old hardcoded fallback key, re-encrypts under the new key in a versioned `v1:` envelope,
  idempotent, leaves any field it can't decrypt untouched) against the live Settings collection,
  and left the one production-encrypted document alone. User will re-save their Binance keys on
  this local stack. **Flagged, not fixed:** local dev sharing production's database is a latent
  risk this session surfaced but did not resolve — worth a deliberate decision (point local dev
  at its own Mongo, or formalize the shared-cluster setup) before Plan 4 (credential topology).
- **2.4** — implemented as designed: `AsyncLocalStorage`-based `requestContext.js` (no signature
  changes needed anywhere), `pino-http` replacing `morgan('dev')`, redaction list, engine-side
  `contextvars` + a logging filter on the root handler, `X-Request-Id` echoed both directions.
  **Scoping decision:** engine → Node propagation (`_notify_node`/`_call_node_internal` inside
  `live_bot_manager.py`) was explicitly left out — those are engine-initiated background-loop
  calls with no inbound request to correlate against, a different tracing problem than the
  plan's synchronous "one Trade request, one id" acceptance criterion, and touching that
  2,000-line file here would have pre-empted Plan 6's decomposition. Verified: header round-trips
  both directions (curl), and the correlation-id log filter mechanism proven directly (not found
  via uvicorn's own access log, which uses its own logger config outside `logging.basicConfig`'s
  reach — a real but cosmetic gap, business log lines from application code do carry it correctly).
- **2.5** — server's `/api/v1/health` was *already* honest (checks Mongo+Redis live, returns 503
  if either is down) — no ENG-13 equivalent existed there. Only the engine's `/health` was the
  hardcoded-`"ok"` lie; fixed to live-ping Mongo + TimescaleDB on every call.
- **2.6** — CI needed a docker-compose override (`docker-compose.ci.yml`) adding a local
  throwaway `mongodb` service + `.env.ci` (no real secrets) — the real `.env` must never be used
  in CI given the shared-production-database discovery above. Golden master runs in CI as an
  **execution smoke check only** (`continue-on-error: true`), not a byte-level regression gate —
  no baseline is committed to the repo yet, and Binance REST reachability from the runner isn't
  guaranteed. Rule C's actual before/after byte-compare stays a local, per-session discipline
  until a committed-baseline policy is designed. **Unverified end-to-end:** validated via
  `docker compose config` (merges cleanly) but not run against a live swapped `.env` locally
  (would have required touching the live dev stack's real `.env`) — first real run is the next
  push to GitHub.

**Files:** `server/src/utils/encryption.js`, `server/scripts/migrate-encryption-key.js` (new),
`server/src/utils/__tests__/{encryption,chaosAllocator,risk}.test.js` (new),
`server/src/middleware/__tests__/auth.middleware.test.js` (new), `server/src/config/{logger,
requestContext}.js` (new), `server/src/middleware/requestId.js` (new), `server/src/app.js`,
`server/src/services/engineClient.js`, `server/src/middleware/errorHandler.js`,
`server/package.json`, `client/src/tests/setup.js` (new),
`client/src/tests/pages.smoke.test.jsx` (new), `engine/main.py`, `.env` (added
`ENCRYPTION_KEY`, local-only), `.env.ci` (new), `docker-compose.ci.yml` (new),
`.github/workflows/ci.yml` (new).

> Source issues (see `audit_1_system-design.md`): SRV-2, SEC-3, SYS-5, SYS-6, ENG-13.
> This plan changes **no product behaviour**. It builds the scaffolding every later plan
> relies on to prove it didn't break anything. Land it before touching auth, credentials,
> or the trade state machine.

## Why this is first

Plans 3–8 modify authentication, credential handling, and the live-money state machine.
There are currently **zero** server and client tests, encryption is fail-open, and there is
no correlation logging to reconstruct an incident. Changing high-risk code with none of that
in place is how a two-bug repo becomes a ten-bug repo. This plan installs the net.

## Goal

A maintainer on any later plan can (a) run a test suite that covers the code they touch,
(b) trust that the encryption primitive fails *closed*, (c) trace one request across
client → Node → engine → Binance by a shared id, and (d) get a red CI signal on regressions.

## Scope / what changes

### Step 2.1 — Server test harness (issue SRV-2)
- Add a test runner to `server/` (Jest or Vitest — pick one, record the choice in
  `server/CLAUDE.md`). Wire `npm test` and a `test:watch` script.
- Add `mongodb-memory-server` (or a disposable Mongo container) and an ioredis mock so tests
  need no live infra.
- Write the **first** tests against the highest-risk, lowest-churn units so they act as a
  spec the later plans must keep green:
  - `utils/encryption.js` round-trip + failure modes (see Step 2.3).
  - `middleware/auth.middleware.js` — `verifyJWT`, `requireAdmin`, `requireAlgoAccess` happy
    and unhappy paths.
  - `utils/chaosAllocator.js` and `utils/risk.js` (pure functions — cheap, high value).
- Acceptance check: `npm test` runs offline and passes; coverage report emitted.

### Step 2.2 — Client test harness (issue SRV-2/CLI)
- Add Vitest + React Testing Library to `client/`. Wire `npm test`.
- Seed with one render test per top-level page so later refactors (Plan 7) have a smoke net.
  Do **not** attempt full coverage here — just prove the harness runs and a component mounts.
- Acceptance check: `npm test` passes in `client/`.

### Step 2.3 — Encryption primitive: fail closed (issue SEC-3)
- `server/src/utils/encryption.js` must **throw on boot** if `ENCRYPTION_KEY` is absent or not
  a valid 32-byte key — never silently fall back to the hardcoded `dev-secret-key-salt`.
- `decrypt()` must **throw** (or return a typed failure) on malformed input or auth-tag
  mismatch instead of returning the ciphertext/input unchanged. Callers that today rely on the
  pass-through must be found (`grep -rn "decrypt(" server/src`) and made to handle failure.
- Add a versioned envelope to stored secrets (a `keyVersion`/`v1:` prefix on the encrypted
  string) so Plan 3 can rotate `ENCRYPTION_KEY` without silently corrupting every record.
- Tests (Step 2.1) cover: valid round-trip, wrong key, truncated ciphertext, tampered tag,
  missing env → boot failure.
- Golden-master: not applicable (Node). Acceptance check: the new tests pass and boot with a
  missing key fails loudly.

> ⚠️ This step changes a security primitive's failure semantics. Coordinate with Plan 3,
> which migrates more secrets through it. Do not merge Step 2.3 and start Plan 3 in the same
> session — let the fail-closed behaviour bake first.

### Step 2.4 — Correlation IDs + structured logging (issue SYS-6)
- Server: add a request-id middleware (accept inbound `X-Request-Id`, generate if absent,
  attach to `req`, echo in the response header). Replace `morgan('dev')` with a structured
  logger (pino) that includes the request id and **never** logs cookies, `Authorization`,
  `X-Binance-*`, or decrypted secrets (add a redaction list).
- Engine: replace `logging.basicConfig` bare setup with a structured formatter that carries a
  `correlation_id`. Propagate the id on every engine↔Node hop (`_notify_node`,
  `_call_node_internal`, `engineClient`) via the `X-Request-Id` header.
- Acceptance check: a single Trade request shows the same id in server and engine logs.

### Step 2.5 — Loud health & no silent startup (issue ENG-13)
- Engine `/health` must report degraded/unhealthy when Mongo or Timescale ping failed at
  startup, instead of always `{"status":"ok"}` while dependencies are down. (Full state-machine
  hardening of the 124 broad excepts is Plan 5 — here, only the health lie is fixed.)
- Acceptance check: with Timescale stopped, `/health` returns non-200 and the Docker
  healthcheck goes unhealthy.

### Step 2.6 — CI quality gate (issue SYS-5)
- Add a CI pipeline (`.github/workflows/ci.yml` or the repo's chosen CI) that runs, on every
  push/PR: server tests, client tests, engine `pytest`, and the engine golden-master
  (`engine/scripts/golden_master.py`). Fail the build on any failure.
- Record the pipeline as the enforcement mechanism for `CLAUDE.md` Rule C (golden-master) so it
  stops being convention-only.
- Acceptance check: CI runs green on a trivial branch and red when a test is deliberately broken.

## Out of scope
- Any change to auth flow, route protection, or credential storage location (Plans 3–4).
- Refactoring the god classes or the state machine (Plans 5–6).
- Broad exception cleanup beyond the `/health` lie (Plan 5).

## Acceptance criteria (phase)
- `npm test` (server), `npm test` (client), and `pytest` (engine) all run offline and pass.
- CI is green on the branch and demonstrably red on a planted failure.
- Encryption fails closed (missing key → boot error; bad ciphertext → error, not pass-through)
  with tests proving it.
- One request id threads client → Node → engine in logs; no secret appears in any log line.
- Golden-master byte-identical (no pipeline code touched).

## Open questions
- Jest vs Vitest for the server (pick one, document it). Pino vs the team's preferred logger.
- CI provider — confirm `.github/` is the target (no CI config exists in the repo today).

## Handoff note template (fill on stop)
`Next session: [steps done 2.x], [next step], [files changed], [open questions]`
