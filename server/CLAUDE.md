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
- jsonwebtoken + bcryptjs
- express-validator (installed but not used as standalone middleware — validation inline in controllers)
- express-rate-limit (inline in `app.js`)
- Helmet.js
- Morgan for logging
- dotenv
- axios (HTTP calls to Python engine via `services/engineClient.js`)
- uuid (v4 job ID generation)

---

## Folder structure

```
server/
└── src/
    ├── config/
    │   ├── redis.js        ← ioredis client singleton (shared by BullMQ + pub/sub)
    │   └── socket.js       ← Socket.IO server setup
    ├── middleware/
    │   ├── errorHandler.js          ← global error handler
    │   └── requireBinanceCredentials.js ← validates X-Binance headers on trade routes
    ├── models/             ← Mongoose models
    │   ├── Strategy.js        ← metadata: name, description, filePath
    │   ├── BacktestResult.js  ← server fields: jobId, status, error, tradeCount
    │   │                         engine fields (Mixed, never written by server): metrics, equityCurve
    │   ├── BacktestTrade.js   ← split collection backtestTrades (jobId, tradeIndex, …)
    │   ├── LiveSession.js
    │   ├── TradeOrder.js
    │   ├── TradeExecution.js
    │   ├── TradeTransaction.js
    │   └── Settings.js        ← AES-encrypted Binance keys + exchange settings
    ├── routes/             ← Express routers (thin — logic in controllers)
    │   ├── strategy.routes.js   ← /strategies, /strategies/:id/code
    │   ├── candle.routes.js     ← /candles/symbols, /candles/cached
    │   ├── backtest.routes.js
    │   ├── dashboard.routes.js  ← /dashboard/stats
    │   ├── trade.routes.js      ← /trade/* (settings/keys, account, positions, orders, klines)
    │   ├── algo.routes.js       ← /algo/sessions, /algo/symbols/locked
    │   ├── settings.routes.js   ← /settings/exchange
    │   └── internal.routes.js   ← /internal/algo/sessions/:id/* (engine callbacks)
    ├── controllers/
    │   ├── strategy.controller.js   ← MongoDB queries + code proxy to engine
    │   ├── candle.controller.js     ← getSymbols, getCachedCandles
    │   ├── backtest.controller.js
    │   ├── dashboard.controller.js  ← proxies engine /dashboard/stats
    │   ├── trade.controller.js
    │   ├── algo.controller.js       ← session CRUD + engine callbacks (handleEngineStats, handleAlgoPlaceOrder, …)
    │   └── settings.controller.js   ← getExchangeSettings, updateExchangeSettings
    ├── services/
    │   ├── engineClient.js  ← axios instance for engine HTTP calls
    │   ├── backtestQueue.js ← BullMQ queue definition for bull:backtest
    │   ├── socketEmitter.js ← Redis pub/sub → Socket.IO relay
    │   └── symbolLock.js    ← Redis-backed symbol lock (bot vs manual)
    ├── workers/
    │   └── backtest.worker.js
    ├── utils/
    │   ├── ApiError.js      ← Custom error class
    │   ├── ApiResponse.js   ← Standard response helpers
    │   └── encryption.js    ← AES-256 for API key storage
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
- **One active queue:** `bull:backtest` — no candle queue, no live queue
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
| TimescaleDB — `candles` | engine | **Never** — server never queries TimescaleDB |
| Redis — BullMQ queues | server | Write (enqueue jobs) |
| Redis — progress pub/sub | engine writes, server reads | Subscribe and relay to Socket.IO |
| Redis — cancel flags | server writes, engine reads | Write only (`backtest:cancel:{jobId}`) |
| Redis — symbol locks | server writes/reads | Via `symbolLock.js` (bot vs manual lock) |
| Redis — live bot cache | engine writes, server reads | Read-only |

**Policies:**
- server/ never connects to TimescaleDB — all candle data comes through engine HTTP endpoints
- server/ never writes `metrics`, `trades`, or `equityCurve` to `backtestResults` or individual trades to `backtestTrades` — engine is the sole writer for result data; server only updates the `status` and `error` fields
- `metrics`, `trades`, and `equityCurve` are defined as `mongoose.Schema.Types.Mixed` in `BacktestResult.js` to make engine ownership explicit; do not add typed Array or Object schema definitions for these fields
- `CandleImport` model, `candle.worker.js`, `candleQueue.js`, `liveQueue.js`, `live.worker.js` — none exist; do not create them
- No `auth.routes.js` or `auth.controller.js` — auth routes are not yet mounted; do not add auth scaffolding
- Strategy code lives on engine disk — server never reads strategy files directly; always proxy via `GET engine:8000/strategies/:name/code`
- Strategy metadata (name, description, filePath) lives in MongoDB `strategies` collection, owned by server
- No `user_id` on any Mongoose model — this is a single-user platform

### Dashboard proxy rules

- `GET /api/v1/dashboard/stats` → `dashboard.controller.js` → proxies `GET {ENGINE_URL}/dashboard/stats` via `engineClient`; returns result to client unchanged
- `GET /api/v1/candles/cached` → `candle.controller.js` (`getCachedCandles`) → proxies `GET {ENGINE_URL}/candles/cached` via `engineClient`; returns result to client unchanged
- Server does **not** perform any aggregation itself — both endpoints are pure proxies; all data computation happens in the engine
- Both endpoints require JWT auth middleware (same as all other `/api/v1/` routes)

---

## What Claude Code must NOT do in server/

- Write financial calculations, indicator math, or order logic
- Call Binance API directly (all exchange calls go through engine)
- Store plain-text API keys or passwords
- Skip request validation middleware on any route
- Use `process.exit()` — use proper error handling
- Add new npm packages without updating root CLAUDE.md stack table
- Connect to TimescaleDB — only engine queries candle data
- Add user_id fields to any Mongoose model (see root CLAUDE.md for platform-wide rules)
