# Plan 4 — Credential & config topology

**Status:** Ready · **Priority:** P1 · **Depends on:** 2, 3 · **Related:** 8

> Source issues: SEC-4, SEC-9, SEC-7, and the SYS-4 config-drift portion. Directly implements
> the user directive: **remove personal tokens/API keys/accesses from `.env` files and move
> them into each user's Settings.** Depends on Plan 2 (fail-closed, versioned encryption) and
> Plan 3 (authenticated secret retrieval) so secrets have a safe home and a safe path.

## Why now

Per-user encrypted credentials already exist in `Settings` and the session flows pass them
explicitly — the foundation is there. What remains is (a) eliminating the env/file-level
personal credentials that shouldn't exist, (b) stopping the shared `.env` from being injected
into every container, and (c) giving `ENGINE_API_KEY`/`ENCRYPTION_KEY` a rotation story. This
must come after Plan 2/3 or you are moving secrets into a still-fail-open vault down a still-
unauthenticated path.

## Goal

No personal Binance credential exists anywhere except a per-user, versioned-encrypted record in
Mongo. No container receives a secret it doesn't need. Infra secrets (`ENGINE_API_KEY`,
`ENCRYPTION_KEY`, internal key) are rotatable without silent data loss.

## Scope / what changes

### Step 4.1 — Inventory & classify every secret (issue SEC-9)
- Produce a short table (put it at the bottom of this file when done) of every secret in
  `.env`, `.env.example`, `client/.env.production`, and `keys/`: name, who needs it, current
  location, target location. Classify each as **infra** (stays in env/secret-manager, scoped)
  or **personal** (moves to per-user Settings) or **dead** (delete).
- Known entries to resolve: `BINANCE_API_KEY` / `BINANCE_SECRET` in `.env.example`
  (dead-or-fallback — clarify and remove the ambiguity), `keys/binance_testnet.env`,
  `ADMIN_EMAIL` bootstrap, `ENGINE_API_KEY`, `ENCRYPTION_KEY`, `JWT_SECRET`,
  `GOOGLE_CLIENT_SECRET`.
- Acceptance check: table complete; every secret has a target.

### Step 4.2 — Move personal credentials to per-user Settings (user directive)
- Confirm the engine reads Binance credentials **only** from the per-session payload sourced
  from the user's `Settings` record — never from `os.getenv("BINANCE_*")`. Remove any engine
  code path that falls back to env Binance keys (`grep -rn "BINANCE_API_KEY\|BINANCE_SECRET"
  engine`).
- Remove `BINANCE_API_KEY` / `BINANCE_SECRET` from `.env`, `.env.example`, and delete
  `keys/binance_testnet.env` from use (migrate any real testnet key a developer needs into
  their own Settings via the UI).
- Ensure the Settings UI/flow covers both testnet and mainnet key pairs (the model already has
  `encryptedMainnetApiKey` fields).
- Golden-master: run before/after — this touches the live/backtest credential injection path
  (CLAUDE.md Rule C). Acceptance check: a session started with no env Binance keys but valid
  per-user Settings keys still trades on testnet.

### Step 4.3 — Stop injecting the shared `.env` into every container (issue SEC-4)
- Split env by service. The client build container must receive **only** public `VITE_*` build
  vars — never `JWT_SECRET`, `ENCRYPTION_KEY`, `GOOGLE_CLIENT_SECRET`, or DB URIs.
- Give server and engine their own scoped env files / compose `environment:` blocks with only
  the variables each actually reads (derive from the Step 4.1 table).
- Acceptance check: `docker compose config` shows the client env free of any secret; each
  service sees only its own.

### Step 4.4 — Rotatable infra secrets (issue SEC-9)
- `ENCRYPTION_KEY`: rely on the versioned envelope from Plan 2.3 so a new key can be introduced
  as `v2` while `v1` records still decrypt; document the rotation runbook.
- `ENGINE_API_KEY` and the internal key (Plan 3.1): document rotation (both sides read from
  scoped env; rotate by deploying both with the new value). Note there is no live-rotation
  without brief downtime unless a two-key overlap window is added — capture that as a follow-up.
- Acceptance check: rotation runbook exists; a `v1→v2` encryption-key rotation is exercised in
  a test with mixed-version records.

### Step 4.5 — Harden infra image/credential hygiene (issue SEC-7)
- Pin `timescale/timescaledb` to an exact version (drop `latest-pg16`) in dev and prod compose.
- Add Redis auth (`requirepass`) in both compose files; update all Redis URLs.
- Replace the dev Postgres password literal; confirm dev-only port publishing is intended and
  documented.
- Acceptance check: stack boots with pinned images and authenticated Redis; no `latest` tags.

## Out of scope
- Auth/route protection (Plan 3, done).
- Application-layer request validation (Plan 8, SEC-10).

## Acceptance criteria (phase)
- No personal Binance credential resolvable from any env/file — only per-user Settings.
- Client container env contains zero secrets; server/engine each see only their own.
- Encryption-key rotation works across mixed-version records (tested).
- Images pinned, Redis authenticated.
- Golden-master identical or explained; CI green.

## Open questions
- Adopt a real secret manager (Docker/host secrets, Vault, cloud KMS) now, or keep scoped env
  files for this pass? Recommend scoped env files now, secret-manager as a follow-up plan.
- Does any developer workflow depend on `keys/binance_testnet.env`? Confirm before deleting.

## Secret inventory (fill in Step 4.1)
| Secret | Read by | Current location | Class | Target |
|--------|---------|------------------|-------|--------|
| | | | | |
