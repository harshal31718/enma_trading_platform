# Enma — Server (Node.js) Rules

> Inherits all rules from root `CLAUDE.md`.
> Read root CLAUDE.md first, then this file.

---

## Stack (server-specific)

- Node.js 20 LTS
- Express 4
- Socket.IO 4 (server)
- BullMQ 5 + ioredis
- Mongoose 7
- passport + passport-google-oauth20 (Google OAuth 2.0, sessionless)
- jsonwebtoken (JWT signing/verification)
- cookie-parser (reads the `enma_jwt` httpOnly cookie)
- express-validator (installed but not used as standalone middleware — dead dependency, superseded by zod, see below)
- zod (Plan 8 Step 8.2, SEC-10) — schema-validation layer via `middleware/validate.js`'s `validate(schema, source='body')`, applied per-route on the previously-zero-validation routes (`POST /strategies`). Most controllers already had adequate hand-rolled inline validation (`settings.controller.js`, `risk.controller.js`, `admin.controller.js`, `lab.controller.js` via `utils/labConfig.js`) — those were deliberately left as-is rather than force-migrated to zod for stylistic consistency; see `0_tracker.md`'s Plan 8 notes for the full per-controller scoping.
- express-rate-limit (inline in `app.js`)
- Helmet.js
- pino + pino-http for structured logging (replaces `morgan('dev')`, Plan 2 Step 2.4 — DECISIONS
  needed: request-id middleware attaches a correlation id to every log line, redacts cookies/
  `Authorization`/`X-Binance-*`/decrypted secrets)
- dotenv
- axios (HTTP calls to Python engine via `services/engineClient.js`)
- uuid (v4 job ID generation)
- **Test stack (Plan 2 Step 2.1):** Jest (not Vitest — this is a CommonJS `require()` codebase;
  Jest needs zero ESM config for that, Vitest would need `vite-node`/extra config for no
  benefit here) + Supertest (route-level tests) + `mongodb-memory-server` (disposable Mongo,
  no live infra needed) + `ioredis-mock` (mock Redis). `npm test` runs `jest --runInBand`
  (serial — `mongodb-memory-server` instances are heavier under parallel workers).

---

## Folder structure

```
server/
└── src/
    ├── config/
    │   ├── redis.js        ← ioredis client singleton (shared by BullMQ + pub/sub)
    │   ├── socket.js       ← Socket.IO server setup
    │   ├── passport.js     ← Google OAuth 2.0 strategy (sessionless)
    │   ├── logger.js       ← pino instance, redacts cookies/Authorization/X-Binance-* (Plan 2 2.4)
    │   └── requestContext.js ← AsyncLocalStorage carrying the current request's correlation id
    │                            across async calls (controllers → services → engineClient)
    ├── constants/
    │   └── top_symbols.js  ← ~80 tiered symbols (high/mid/low) — Chaos Mode pool
    ├── middleware/
    │   ├── errorHandler.js          ← global error handler, logs via config/logger.js with req.id
    │   ├── auth.middleware.js       ← verifyJWT / requireAdmin / requireAlgoAccess (gates all /api/v1/* routes)
    │   ├── requestId.js             ← reads/generates X-Request-Id, echoes on response, seeds requestContext
    │   ├── requireBinanceCredentials.js ← validates X-Binance headers on trade routes
    │   └── validate.js              ← Plan 8 Step 8.2 (SEC-10): generic zod schema-validation middleware, `validate(schema, source='body')` — throws ApiError(400, 'VALIDATION_ERROR', …) on failure, replaces req[source] with the parsed data on success
    ├── validators/          ← Plan 8 Step 8.2 — per-route zod schemas, one file per controller domain that needed one (only routes with zero prior inline validation got a schema here — see server/CLAUDE.md's Stack section)
    │   └── strategy.validators.js ← createStrategySchema (POST /strategies)
    ├── models/             ← Mongoose models
    │   ├── Strategy.js        ← metadata: name, description, filePath (global, no userId)
    │   ├── User.js             ← googleId, email, name, avatar, role, isActive, algoAccess {status,requestedAt,decidedAt,decidedBy}
    │   ├── BacktestResult.js  ← server fields: jobId, status, error, tradeCount
    │   │                         engine fields (Mixed, never written by server): metrics, equityCurve
    │   ├── BacktestTrade.js   ← split collection backtestTrades (jobId, tradeIndex, …)
    │   ├── BacktestLeverageScenario.js ← Risk Dashboard Zone 3 leverage-sensitivity runs (engine-owned)
    │   ├── LabResult.js        ← Strategy Lab job results (labId, type: "monte_carlo"|"optimization"|"pbo", sourceJobId?, config, configHash, status, results[engine-owned]) — shared by Phase 1 (MC), Phase 3a (walk-forward), and PBO
    │   ├── LiveSession.js
    │   ├── TradeOrder.js
    │   ├── TradeExecution.js
    │   ├── TradeTransaction.js
    │   ├── TradeRecord.js     ← completed round-trip trades (engine writes, server reads; collection: tradeRecords)
    │   └── Settings.js        ← AES-encrypted Binance keys + exchange settings (userId-keyed)
    ├── routes/             ← Express routers (thin — logic in controllers)
    │   ├── auth.routes.js       ← /auth/google, /auth/google/callback, /auth/logout, /auth/me (unprotected)
    │   ├── admin.routes.js      ← /admin/users, /admin/users/:id/algo-access (requireAdmin)
    │   ├── strategy.routes.js   ← /strategies, /strategies/:id/code
    │   ├── candle.routes.js     ← /candles/symbols, /candles/cached
    │   ├── backtest.routes.js
    │   ├── dashboard.routes.js  ← /dashboard/stats, /dashboard/performance-calendar
    │   ├── trade.routes.js      ← /trade/* (settings/keys [testnet+mainnet env], balances [testnet+mainnet, read-only mainnet], account, positions, orders, klines, order status)
    │   ├── risk.routes.js         ← /risk/* (settings, live metrics, simulation, overrides)
    │   ├── lab.routes.js          ← /lab/simulations [POST, GET list, GET :simId] (Plan 10 Phase 1, MC), /lab/optimizations [POST, GET list, GET :labId], /lab/objectives [GET] (Plan 10 Phase 3a, walk-forward), /lab/pbo [POST, GET list, GET :labId] (Plan 10 PBO)
    │   ├── algo.routes.js         ← /algo/sessions [requireAlgoAccess], /algo/chaos [requireAlgoAccess], /algo/access-request, /algo/symbols/locked, /algo/pairlist/preview, /algo/sessions/:id/trading-state
    │   ├── settings.routes.js     ← /settings/exchange
    │   ├── orderHistory.routes.js ← /order-history (GET, paginated, filterable)
    │   └── internal.routes.js     ← /internal/algo/sessions/:id/* (engine callbacks, unprotected — uses LiveSession-derived context)
    ├── controllers/
    │   ├── auth.controller.js       ← Google OAuth callback, issues JWT cookie, /auth/me, logout
    │   ├── admin.controller.js      ← user management: listUsers + setUserAlgoAccess (grant/revoke)
    │   ├── strategy.controller.js   ← MongoDB queries + code proxy to engine
    │   ├── candle.controller.js     ← getSymbols, getCachedCandles
    │   ├── backtest.controller.js
    │   ├── dashboard.controller.js  ← proxies engine /dashboard/stats, /dashboard/performance-calendar
    │   ├── trade.controller.js
    │   ├── risk.controller.js         ← proxies engine /risk/* (settings, live metrics cache, simulation, overrides)
    │   ├── lab.controller.js          ← runMonteCarlo (enqueues Plan 10 Phase 1 job, configHash cache short-circuit), getSimulation, listSimulations, runOptimization (Phase 3a, resolves strategyId→filePath), getOptimization, listOptimizations, listObjectives, runPBO (same strategyId→filePath resolution, standalone full-range run), getPBO, listPBO
    │   ├── algo.controller.js         ← session CRUD + startChaos + trading-state kill-switch + engine callbacks (handleEngineStats, handleAlgoPlaceOrder, …)
    │   ├── settings.controller.js     ← getExchangeSettings, updateExchangeSettings
    │   └── orderHistory.controller.js ← getOrderHistory (reads tradeRecords; engine is sole writer)
    ├── services/
    │   ├── engineClient.js  ← axios instance for engine HTTP calls
    │   ├── backtestQueue.js ← BullMQ queue definition for bull:backtest
    │   ├── simulationQueue.js ← BullMQ queue definition for bull:simulation (Plan 10 Phase 1)
    │   ├── optimizationQueue.js ← BullMQ queue definition for bull:optimization (Plan 10 Phase 3a)
    │   ├── pboQueue.js ← BullMQ queue definition for bull:pbo (Plan 10 PBO)
    │   ├── socketEmitter.js ← Redis pub/sub → Socket.IO relay
    │   ├── symbolService.js ← fetches tiered symbol list from engine (5-min TTL cache)
    │   ├── symbolLock.js    ← Redis-backed symbol lock (bot vs manual)
    │   ├── eventStreamConsumer.js ← Plan 6 Step 6.5 (ENG-16): consumer-group reader for the engine's `algo:events` Redis Stream (`core/node_notifier.py`'s `NodeNotifier.notify()`) — ordered, at-least-once, replaces the old fire-and-forget HTTP PATCH. Applies each entry via `algoSessionService.processEngineStatsUpdate()` (same function the old `PATCH /internal/algo/sessions/:id/stats` route used) then XACKs; consumer name is `os.hostname()`-keyed (stable across this dev environment's frequent nodemon restarts) and `claimStalePending()` uses `XAUTOCLAIM` on startup to reclaim any dead consumer's unacked backlog, not just its own
    │   └── reconciliation.js ← startup reconciliation (server.js), aligns local state with exchange/engine truth
    ├── workers/
    │   ├── backtest.worker.js
    │   ├── simulation.worker.js ← Plan 10 Phase 1 — mirrors backtest.worker.js, POSTs engine /simulate/monte-carlo
    │   ├── optimization.worker.js ← Plan 10 Phase 3a — mirrors simulation.worker.js, POSTs engine /simulate/optimize
    │   └── pbo.worker.js ← Plan 10 PBO — mirrors optimization.worker.js, POSTs engine /simulate/pbo
    ├── utils/
    │   ├── ApiError.js        ← Custom error class
    │   ├── ApiResponse.js     ← Standard response helpers
    │   ├── chaosAllocator.js  ← Chaos Mode symbol allocation (manual pick guarantee + round-robin tier partition)
    │   ├── encryption.js      ← AES-256 for API key storage
    │   ├── risk.js            ← resolveRiskParams() — per-run risk override merge
    │   ├── labConfig.js       ← buildMonteCarloConfig() (Phase 1) / buildWalkForwardConfig() (Phase 3a) / computeConfigHash(), pure + unit-tested
    │   ├── symbolFormat.js    ← Plan 8 Step 8.2 (SEC-10): SYMBOL_REGEX / isValidSymbolFormat() — whitelists the real Binance symbol shape before a user/engine-callback-supplied symbol is used as a Mongo dot-path segment (`positionDetails.${symbol}`) or Redis lock key
    │   └── healthCheck.js     ← Plan 8 Step 8.7 (SEC-8): checkMongoHealth()/checkRedisHealth() — extracted from `app.js`'s `/api/v1/health` handler so its connection-reuse behavior is unit-testable without requiring the whole app (which transitively opens its own real Redis connections via `socketEmitter.js`/BullMQ queue definitions)
    ├── app.js               ← Express app setup (no server.listen here)
    └── server.js            ← Entry point (server.listen + startup reconciliation)
```

---

## Route rules

- All routes prefixed `/api/v1/`
- Routes are thin — they validate input and call a controller
- Controllers are thin — they call a service and return the response
- Services contain the actual logic
- Never write database queries in routes or controllers — models only

## Response format (always use ApiResponse helpers)

```js
// Success
res.status(200).json(ApiResponse.success(data))

// Created
res.status(201).json(ApiResponse.created(data))

// Error (caught by global error handler)
throw new ApiError(404, 'NOT_FOUND', 'Strategy not found')
```

---

## How to call the Python engine

Always use `services/engineClient.js` — never raw axios/fetch in controllers.

```js
// engineClient.js exposes:
engineClient.post('/backtest/run', payload)
engineClient.post('/live/start', payload)
// etc.
```

The engine client handles: base URL from env, API key header, timeout, error wrapping.

---

## BullMQ rules

- One queue file per job type in `services/`, one worker per job type in `workers/`
- Workers publish progress to Redis pub/sub — never directly to Socket.IO
- `socketEmitter.js` subscribes to Redis pub/sub and relays to Socket.IO rooms
- Job IDs are UUIDs (generated before queue submission in the controller)
- **Four active queues:** `bull:backtest`, `bull:simulation` (Plan 10 Phase 1), `bull:optimization` (Plan 10 Phase 3a), `bull:pbo` (Plan 10 PBO) — no candle queue, no live queue
- Worker only updates `status` and `error` in `backtestResults` — never writes `metrics`, `equityCurve`, or trade records; engine is the sole writer for result data


### Backtest job flow

```
POST /api/v1/backtest
  → backtest.controller.js generates jobId (UUID), creates BacktestResult doc (status: queued)
  → enqueues job on bull:backtest queue via backtestQueue.js
  → returns 202 { jobId, status: "queued" }

backtest.worker.js picks up job:
  → calls subscribeToJob(jobId, 'backtest') — subscribes to Redis progress:{jobId}
  → updates BacktestResult status to 'running'
  → calls POST {ENGINE_URL}/backtest/run with full payload
  → engine auto-fetches candles if needed (via ensure_candles_available())
  → engine publishes progress events to Redis channel progress:{jobId}
  → socketEmitter.js relays progress events to Socket.IO room backtest:{jobId}
  → on engine response 200: updates BacktestResult status to 'completed' only
  → emits backtest:complete to Socket.IO room backtest:{jobId}
  → calls unsubscribeFromJob(jobId) — cleanup Redis subscription
  → on engine error: updates BacktestResult status to 'failed', emits backtest:error
  → calls unsubscribeFromJob(jobId) on error path as well
```

### socketEmitter rules

- Always call `unsubscribeFromJob(jobId)` after `backtest:complete` or `backtest:error` events
- `unsubscribeFromJob` must: call `subscriber.unsubscribe(channel)`, delete the entry from `jobTypes` Map
- Separate Redis connection required for pub/sub — cannot share the BullMQ connection
- `subscribeToJob(jobId, type)` is called by the worker before calling the engine, not after

---

## Mongoose rules

- Always define schema with `timestamps: true`
- Always add indexes for fields used in queries
- Never use `find()` without a limit
- Sensitive fields (API keys) must use the `encrypt.js` util before saving
- Schema changes need a migration plan — flag it, don't just change the schema
- Use `mongoose.Schema.Types.Mixed` for fields owned by another service (e.g., `metrics`, `trades`, `equityCurve` in `BacktestResult` are engine-owned). `Mixed` signals "this service stores but never writes or validates this field" and avoids false defaults like `[]` that imply server ownership.

---

## Data ownership

The server owns the routing, auth, and job queue layers. Database ownership is split:

| Database | Owned by | server/ access |
|---|---|---|
| MongoDB — `strategies` | server | Read + write via Mongoose |
| MongoDB — `backtestResults` | engine | Read-only for status/error fields only; engine writes all result data |
| MongoDB — `backtestTrades` | engine | Read-only; engine bulk-writes all trades |
| MongoDB — `liveSessions` | engine | Read-only (same pattern) |
| MongoDB — `tradeRecords` | engine | Read-only via `TradeRecord.js` model — engine is sole writer |
| MongoDB — `backtestLeverageScenarios` | engine | Read-only via `BacktestLeverageScenario.js` model — engine is sole writer (Risk Dashboard Zone 3) |
| MongoDB — `labResults` | split | Server creates the `queued` doc + updates `status`/`error` only (same pattern as `backtestResults`); engine is sole writer of `results` (Plan 10 Phase 1) |
| MongoDB — `users` | server | Read + write via `User.js` (Passport creates/updates on login; admin reads all users + writes `algoAccess`). Admin reads are a deliberate no-`userId`-scope exception. |
| TimescaleDB — `candles` | engine | **Never** — server never queries TimescaleDB |
| Redis — BullMQ queues | server | Write (enqueue jobs) |
| Redis — progress pub/sub | engine writes, server reads | Subscribe and relay to Socket.IO |
| Redis — cancel flags | server writes, engine reads | Write only (`backtest:cancel:{jobId}`) |
| Redis — symbol locks | server writes/reads | Via `symbolLock.js` (bot vs manual lock) |
| Redis — live bot cache | engine writes, server reads | Read-only |
| Redis — `algo:events` stream | engine writes (`XADD`), server reads (consumer group) | Plan 6 Step 6.5 — ordered/at-least-once session stats/event delivery, see `eventStreamConsumer.js` |

**Policies:**
- server/ never connects to TimescaleDB — all candle data comes through engine HTTP endpoints
- server/ never writes `metrics`, `trades`, or `equityCurve` to `backtestResults` or individual trades to `backtestTrades` — engine is the sole writer for result data; server only updates the `status` and `error` fields
- `metrics`, `trades`, and `equityCurve` are defined as `mongoose.Schema.Types.Mixed` in `BacktestResult.js` to make engine ownership explicit; do not add typed Array or Object schema definitions for these fields
- `CandleImport` model, `candle.worker.js`, `candleQueue.js`, `liveQueue.js`, `live.worker.js` — none exist; do not create them
- Strategy code lives on engine disk — server never reads strategy files directly; always proxy via `GET engine:8000/strategies/:name/code`
- Strategy metadata (name, description, filePath) lives in MongoDB `strategies` collection, owned by server
- **`userId` is required** on all mutable Mongoose models (`BacktestResult`, `BacktestTrade`, `BacktestLeverageScenario`, `LabResult`, `LiveSession`, `Settings`, `TradeOrder`, `TradeExecution`, `TradeTransaction`, `TradeRecord`). Every controller query must include `userId: req.user.id` in the filter. `Strategy` is the only model WITHOUT `userId` — strategies are shared across all users.

### Auth architecture

- **Google OAuth 2.0** via Passport.js, sessionless (`passport.initialize()` only — no `passport.session()`).
- **JWT in `httpOnly` cookie** (`enma_jwt`, `sameSite: lax`, 7-day expiry). Verified by `verifyJWT` middleware.
- Route mounting order in `app.js`: `auth.routes` and `/internal` are unprotected; `app.use('/api/v1', verifyJWT)` gates all other routes.
- `req.user` is a Mongoose `.lean()` User document — available in every protected controller.
- `requireAdmin` middleware (checks `req.user.role === 'admin'`) is applied at the router level in `admin.routes.js`.
- `requireAlgoAccess` middleware (passes if `role === 'admin'` OR `algoAccess.status === 'granted'`; else 403 `ALGO_ACCESS_REQUIRED`) gates only the Algo start actions: `POST /algo/sessions` and `POST /algo/chaos`. Absence of `algoAccess` reads as no access. Since `verifyJWT` reloads the user each request, grants/revokes apply immediately — no JWT re-issue needed.
- **Socket.IO**: `io.use()` middleware parses the `enma_jwt` cookie, verifies JWT, and attaches `socket.user`. On connection, the socket joins `user:<userId>` room. All `io.emit()` calls must be `io.to('user:<userId>').emit()` — never broadcast globally.
- **Internal routes** (`/internal/*`) have no `req.user` — they carry session context via `req.params.id` (LiveSession ID). Use `_getBinanceHeaders(sessionId)` which looks up `userId` via `LiveSession.findById`.
- **Open login**: the OAuth strategy (`passport.js`) no longer gates on any whitelist — anyone with a valid Google account signs in. `ADMIN_EMAIL` is still auto-promoted to `role: 'admin'` on first login. **Local-dev-only exception**: `AUTH_RESTRICT_TO_ADMIN=true` (unset/false in production) rejects every Google account except `ADMIN_EMAIL` at the OAuth callback — for a local dev environment that shouldn't accept arbitrary sign-ins. Never set in production.
- Admin panel: `GET /api/v1/admin/users` (all users + algo-access status) and `PATCH /api/v1/admin/users/:id/algo-access` (`{ status: 'granted'|'none' }`) — admin rows are not editable. Users self-request via `POST /api/v1/algo/access-request` (idempotent `none`→`requested`).
- The former `PlatformConfig` email-whitelist model, `/admin/allowed-emails` routes, and `seedPlatformConfig()` were removed 2026-07-07 — do not reintroduce them.

### Dashboard proxy rules

- `GET /api/v1/dashboard/stats` → `dashboard.controller.js` → proxies `GET {ENGINE_URL}/dashboard/stats` via `engineClient`; returns result to client unchanged
- `GET /api/v1/candles/cached` → `candle.controller.js` (`getCachedCandles`) → proxies `GET {ENGINE_URL}/candles/cached` via `engineClient`; returns result to client unchanged
- Server does **not** perform any aggregation itself — both endpoints are pure proxies; all data computation happens in the engine

---

## What Claude Code must NOT do in server/

- Write financial calculations, indicator math, or order logic
- Call Binance API directly (all exchange calls go through engine)
- Store plain-text API keys or passwords
- Skip request validation middleware on any route
- Use `process.exit()` — use proper error handling
- Add new npm packages without updating root CLAUDE.md stack table
- Connect to TimescaleDB — only engine queries candle data
- Omit `userId` from any controller query on mutable models — every read/write must be scoped to `req.user.id`
- Add `userId` to the `Strategy` model — strategies are global/shared
