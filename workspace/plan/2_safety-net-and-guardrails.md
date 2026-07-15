# Plan 2 — Safety net & guardrails

**Status:** Ready · **Priority:** P0 (do first) · **Depends on:** — · **Related:** 3, 4, 5

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
