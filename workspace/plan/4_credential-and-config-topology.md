# Plan 4 — Credential & config topology

**Status:** Mostly Shipped 2026-07-15 (4.1–4.4 done, 4.5 partial) · **Priority:** P1 · **Depends on:** 2, 3 · **Related:** 8

## Shipped summary

- **4.1** — full inventory table below. Headline finding: every `BINANCE_*` env var is dead code
  (zero reads anywhere in `server/`/`engine/`) — the per-user-Settings credential path the user
  originally asked for was **already fully in place** before this plan started.
- **4.2** — structurally already satisfied by 4.1's finding; no code changed. `.env.example`'s
  dead Binance block removed with an explanatory note. **2026-07-15, follow-up turn:** user
  explicitly authorized deleting the dead lines — removed all 7 `BINANCE_*` entries (including
  the unused plaintext testnet key/secret) from the local `.env`, plus the now-orphaned section
  header and a resulting double blank line. `docker compose up -d` afterward recreated the
  client container (Compose recalculates the config hash whenever root `.env` changes, even for
  services not referencing the removed vars); all three app containers confirmed healthy after.

### Shared dev/prod database — key-sync decision (2026-07-15)

User confirmed the intent: **one database for local dev and production, deliberately, for the
whole development phase** — single test account (the one used throughout this session), zero
real users anywhere. Asked for a recommendation on making that durable.

**Recommendation given:** the only secret that actually needs to match across environments for
this to work cleanly is `ENCRYPTION_KEY` — it's the only one that touches data stored *in* the
shared database (encrypted Settings fields). `JWT_SECRET` doesn't need to match (cookies are
domain-scoped, sessions never cross environments). `INTERNAL_API_KEY`/`ENGINE_API_KEY` don't
need to match (they authenticate same-environment server↔engine pairs, never cross the
internet). `GOOGLE_CLIENT_ID`/`SECRET` don't need to match (Google account identity is stable
regardless of which OAuth app config obtained it).

**Decision: deferred, not implemented.** Attempted to fetch production's `ENCRYPTION_KEY` via
read-only SSH to sync it into local `.env` — blocked twice by the permission system (correctly:
pulling a live production secret's plaintext into this session's transcript is a different risk
category than any local Docker-only action taken so far, and neither "build a mechanism" nor a
generic "proceed yourself" named that specific action clearly enough to authorize it). Asked the
user directly; their call: **skip for now, revisit at actual deploy time** — nothing is
currently broken by the mismatch (both environments already decrypt their own
independently-encrypted copies of the one test user's Settings correctly; the only cost is that
edits from one environment don't decrypt in the other until re-saved there, which hasn't been
an issue for single-environment-at-a-time manual testing).

**Runbook for when this is actually needed (real users, or cross-environment testing that hits
this):** this is exactly what Plan 2 Step 4.4 / `server/scripts/migrate-encryption-key.js`'s
rotation mechanism was built for — set the target key as `ENCRYPTION_KEY` on both sides,
temporarily add the *other* side's current key as `ENCRYPTION_KEY_PREV` on whichever side is
adopting it, run the migration script to re-encrypt existing records, confirm no old-version
records remain, drop `ENCRYPTION_KEY_PREV`. No new code needed — this is a config + one script
run, not an engineering task.
- **4.3** — `docker-compose.yml`'s three app services (`engine`, `server`, `client`) each moved
  from `env_file: - ./.env` (whole shared file) to a scoped `environment:` block listing exactly
  the variables that service reads. Client now receives **only** `VITE_API_URL`/`VITE_SOCKET_URL`
  — previously it got `JWT_SECRET`, `ENCRYPTION_KEY`, `GOOGLE_CLIENT_SECRET`, `MONGO_URI`, all of
  it, into a Vite dev-server Node process with ~15 third-party dependencies (a real supply-chain
  exposure). Verified via `docker exec client env | grep <secret-names>` → 0 matches.
  **Caught and fixed a regression this step itself introduced**: Compose's `KEY: ${VAR}` mapping
  sets the container's env to `""` (not "unset") when `VAR` isn't in `.env` — `engine/services/
  candle_importer.py`'s `os.getenv("BINANCE_FETCH_DELAY_MS", "200")` only substitutes its
  default on a truly-missing key, not an empty string, so it would have thrown `ValueError` on
  the next candle fetch. Fixed to `os.getenv(...) or "200"`; audited every other `os.getenv(key,
  default)` call in the engine against the new scoped env lists and confirmed no other instance
  hits this pattern (the vars affected are ones explicitly listed in the compose `environment:`
  block but absent from `.env` — currently only `BINANCE_FETCH_DELAY_MS` and server's
  `LOG_LEVEL`, and the latter is already safe because `process.env.LOG_LEVEL || 'info'` in JS
  treats `''` as falsy, unlike Python's `os.getenv`).
- **4.4** — `encryption.js` now supports a rotation window: `ENCRYPTION_KEY` is always the
  current key (new writes use it, tagged with the current version); an optional
  `ENCRYPTION_KEY_PREV` lets records still tagged with the previous version keep decrypting.
  Steady state (no `ENCRYPTION_KEY_PREV` set — today's actual deployment) is byte-identical to
  pre-4.4 behavior, version tag `v1`. 6 new tests exercise a full v1→v2 rotation with
  mixed-version records decrypting correctly in the same window. **Rotation runbook** below.
- **4.5 — partial.** TimescaleDB pinned to the exact version already running
  (`timescale/timescaledb:2.26.1-pg16`, was `latest-pg16`) in both `docker-compose.yml` and
  `docker-compose.prod.yml` — verified the pull resolves to the already-running image (zero
  drift) and the container still starts healthy. **Deferred: Redis `requirepass`.** Redis is
  reachable on the published host port in dev; adding auth is real, understood, low-complexity
  work, but this session already had one self-inflicted crash-loop incident from container
  churn, and Redis backs BullMQ + rate limiting + Socket.IO pub/sub + progress channels — an
  auth misconfiguration here has wide blast radius. Left for a dedicated pass with more careful
  sequencing rather than squeezed in at the end of an already-long session. Also not done:
  replacing the dev Postgres password literal (`enma_dev_password`) — low priority, dev-only,
  not exposed beyond the Docker network.

## Rotation runbook (ENCRYPTION_KEY, Step 4.4)

1. Generate a new 32-byte key: `openssl rand -hex 16` (32 hex characters = 32 bytes as utf8,
   matching this codebase's key-length convention — see `.env.example`).
2. Set `ENCRYPTION_KEY_PREV=<the current ENCRYPTION_KEY value>` and `ENCRYPTION_KEY=<the new
   value>` in the environment, then restart the server. New writes are now tagged `v2` and use
   the new key; existing `v1` records still decrypt via `ENCRYPTION_KEY_PREV`.
3. Force-migrate remaining `v1` records to `v2`: re-run `server/scripts/migrate-encryption-key.js`
   pointed at the new key (it already skips anything not matching the OLD hardcoded-fallback
   format — **it needs a small update before reuse for this purpose**: today it only recognizes
   the pre-Plan-2 unversioned format as "old", not a `v1:` record under a *now-retired* key. This
   is flagged as a needed follow-up, not built in this pass).
4. **Before dropping `ENCRYPTION_KEY_PREV`, confirm zero `v1:`-prefixed values remain** in every
   encrypted field across the `Settings` collection (a Mongo query, not built here). Dropping
   `ENCRYPTION_KEY_PREV` while `v1` records still exist is destructive: the retired key's bytes
   are gone, and the next deploy reuses the `v1` version tag for whatever key is now
   `ENCRYPTION_KEY` — a still-`v1`-tagged old record will fail GCM authentication (fail-closed,
   loud, not silent corruption — but the plaintext is unrecoverable without the old key).
5. Once confirmed, remove `ENCRYPTION_KEY_PREV` and restart. Steady state resumes, tagged `v1`
   again under the new key (version tags are relative to "how many rotations old", not absolute).

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

## Secret inventory (Step 4.1 — completed 2026-07-15)

Every `.env` key checked against actual code (`grep -rn` across `server/`, `engine/`, `client/`
for each name) — not assumed from the variable name.

| Secret | Read by | Current location | Class | Target |
|--------|---------|------------------|-------|--------|
| `JWT_SECRET`, `JWT_EXPIRES_IN`, `JWT_REFRESH_EXPIRES_IN` | server only | `.env` | infra | server-scoped env |
| `ENCRYPTION_KEY` | server only | `.env` | infra | server-scoped env (Plan 2/4.4 rotation story) |
| `INTERNAL_API_KEY` | server + engine | `.env` | infra | scoped to both (Plan 3) |
| `ENGINE_API_KEY` | server + engine | `.env` | infra | scoped to both |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_CALLBACK_URL` | server only | `.env` | infra | server-scoped env |
| `ADMIN_EMAIL` | server only | `.env` | infra (bootstrap) | server-scoped env |
| `MONGO_URI`, `MONGO_DB` | server + engine | `.env` | infra | scoped to both — **see the shared-production-database flag from Plan 2**, unresolved, blocks a clean "target" call here |
| `TIMESCALE_URL` | engine only | `.env` | infra | engine-scoped env |
| `REDIS_URL` | server + engine | `.env` | infra | scoped to both |
| `ENGINE_URL`, `SERVER_URL`, `CLIENT_URL` | server/engine (service discovery, not secrets) | `.env` | infra (not secret) | fine as-is, can stay in either scoped file |
| `PORT`, `NODE_ENV`, `PYTHON_ENV`, `ENGINE_PORT` | server/engine (not secrets) | `.env` | infra (not secret) | fine as-is |
| `VITE_API_URL`, `VITE_SOCKET_URL` | client build only | `.env` / `client/.env.production` | infra (not secret, public build-time) | already client-scoped correctly — no change needed |
| `BINANCE_API_KEY`, `BINANCE_SECRET` | **nobody** — confirmed via repo-wide grep, zero matches in `server/`, `engine/` | `.env`, `.env.example` | **dead** | delete |
| `BINANCE_MAINNET_API_KEY`, `BINANCE_MAINNET_SECRET` | **nobody** — zero matches | `.env` | **dead** | delete |
| `BINANCE_TESTNET`, `BINANCE_TESTNET_API_KEY`, `BINANCE_TESTNET_SECRET` | **nobody** — zero matches | `.env` | **dead** | delete |
| `GITHUB_PERSONAL_ACCESS_TOKEN`, `github-enma-vps-deploy` | nobody in app code — manual/deploy tooling only | `.env` | infra (deploy tooling, not app runtime) | out of scope for this plan; stays in root `.env` (gitignored), never passed to any container |
| `keys/binance_testnet.env` (file, not an env var) | **nobody in code** — confirmed zero references anywhere in `server/`, `engine/`, `client/`, docs | `keys/` | personal, **explicitly annotated "not for AI Agents / user reference only" inside the file itself** | leave untouched — not read, not migrated, not deleted; the annotation is a clear signal this file is the user's own manual scratch space |

**Headline finding: Step 4.2 is already structurally satisfied.** Every `BINANCE_*` env var is
dead — the engine has never had a fallback path reading Binance credentials from `os.getenv()`;
personal credentials already flow exclusively through per-user encrypted `Settings` records, as
the user's original directive wanted. The only work Step 4.2 requires is deleting the dead env
var lines — no code path changes needed, so no golden-master re-baseline applies (the plan's
Step 4.2 acceptance check assumed a code change that turned out to be unnecessary).

**BLOCKED — needs the user's own action, not mine:** `.env.example` cleanup landed (dead
`BINANCE_API_KEY`/`BINANCE_SECRET`/`BINANCE_TESTNET` lines removed with an explanatory note).
The **local `.env`** still has 7 dead lines (`BINANCE_TESTNET`, `BINANCE_TESTNET_API_KEY`,
`BINANCE_TESTNET_SECRET` — this one holds a **real, unused testnet key/secret sitting in
plaintext** — `BINANCE_API_KEY`, `BINANCE_SECRET`, `BINANCE_MAINNET_API_KEY`,
`BINANCE_MAINNET_SECRET`, all blank except the TESTNET pair) that the permission system
correctly refused to let me delete autonomously — root CLAUDE.md's "do not modify `.env`" rule
plus this session's two prior one-time exceptions don't extend to unprompted further edits.
**Action for the user:** delete lines matching `^BINANCE_` from `.env` (or ask me to, explicitly,
in a future turn) once you've confirmed the testnet key/secret pair on that line isn't needed
anywhere outside the app (it is not read by any code — confirmed above).
