# Plan 3 — Service-to-service trust

**Status:** Ready · **Priority:** P0 · **Depends on:** 2 · **Related:** 4, 8

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
