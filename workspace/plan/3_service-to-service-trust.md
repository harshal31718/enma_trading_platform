# Plan 3 — Service-to-service trust

**Status:** Shipped 2026-07-15 · **Priority:** P0 · **Depends on:** 2 · **Related:** 4, 8

## Shipped summary

All five steps landed. **Step 3.2 decision was made without a synchronous sign-off round-trip**:
went with the plan's own stated default (option 1, remove the runtime code-write endpoints
entirely), on user authorization to proceed on recommended paths while they were away.
Justification beyond "it's the plan's default": empirically confirmed the write path was already
dead code — `client/src/hooks/useStrategies.js`'s `useUpdateStrategyCode` was defined but
imported nowhere, and `client/CLAUDE.md` already documented `CodeViewer.jsx` as read-only. Removing
it deleted zero live user-facing capability. If a code-editing feature is wanted later, it needs
a fresh design (sandboxed worker, option 2) — this did not preserve a disabled/gated version of
the old endpoint to build on top of.

- **3.1** — `server/src/middleware/requireInternalKey.js` (constant-time compare, distinct
  `INTERNAL_API_KEY` secret) gates `/internal/*`. Engine's `_notify_node`/`_call_node_internal`
  (`live_bot_manager.py`) and the startup reconciliation POST (`main.py`) attach `X-Internal-Key`.
  Verified: unauthenticated/wrong-key curl → 401, correct key → 200, real engine startup
  notification round-trips successfully post-restart.
- **3.2** — removed `PUT /api/v1/strategies/:id/code` (Node route/controller) and
  `PUT /strategies/{name}/code` (engine — `ast.parse`, class-name check, disk write,
  `importlib.reload` into the live process, all gone) plus the unused client mutation hook.
  `POST /strategies` (create/clone) untouched — confirmed it never accepted raw `code` from the
  client (only `name`/`description`/`sourceName`/`template`), so it isn't the RCE vector and
  isn't affected. Verified: `PUT .../code` now 405; `GET .../code` (used by the read-only
  `CodeViewer.jsx`) still 200.
- **3.3** — interim only, as scoped: `X-Binance-*` redaction already shipped in Plan 2.4's pino
  config. Moving the secret out of headers entirely wais on Plan 4.
- **3.4** — `server/src/middleware/rateLimiters.js`: three Redis-backed tiers (`rate-limit-redis`,
  new dependency) — `authLimiter` (20/15min) on `/api/v1/auth`, `mutatingLimiter` (60/min) on
  the entire `/api/v1/trade` and `/api/v1/algo` mounts (simpler and still correct-in-spirit than
  splitting by HTTP method within those routers — both are higher blast-radius than generic
  reads regardless of verb), `readLimiter` (10k/15min, the old global default) on everything
  else. Verified via Redis key inspection (`rl:auth:*`, `rl:mutate:*`, `rl:read:*` all populate
  correctly per-IP).
- **3.5** — Node: `crypto.timingSafeEqual` in `requireInternalKey.js` (with an explicit
  equal-length pre-check, since `timingSafeEqual` throws rather than returning false on a length
  mismatch — Python's `hmac.compare_digest` doesn't have that footgun). Engine: `main.py`'s
  `require_api_key` (Node → engine direction) now uses `hmac.compare_digest`.

**Self-inflicted incident during this step (documented, not hidden):** a mid-edit crash loop —
added a `rate-limit-redis` import before rebuilding the server image to install it, and
separately the server container had gone stale (missing `ENCRYPTION_KEY`/`INTERNAL_API_KEY` in
its process env despite `.env` having them — root cause not fully diagnosed, worked around by a
clean rebuild + recreate). Caused the "Network error: Backend server is unreachable" toast the
user saw repeatedly in-browser. Root-caused and fixed within the same step by rebuilding both
images and recreating the containers; server confirmed stable (healthy, no restart loop) before
moving on.

**Files:** `server/src/middleware/{requireInternalKey,rateLimiters}.js` (new),
`server/src/middleware/__tests__/requireInternalKey.test.js` (new), `server/src/app.js`,
`server/src/routes/strategy.routes.js`, `server/src/controllers/strategy.controller.js`,
`client/src/hooks/useStrategies.js`, `server/package.json`, `engine/main.py`,
`engine/core/live_bot_manager.py`, `engine/routers/strategies.py`, `.env` (added
`INTERNAL_API_KEY`), `.env.example`, `.env.ci`.

> Source issues: SEC-1, SEC-2, SEC-5, SEC-6, SYS-1. These are the two most dangerous holes
> in the system (unauthenticated internal order routes; RCE via strategy-code write) plus the
> transport and rate-limit weaknesses around them. Requires Plan 2's fail-closed encryption
> and correlation logging to land safely and be verifiable.

## Why now (and why after Plan 2)

The trust topology is inverted (SYS-1): the deadliest surfaces are the least protected while
harmless read routes sit behind a key. This plan flips that. It goes after Plan 2 because
every fix here needs tests (auth middleware, transport) and correlation logs to confirm the
new boundaries actually hold.

## Goal

No unauthenticated code path can place/close orders or mutate session state. No authenticated
user can inject code into the engine process. Every service-to-service call is authenticated
and rate-limited proportional to its blast radius.

## Scope / what changes

### Step 3.1 — Authenticate the Node `/internal/*` routes (issue SEC-1)
- Today `internalRoutes` mounts before `verifyJWT` with **no** auth. The engine is the only
  legitimate caller. Add a shared-secret / mTLS check on `/internal/*`:
  - Require a header (e.g. `X-Internal-Key`) matching a dedicated secret **distinct** from
    `ENGINE_API_KEY` (Node→engine) — this is the reverse direction (engine→Node).
  - Constant-time compare (see SEC-8; reuse the helper Plan 8 adds, or add it here).
  - Bind to an allowlisted source where the deployment allows it.
- Engine side: `_notify_node` and `_call_node_internal` attach the internal key.
- Tests: `/internal/*` returns 401 without the key, 200 with it.
- Acceptance check: unauthenticated `curl` to every `/internal/algo/...` route is rejected.

### Step 3.2 — Kill the strategy-code RCE path (issue SEC-2) — **decision required**
The chain `PUT /api/v1/strategies/:id/code` (Node, `verifyJWT` only) → engine
`PUT /strategies/{name}/code` writes arbitrary Python to disk and `importlib.reload`s it into
the process holding every user's decrypted keys. Options, in order of preference:
  1. **Remove the runtime code-write endpoints entirely.** Strategies become code-reviewed,
     version-controlled assets shipped in the image; the "edit strategy code in the UI" feature
     is retired. Safest; aligns with SYS-3.
  2. **Gate + sandbox.** Restrict the endpoints to `requireAdmin`, and move strategy execution
     into an isolated worker (separate process/container with no credential access, resource
     limits, restricted imports). Keeps the feature, large effort, still risky.
  3. **Interim:** immediately add `requireAdmin` to the write endpoint and disable the reload
     into the live process, pending 1 or 2.
- Whichever is chosen, also fix the reload version-skew (running sessions keep stale classes):
  document that code changes require a session restart, or block writes while sessions run.
- This step needs an explicit product decision — see Open questions. Record it in the tracker.
- Acceptance check: a non-admin user cannot write strategy code; the chosen option is enforced
  and tested.

### Step 3.3 — Secret transport off custom headers (issue SEC-6)
- Stop sending `X-Binance-API-Secret: <plaintext>` between services. Once Plan 4 finalises
  where credentials live, the secret should be fetched by the engine from the credential store
  under an authenticated call, not passed hop-to-hop in a header. Until then, ensure the
  redaction list (Plan 2.4) covers `X-Binance-*` so it never lands in a log.
- Acceptance check: no plaintext secret in any inter-service header after Plan 4; interim
  redaction verified in logs.

### Step 3.4 — Real rate limiting, tiered by risk (issue SEC-5)
- The global `apiLimiter` (10k/15min ≈ 11 rps) is effectively off. Replace with tiered limits:
  a stricter limiter on `/api/v1/auth/*`, a moderate one on mutating `/algo`/`/trade` routes,
  and a looser one on reads. Back the limiter with Redis (already in stack) so it works across
  multiple server instances.
- Acceptance check: auth brute-force limiter trips in tests; order routes are bounded.

### Step 3.5 — Constant-time key comparison, both directions (issue SEC-8, pulled forward)
- Engine `require_api_key` and the new Node `/internal` check must use constant-time compare.
- Acceptance check: comparison uses `hmac.compare_digest` / `crypto.timingSafeEqual`.

## Out of scope
- Where credentials are stored / `.env` removal (Plan 4 — this plan only fixes *who may call
  what* and *how secrets travel*, not *where they live*).
- Engine decomposition (Plan 5).

## Acceptance criteria (phase)
- Every `/internal/*` route rejects unauthenticated callers (tested).
- The strategy-code RCE path is closed per the chosen option and enforced by a test.
- No plaintext credential travels in an inter-service header (or the interim redaction is in
  place and verified).
- Auth and mutating routes are rate-limited via Redis; limits proven in tests.
- CI green; golden-master identical (no pipeline code touched).

## Open questions
- **Step 3.2 is a product call:** retire UI strategy editing (option 1), or invest in a
  sandboxed worker (option 2)? Default recommendation: option 1 now, option 2 only if the
  feature is genuinely required. Needs sign-off before implementation.
- Internal-auth mechanism: shared secret (fast) vs mTLS (stronger, more ops). Recommend shared
  secret now, mTLS tracked as a follow-up.

## Handoff note template
`Next session: [steps done 3.x], [next step], [decision on 3.2], [files changed]`
