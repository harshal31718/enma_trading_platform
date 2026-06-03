# Enma — Decision Log

> Append-only. Never delete or edit past entries.
> Add a new entry every time an architectural decision is made in chat.
> Format: `## [date] — topic`

---

## 2024 — Initial architecture

**Stack:** MERN (MongoDB, Express, React, Node.js) + Python FastAPI for the strategy engine.
Chosen because: React/Node is the developer's primary stack, Python is necessary for TA-Lib
and ccxt, and FastAPI is the fastest Python web framework for this use case.

**Monorepo:** Single repo with `client/`, `server/`, `engine/` directories.
Chosen because: solo developer + Claude Code needs full project visibility in one session.

**Job queue:** BullMQ backed by Redis.
Chosen because: backtests are long-running jobs that need progress streaming, cancellation,
and retry logic. BullMQ is the most mature Redis-backed queue for Node.js.

**Exchange:** Binance Spot + Futures via ccxt (Python).
Chosen because: ccxt abstracts exchange APIs and supports 100+ exchanges — adding others
later is a config change, not a rewrite.

**Frontend state:** Zustand for global UI state, TanStack Query for server state.
Chosen because: Redux is overkill for this project size. TanStack Query handles caching,
refetching, and loading states for API data automatically.

**Auth:** JWT with refresh tokens.
Chosen because: stateless, works well with the monorepo structure, no session storage needed.

**Candle storage:** MongoDB initially. TimescaleDB (PostgreSQL extension) as an optional
upgrade for when candle data grows large.
Chosen because: MongoDB is already in the stack. TimescaleDB is better for time-series at
scale but adds operational complexity — defer until needed.

**Deployment:** Vercel (client) + Oracle Cloud Free VM (server + engine) + MongoDB Atlas Free
+ Upstash Redis Free.
Chosen because: maximizes free tier hosting during development and early production.

**Reference implementation:** Jesse.trade (https://docs.jesse.trade).
The strategy interface (`BaseStrategy`) intentionally mirrors Jesse's API so strategies
are portable between the two platforms.

---

## Decision template for future entries

```
## YYYY-MM-DD — [topic]

**Decision:** [what was decided]
**Alternatives considered:** [what else was on the table]
**Reason:** [why this was chosen]
**Impact:** [what this affects]
```

## 2024 — UI component library

**Decision:** shadcn/ui as the component base for the React frontend.
**Alternatives considered:** Pure Tailwind from scratch, Chakra UI, MUI.
**Reason:** shadcn copies source into the repo — we own the code, full control, Tailwind-native, no version lock-in.
**Impact:** All UI primitives (Button, Input, Dialog, etc.) come from shadcn. Never rebuild these from scratch.

## 2024 — Color palette

**Decision:** Emerald (primary) + Yellow (accent) + Blue (info). Green/Red reserved strictly for financial P&L data.
**Alternatives considered:** Blue primary, purple primary.
**Reason:** Emerald feels distinct from generic trading apps. Yellow gives strong attention cues for key metrics. Strict green/red reservation prevents color meaning confusion — green always means profit, never "active button".
**Impact:** Enforced in client/CLAUDE.md. Claude Code must never use green/red for UI chrome.

---

## 2026-06-02 — shadcn manual setup (no CLI init)

**Decision:** Manually wrote `components.json`, shadcn CSS variables, and all UI primitives by hand rather than using `npx shadcn@latest init`.
**Alternatives considered:** Running `shadcn init` via CLI.
**Reason:** The latest shadcn CLI (v4.x) requires an interactive TTY to select presets and cannot be bypassed non-interactively in the current environment. Manual setup produces identical output and is fully equivalent.
**Impact:** `components.json` exists and is correctly configured. All shadcn primitives (Badge, Skeleton, etc.) are hand-written but follow the same shadcn conventions. Future `npx shadcn@latest add <component>` commands should work normally now that `components.json` is in place.

## 2026-06-02 — @vitejs/plugin-react pinned to v4

**Decision:** Installed `@vitejs/plugin-react@4` instead of latest (v6).
**Alternatives considered:** Upgrading to Vite 8 to use plugin-react v6.
**Reason:** The spec mandates Vite 5. `@vitejs/plugin-react@6` requires Vite 8+ as a peer dependency and fails to resolve with Vite 5. Version 4 is the last release compatible with Vite 5.
**Impact:** Vite 5 is preserved as required. No functional difference — v4 supports all React 18 features including Fast Refresh and JSX transform.

## 2026-06-02 — Radix UI primitives installed directly

**Decision:** Installed individual `@radix-ui/react-*` packages directly rather than relying on shadcn CLI to install them.
**Alternatives considered:** Waiting for shadcn CLI to work.
**Reason:** shadcn CLI could not run non-interactively (see manual setup decision above). Radix primitives are the same packages shadcn would have installed.
**Impact:** All required Radix packages are in `package.json`. No functional difference.

---

## 2026-06-02 — Docker architecture for local development

**Decision:** Separate Dockerfile per service (`client/`, `server/`, `engine/`) orchestrated by a single `docker-compose.yml` at the project root. Dev only — no production compose config will ever exist in this repo.
**Alternatives considered:** Single monolithic container; docker-compose only for databases with services run natively.
**Reason:** Isolates each service's dependency chain (especially Python + TA-Lib from source), eliminates Windows-host TA-Lib installation pain, and ensures every developer starts with `docker-compose up` and gets a working environment with zero manual setup.
**Impact:** All services start together via `docker-compose up`. Code is mounted as volumes for live reload (Vite HMR for client, nodemon for server, uvicorn --reload for engine). `node_modules` for client and server live in named Docker volumes — never mounted from the Windows host to avoid path/symlink issues. TA-Lib is built from source inside the engine container only. Named volumes for MongoDB, TimescaleDB, and Redis data persist across `docker-compose down`. Port assignments: client 5173, server 5000, engine 8000, MongoDB 27017, Redis 6379, TimescaleDB 5432.

## 2026-06-02 — TimescaleDB as primary candle store (replaces MongoDB)

**Decision:** TimescaleDB (PostgreSQL + TimescaleDB extension) is the candle store from day one. MongoDB is NOT used for OHLCV data at any point.
**Alternatives considered:** MongoDB initially, migrate to TimescaleDB later (the original plan).
**Reason:** The "MongoDB initially, TimescaleDB later" plan was deferred complexity, not avoided complexity — a migration would have been more disruptive than starting correctly. OHLCV data is a pure time-series workload; TimescaleDB's hypertables, continuous aggregates, and time-bucket queries are purpose-built for it. MongoDB's document model adds no value for candles and its query performance for sequential time-range reads is measurably worse.
**Impact:** MongoDB owns: users, strategies, backtestResults, liveSessions, notifications. TimescaleDB owns: all OHLCV candle data. Engine uses asyncpg (async PostgreSQL driver) for TimescaleDB writes/reads and pymongo for MongoDB. All references to "MongoDB candles collection" in docs are replaced. The `candles` collection is removed from the MongoDB collections table. A new TimescaleDB section is added to ARCHITECTURE.md.

---

## 2026-06-02 — motor used instead of raw pymongo for async MongoDB

**Decision:** Use `motor` (Motor async driver) as the MongoDB client in the engine, not `pymongo` directly.
**Alternatives considered:** pymongo (synchronous), pymongo with `run_in_executor` wrapping.
**Reason:** The engine is a fully async FastAPI application. `pymongo` is synchronous and blocks the event loop when called directly inside async routes — this would serialize all MongoDB operations and defeat the async architecture. `motor` is the official async wrapper around `pymongo` maintained by MongoDB Inc., uses the same API surface, and integrates cleanly with asyncio. `pymongo` remains a transitive dependency of `motor`.
**Impact:** `motor` added to `engine/requirements.txt`. `engine/config/mongo.py` uses `AsyncIOMotorClient`. The `engine/CLAUDE.md` stack entry for `pymongo` should be understood to mean motor in practice. Stack table in `CLAUDE.md` updated to reflect `motor`.

---

## 2026-06-02 — Single-user model (no user_id anywhere)

**Decision:** No user concept, no user_id fields. All data in all databases belongs to the single local developer by definition.
**Alternatives considered:** Option B (add user_id everywhere now), Option C (project/session namespace).
**Reason:** Simpler implementation, faster development. Multi-user can be added later if needed — no schema migrations required since there's no user isolation to remove.
**Impact:**
- No user_id columns in TimescaleDB
- No user_id fields in MongoDB documents
- No user context in Redis keys
- All queries/filters work on global data, not per-user

## 2026-06-02 — Three-database architecture finalized

**Decision:** Three-database architecture as designed:
- MongoDB: strategies, backtestResults, liveSessions, candleImports, (settings later)
- TimescaleDB: candles hypertable with schema [time, exchange, symbol, timeframe, instrument_type, expiry, open, high, low, close, volume, quote_volume]
- Redis: BullMQ job queues, live session cache, progress channels

**Alternatives considered:** Single database, different partitioning.
**Reason:** Each database type owns the data it's best at — document storage (MongoDB), time-series (TimescaleDB), cache/queue (Redis).
**Impact:**
- engine/ connects to both MongoDB (motor) and TimescaleDB (asyncpg)
- server/ writes job results to MongoDB via engine
- All candle queries go to TimescaleDB, never MongoDB
- Backtest results stored as full documents in MongoDB (equity curve + trades array)
- Live sessions persist in MongoDB, cache in Redis

## 2026-06-02 — Horizontal navbar replaces fixed sidebar

**Decision:** Replace fixed left sidebar (240px) with a horizontal navbar fixed at top, spanning full width.
**Alternatives considered:** Keep sidebar, collapsible sidebar, icon-only sidebar.
**Reason:** A top navbar is a better fit for a dashboard with a small number of top-level routes and avoids the persistent 240px left margin that reduces usable chart/table width.
**Impact:**
- Remove Sidebar.jsx component entirely
- Update TopBar.jsx to include full navbar (logo + nav items)
- Remove ml-[240px] from PageWrapper — now just pt-[56px] and full width
- Update all page layouts since there's no longer a fixed sidebar column
- client/CLAUDE.md layout rules section updated

---

## 2026-06-02 — Candle importer: exchange library

**Decision:** ccxt used for all historical candle fetching (backtest phase). Official Binance SDKs (binance-connector-python, binance-futures-connector-python) reserved for live trading phase — not added yet.
**Alternatives considered:** Official Binance SDKs from the start, python-binance.
**Reason:** ccxt provides one unified interface for both spot and futures. Jesse compatibility. Live trading will use official SDKs for reliability.
**Impact:**
- engine uses `ccxt.binance()` for spot, `ccxt.binanceusdm()` for perpetual futures
- ccxt already in requirements.txt — no new packages needed

## 2026-06-02 — Candle importer: symbol format

**Decision:** App-wide symbol format is `BTC-USDT` (hyphen-separated). Engine converts to `BTC/USDT` (slash) internally when calling ccxt. Conversion is always done inside the engine — never in server or client.
**Alternatives considered:** Use ccxt slash format everywhere, use exchange-native formats.
**Reason:** Hyphen format is URL-safe and consistent. Centralising the conversion in the engine means the rest of the stack never needs to know about ccxt's format.
**Impact:**
- All API contracts, MongoDB documents, TimescaleDB rows use `BTC-USDT`
- Engine has a utility function: `to_ccxt_symbol(symbol)` — replaces `-` with `/`

## 2026-06-02 — Candle importer: symbol list

**Decision:** Top 50 perpetual futures symbols hardcoded in a global constants file. Futures only for now. Spot symbols to be added in a later phase. List stored in `engine/core/constants.py` as `FUTURES_SYMBOLS`. Client reads this list via a dedicated endpoint.
**Alternatives considered:** Fetching live symbol list from Binance on startup, letting users type symbols freely.
**Reason:** Stable working set during development. Fetching live from Binance adds startup dependency — deferred to a later cleanup pass.
**Impact:**
- `engine/core/constants.py` contains `FUTURES_SYMBOLS` (BTC-USDT format) and an empty `SPOT_SYMBOLS` placeholder
- `GET /candles/symbols` engine endpoint returns both lists
- Constants file has a clearly commented placeholder section for spot symbols

## 2026-06-02 — Candle importer: fetch mechanics

**Decision:** Batch size 1000 candles per ccxt call (Binance maximum). Delay between batches: 200ms, configurable via `BINANCE_FETCH_DELAY_MS` env var. Duplicate handling: `INSERT ... ON CONFLICT DO NOTHING` (safe to re-import). Progress published to Redis pub/sub after every batch. Storage: TimescaleDB candles hypertable via asyncpg.
**Alternatives considered:** Smaller batches, no delay, upsert instead of ignore-on-conflict.
**Reason:** 1000 is the Binance API maximum — maximises throughput. 200ms delay stays within rate limits. ON CONFLICT DO NOTHING makes re-imports idempotent without upsert overhead.
**Impact:**
- `candle_importer.py` uses `fetch_ohlcv` with limit=1000 in a loop
- `BINANCE_FETCH_DELAY_MS` read from env with default 200
- TimescaleDB unique index on `(time, exchange, symbol, timeframe, instrument_type)` enforces no-duplicate constraint

## 2026-06-02 — Candle importer: UI

**Decision:** Dedicated Import Candles page (already exists as stub) with two sections: import form (exchange, symbol, timeframe, date range, submit) and import history table (past imports from MongoDB candleImports collection).
**Alternatives considered:** Modal-based import flow, inline import on other pages.
**Reason:** Import is a distinct workflow that warrants its own page. History table gives visibility into what data is available for backtests.

---

## 2026-06-02 — Strategy storage: files on disk

**Decision:** Strategy code stored as actual Python files on the engine container filesystem. MongoDB stores metadata only (name, description, filePath, createdAt, updatedAt). Code never stored in MongoDB.
**Alternatives considered:** Storing code as strings in MongoDB, storing code in a separate code-focused database.
**Reason:** Real files allow proper Python imports, easier debugging, no temp file management complexity. Files are on a Docker volume so they persist and are editable from the host machine.
**Impact:**
- `engine/strategies/` directory is the strategy store
- MongoDB `strategies` collection: name, description, filePath, createdAt, updatedAt — metadata only
- Server reads code by asking engine; engine reads from disk
- User-created strategies deferred to a later phase

## 2026-06-02 — Default strategies: 3 shipped with app

**Decision:** Three default strategies seeded into the engine on startup (if not already present): SimpleEMACross, RSIReversion, DonchianBreakout.
**Alternatives considered:** No default strategies; user must create their own from scratch.
**Reason:** Gives the platform real usable content from day one. Covers three strategy styles (trend following, mean reversion, breakout) and serves as learning examples and test data.
**Impact:**
- Engine startup checks `engine/strategies/` for the three folders; creates them if missing
- Upserts metadata into MongoDB `strategies` collection on every startup (idempotent)
- `engine/services/strategy_seeder.py` owns this logic

## 2026-06-02 — Strategy boilerplate interface

**Decision:** Every Enma strategy extends `BaseStrategy` defined in `engine/core/strategy.py`. Interface mirrors Jesse's strategy API intentionally for portability.
**Alternatives considered:** Duck typing with no base class, Protocol/ABC without a concrete base.
**Reason:** A concrete base class with sensible defaults for optional methods keeps strategy files minimal. Jesse compatibility is a stated goal — matching the interface exactly lowers the migration cost for existing Jesse users.
**Impact:**
- `engine/core/strategy.py` is the canonical interface definition — do not change it without a new DECISIONS.md entry
- Required methods: `should_long`, `should_short`, `should_cancel_entry`, `go_long`, `go_short`
- Optional lifecycle: `before`, `after`, `update_position`, `__init__`, `before_terminate`, `terminate`
- Optional event hooks: `on_open_position`, `on_close_position`, `on_increased_position`, `on_reduced_position`, `on_cancel`
- Available properties injected by the backtest engine at runtime (candles, price, position, balance, etc.)

## 2026-06-02 — Strategies UI: phase 1 read-only

**Decision:** Strategies page shows a list of the 3 default strategies as cards. Each card has a "View" button that opens a read-only code viewer (styled pre block, no editor). No create, edit, or delete in this phase.
**Alternatives considered:** Full browser-based Monaco editor from the start.
**Reason:** User-created strategies and a browser-based editor are deferred to a later phase. Read-only viewer gives visibility into strategy logic without editor complexity.
**Impact:**
- `client/src/features/strategies/StrategyCard.jsx` — card: name, description, type badge, View button
- `client/src/features/strategies/CodeViewer.jsx` — read-only pre block rendered in a Dialog
- `client/src/hooks/useStrategies.js` — `useStrategies()` and `useStrategyCode(id)` TanStack Query hooks

---

## 2026-06-03 — Import Candles page removed entirely

**Decision:** The Import Candles page (`ImportCandles.jsx`) is removed. Candle fetching is handled automatically by the backtest engine via `ensure_candles_available()` when a backtest is submitted. No manual import step is required.
**Alternatives considered:** Keeping the manual import page alongside auto-fetch.
**Reason:** Auto-fetch eliminates the need for a separate import workflow entirely. Users no longer need to pre-import candles before running a backtest — the engine does it transparently. Removing the page simplifies the UI and removes an entire data flow path.
**Impact:**
- `client/src/pages/ImportCandles.jsx` deleted
- Import Candles removed from navbar (5 nav items remain: Dashboard, Strategies, Backtest, Live Trading, Settings)
- `CandleImport` MongoDB collection removed from architecture
- `server/src/models/CandleImport.js` deleted
- `server/src/controllers/candle.controller.js` import/available methods deleted; `getSymbols` kept
- `server/src/routes/candle.routes.js` import/available routes deleted; `GET /symbols` kept
- `server/src/workers/candle.worker.js` deleted
- `server/src/services/candleQueue.js` deleted
- `socketEmitter.js` candle job type removed
- `client/src/hooks/useCandles.js` — `useAvailableImports` and `useImportCandles` deleted; `useSymbols()` kept
- `client/src/features/candles/` directory and all components deleted

---

## 2026-06-03 — Candle data kept permanently in TimescaleDB

**Decision:** Candle data fetched during backtest auto-fetch is stored permanently in TimescaleDB and reused across subsequent backtests. No deletion after backtest run.
**Alternatives considered:** Deleting candles after each backtest run to save storage.
**Reason:** Backtests are iterative — the same symbol/timeframe/date range is used many times during strategy development. Re-fetching wastes 30–60 seconds per run. TimescaleDB stores time-series efficiently with hypertable compression. `ON CONFLICT DO NOTHING` makes re-fetches idempotent.
**Impact:**
- `ensure_candles_available()` remains the single entry point for all candle data — never bypassed
- `ON CONFLICT DO NOTHING` in `INSERT` ensures re-fetches are safe
- No candle cleanup logic anywhere in the codebase

---

## 2026-06-03 — Backtest engine is sole writer to backtestResults

**Decision:** The engine is the only writer to the `backtestResults` MongoDB collection. The server worker reads the engine HTTP response but does NOT write metrics, trades, or equityCurve to MongoDB independently. Eliminates double-write.
**Alternatives considered:** Server worker writes the full result document after engine responds.
**Reason:** Having both the engine and the server write to the same collection is an architecture violation — it creates two competing writers for the same document. The engine already writes the full result during `run_backtest_simulation()`. The worker only needs to relay the completion event to the client.
**Impact:**
- `server/src/workers/backtest.worker.js` — worker calls engine, then only updates `status` field on the existing MongoDB document; never writes `metrics`, `trades`, or `equityCurve`
- Engine writes full result document (metrics + trades + equityCurve) via upsert in `backtest_runner.py`
- Server never calls `db.backtestResults` with result data directly

---

## 2026-06-03 — Backtest cancel — engine owns status update

**Decision:** The cancel flow calls the engine to set the Redis cancel flag. Server does not write to `backtestResults` directly to set `cancelled` status. Engine handles status update when it detects the cancel flag during simulation.
**Alternatives considered:** Server immediately overwrites status to `cancelled` in MongoDB, engine ignores.
**Reason:** Consistent with the "engine is sole writer to backtestResults" decision above. Server writing a cancel status races with the engine's own cleanup. Engine detects the cancel flag, raises `JOB_CANCELLED`, and the error handler in `routers/backtest.py` writes `status: failed` with the cancellation error message.
**Impact:**
- `server/src/controllers/backtest.controller.js` `cancelBacktest` — remove the direct `BacktestResult.updateOne` call; only call the engine cancel endpoint
- Engine raises `RuntimeError("JOB_CANCELLED")` → router catches and writes `status: failed, error: "Cancelled by user"` to MongoDB

---

## 2026-06-03 — Redis subscription cleanup after backtest events

**Decision:** `socketEmitter.js` unsubscribes from Redis pub/sub channels after `backtest:complete` or `backtest:error` events to prevent accumulating dead subscriptions.
**Alternatives considered:** Never unsubscribing; relying on Redis TTL.
**Reason:** Each backtest job subscribes to `progress:{jobId}`. Without cleanup, every completed job leaves a dead subscription open for the lifetime of the server process. Over many runs this leaks memory and Redis connections.
**Impact:**
- `socketEmitter.js` exports `unsubscribeFromJob(jobId)` function
- `backtest.worker.js` calls `unsubscribeFromJob(jobId)` after emitting `backtest:complete` or `backtest:error`
- `jobTypes` Map entry is deleted on unsubscribe

---

## 2026-06-03 — Dashboard page: simulation metrics hub

**Decision:** Implement the Dashboard (`/`) as a simulation metrics hub and local data monitor. The page contains four sections: a key stats grid (4 StatCards), a CachedCandlesTable showing all symbol/timeframe ranges currently stored in TimescaleDB, a RecentActivityTable listing the last 5 backtest runs, and a StrategyLeaderboard showing averaged metrics per strategy.
**Alternatives considered:** Keeping Dashboard as a generic "welcome" shell with no data; deferring a real Dashboard until live trading (Phase 5).
**Reason:** Live trading is deferred. During the backtesting phase the developer needs direct visibility into (a) what candle data is already cached in TimescaleDB to avoid duplicate Binance fetches, and (b) an at-a-glance summary of simulation history and strategy performance. A simulation metrics hub serves both needs without requiring any live trading infrastructure.
**Impact:**
- `GET /api/v1/dashboard/stats` added to server — returns overall stats object and strategy leaderboard array
- `GET /api/v1/candles/cached` added to server — returns cached candle summary from TimescaleDB (symbol, timeframe, start_date, end_date, total_candles per group)
- `GET {ENGINE_URL}/dashboard/stats` added to engine — internal endpoint the server proxies
- `GET {ENGINE_URL}/candles/cached` added to engine — runs TimescaleDB GROUP BY query and returns candle cache summary
- New components: `StatCard`, `CachedCandlesTable`, `RecentActivityTable`, `StrategyLeaderboard` — all under `client/src/features/dashboard/`
- New hooks: `useDashboardStats()`, `useCachedCandles()` in `client/src/hooks/useDashboard.js`
- `/backtest` page reads optional `?jobId=` query param on mount to auto-select a historical run (for deep-linking from RecentActivityTable)
- Navigation link format: `/backtest?jobId={jobId}`

---

## 2026-06-03 — Phase 4.5: Polish, cleanup, and optimization

### a) Dead client code removed

**Decision:** Five files in `client/` that were never imported anywhere were deleted.

| File | Reason for deletion |
|---|---|
| `client/src/components/ui/DataTable.jsx` | Never imported anywhere in the codebase |
| `client/src/components/ui/EmptyState.jsx` | Never imported anywhere in the codebase |
| `client/src/components/ui/StatusBadge.jsx` | Never imported anywhere in the codebase |
| `client/src/components/ui/StatCard.jsx` | Duplicate of `features/dashboard/StatCard.jsx` with a different prop API (`subtitle`/`trend`/`trendValue` vs `title`/`value`/`subtext`/`icon`); the `features/dashboard` version is the one in active use |
| `client/src/store/useUIStore.js` | Zustand store for sidebar state that is never imported anywhere; sidebar was removed in Phase 1 |

**Alternatives considered:** Keeping the files as unused stubs.
**Reason:** Dead code that is never imported increases maintenance surface and causes confusion about which StatCard variant is correct. Removing them makes the codebase state unambiguous.
**Impact:** Only `features/dashboard/StatCard.jsx` exists as the canonical StatCard. `components/ui/` no longer contains DataTable, EmptyState, StatusBadge, or StatCard.

---

### b) Backtest.jsx decomposed into feature components

**Decision:** `Backtest.jsx` was a monolithic page component. Three components were extracted to `client/src/features/backtest/`:
- `BacktestConfigForm.jsx` — form fields, strategy/symbol/timeframe/date/capital/leverage/fee inputs, submit and cancel button logic
- `BacktestHistory.jsx` — history sidebar list, selected-run highlighting with emerald left border, refresh button
- `BacktestMetricCard.jsx` — single reusable KPI stat card replacing 6 inline copies of the same `<Card>` + icon + value + subtitle pattern

**Alternatives considered:** Leaving everything in `Backtest.jsx`.
**Reason:** `Backtest.jsx` had grown too large to navigate. Extracting to feature components makes each concern independently readable and testable. `BacktestMetricCard` eliminates repeated inline markup that had to be kept in sync manually.
**Impact:** `Backtest.jsx` is now state management + layout wiring only. The three feature components live in `client/src/features/backtest/`.

---

### c) Error UX: alert() replaced with inline error banner

**Decision:** All `alert()` calls in `Backtest.jsx` replaced with `errorMessage` local state rendered as a red inline banner inside the page.

**Alternatives considered:** Keeping `alert()` for simplicity; using a toast library.
**Reason:** `alert()` blocks the browser thread, is not styleable, and is jarring UX for a trading dashboard. An inline banner keeps the user in context, is dismissible on the next run attempt, and matches the dark theme. A toast library would add a dependency for a single use case.
**Impact:** `errorMessage` state (string | null) is set on backtest run failure, cancel failure, and socket error. The banner renders as `bg-red-950/20 border border-red-800/40` with an `AlertTriangle` icon from lucide-react. It is cleared (set to null) when the user clicks "Run Backtest" again.

---

### d) Formatter: formatSignedPct added to client/src/utils/formatters.js

**Decision:** Added `formatSignedPct(value)` to the shared formatters module.

**Signature:** `formatSignedPct(value: number | string) → string`
**Output examples:** `+32.41%`, `-8.20%`, `+0.00%`

**Alternatives considered:** Inlining the sign logic per component.
**Reason:** `RecentActivityTable` and `StrategyLeaderboard` both display P&L percentage with a required sign prefix. Without a shared formatter the sign logic would be duplicated and could drift. `formatSignedPct` mirrors the contract of `formatPnl` (always show sign) but for percentage values.
**Impact:** `formatSignedPct` exported from `client/src/utils/formatters.js`. Used in `RecentActivityTable` and `StrategyLeaderboard` for P&L% columns.

---

### e) Engine data integrity — two fixes in candle_importer.py

**Decision:** Two bugs in `engine/services/candle_importer.py` were corrected.

**Fix 1 — instrument_type value:**
- Was: `"perpetual"` for `exchange == "Binance Futures"`
- Now: `"futures"` to match the TimescaleDB schema and `candle_manager.py` queries
- Root cause of cache miss: `ensure_candles_available()` queries TimescaleDB using the exchange name directly as a filter. The mismatch between `"perpetual"` (written by importer) and `"futures"` (expected by schema/manager) caused every futures candle lookup to return 0, triggering an unnecessary re-fetch on every backtest run.

**Fix 2 — expiry column added to INSERT:**
- The `candles` hypertable has an `expiry TEXT` nullable column.
- The `INSERT` statement was omitting this column entirely, relying on PostgreSQL default (NULL).
- Now: `expiry` is explicitly included in the INSERT column list and always set to `NULL` for spot and perpetual futures.
- Exchange-dated futures (e.g., quarterly contracts with a defined settlement date) will populate this field in a future phase.

**Alternatives considered:** Leaving `expiry` as implicit NULL.
**Reason:** Explicit NULL is self-documenting and ensures the INSERT column list matches the full 12-column schema. Implicit omission would silently break if the column ever gained a NOT NULL constraint.
**Impact:** `instrument_type` is now `"futures"` for Binance Futures and `"spot"` for Binance Spot. The INSERT now lists all 12 columns including `expiry NULL`. Cache miss on re-run is eliminated.

---

### f) BacktestResult Mongoose schema simplified

**Decision:** `server/src/models/BacktestResult.js` schema updated to reflect data ownership.

- `metrics`: changed from untyped field to `mongoose.Schema.Types.Mixed`
- `trades`: changed from `{ type: Array, default: [] }` to `mongoose.Schema.Types.Mixed`
- `equityCurve`: changed from `{ type: Array, default: [] }` to `mongoose.Schema.Types.Mixed`

**Alternatives considered:** Leaving the schema as-is.
**Reason:** The server never writes `metrics`, `trades`, or `equityCurve` — the engine is the sole writer for those fields (established in the 2026-06-03 "Backtest engine is sole writer" decision). Defining these as typed Array fields with defaults (`[]`) implies the server manages them and creates a false expectation. `Mixed` schema makes data ownership explicit: these are engine-owned payload fields that the server stores without inspecting or defaulting.
**Impact:** `BacktestResult.js` schema now uses `Mixed` for all three engine-owned fields. Server behaviour is unchanged — it still only writes `status`, never `metrics`/`trades`/`equityCurve`.

---

### g) Auth deferred

**Decision:** All routes remain open (no JWT middleware applied) for this phase.
**Reason:** Auth infrastructure exists but wiring it to every route is a separate task. Single-user dev environment requires no auth for local use. Auth will be enforced as a hardening pass before any deployment.
**Impact:** None to current functionality.

---

## 2026-06-03 — Backtesting engine performance and database optimizations (BSON limit fix)

**Decision:** Optimize the backtest runner execution loop and database persistence schema:
1. **Vectorized Metrics:** Replaced slow Python loops for drawdown, Sharpe, Sortino, and trade statistic calculations with vectorized NumPy implementations.
2. **NumPy Hot Loop Prep:** Replaced dict allocations in the simulation loop with flat NumPy arrays and list structures, converting to dicts only after simulation completes.
3. **Async Cancellation Monitoring:** Replaced synchronous Redis cancel checking with a concurrent asyncio pub/sub watcher that flips a local flag, eliminating network round-trip delays in the simulation loop.
4. **MongoDB Document Limit (BSON) Mitigation:**
   - Downsample the equity curve to at most 1,000 points (`EQUITY_CURVE_MAX_POINTS`) before MongoDB write.
   - Decouple the trade log array from the main `backtestResults` document. Trades are bulk-inserted in batches of 500 (`TRADE_INSERT_BATCH`) into a separate `backtestTrades` collection.
5. **Paginated Trades API:** Added a paginated route `GET /api/v1/backtest/:id/trades` on the Node server and a corresponding `useBacktestTrades` TanStack Query hook on the client.

**Alternatives considered:**
- Keeping trades inline and increasing MongoDB's limit (not possible, 16MB is a hard MongoDB BSON limit).
- Truncating trade logs (unacceptable UX; users need full trade logs).
- Retaining synchronous cancel polling at a lower frequency (still blocks hot loop, asyncio pub/sub is much cleaner).

**Reason:**
Large backtests (e.g. 1-minute candles over multiple years with thousands of trades) quickly exceeded MongoDB's 16MB document size limit when storing raw equity curves and full trade log arrays, causing writes to fail. Additionally, synchronous Redis lookups and loop-based statistics severely slowed down execution.

**Impact:**
- `engine/services/backtest_runner.py` uses `_downsample`, bulk-inserts to `backtestTrades` collection, and uses vectorized NumPy calculations.
- `server/src/models/BacktestTrade.js` defines the new trade collection schema.
- `server/src/controllers/backtest.controller.js` implements the paginated trades endpoint.
- Client queries trades dynamically via `useBacktestTrades` hook and displays them in a paginated list.
- Backtest execution time is significantly reduced, and documents are safe from BSON limit crashes.

---

## 2026-06-03 — Binance Futures Public WebSockets Stream (Phase 5.3)

**Decision:** Implement public Binance USD-M Futures WebSockets feed in the client using a single WebSocket singleton manager (`client/src/lib/binanceWS.js`) and a custom hook (`client/src/hooks/useBinanceWS.js`) supporting multiple dynamic callbacks.
- **WebSocket URL:** `wss://fstream.binance.com/ws`
- **Stream parameters:** `<symbol_lower>@ticker`, `<symbol_lower>@trade`, `<symbol_lower>@depth20@100ms`, and `<symbol_lower>@kline_1m`.
- **Logic Isolation:** Components subscribe only to the data streams they need (e.g., `TickerBar` for ticker, `OrderBook` for depth, `RecentTrades` for trade, and `ChartContainer` for kline). This isolates re-renders to the affected component.
- **Chart Performance Optimization:** The `ChartContainer` updates the lightweight-charts series imperatively using `seriesRef.current.update(kline)` within the WebSocket callback, completely bypassing React state re-renders and preventing chart re-initialization.

**Alternatives considered:**
- Creating a separate WebSocket connection for each hook call (inefficient, hits rate limits, poor performance).
- Storing WebSocket data in top-level state in `Trade.jsx` (causes the entire terminal page, form inputs, and sub-components to re-render on every tick, causing significant rendering lag).

**Reason:**
A single WebSocket connection minimizes network usage and respects exchange rate limits. Decoupling stream states into separate sub-components keeps the app highly responsive even under high-frequency tick data (like order book depth and trades). Updating the chart imperatively prevents visual glitching and CPU overhead from chart reconstruction.

**Impact:**
- Create [binanceWS.js](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/lib/binanceWS.js) (WebSocket manager).
- Create [useBinanceWS.js](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/hooks/useBinanceWS.js).
- Update [Trade.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/pages/Trade.jsx) to split into smaller, stream-subscribed sub-components (`TickerBar`, `OrderBook`, `RecentTrades`, `ChartContainer`) and wire up the real-time feeds.

---

## 2026-06-03 — Binance Futures Private API Client Integration (Phase 5.4)

**Decision:** Implement private Binance USD-M Futures account and positions fetching using Express proxy routes and Python engine signed REST calls.
- **Credential Storage & Transit:** API credentials are retrieved from the singleton MongoDB `Settings` document (which exists as `_id: "global"`) by the Node Express server. For proxy requests, Express forwards credentials to the Python FastAPI engine via custom headers (`X-Binance-API-Key` and `X-Binance-API-Secret`).
- **Signature & Security:** The Python engine creates authenticated requests dynamically by generating an HMAC-SHA256 signature using the secret key, appending the timestamp and recvWindow, and passing `X-MBX-APIKEY` in the headers.
- **REST Endpoints:**
  - `GET /live/account` proxies to `GET /fapi/v1/account` (Binance Testnet)
  - `GET /live/positions` proxies to `GET /fapi/v1/positionRisk` (Binance Testnet)
  - `GET /live/open-orders` proxies to `GET /fapi/v1/openOrders` (Binance Testnet)
- **UI Integration:** The client `/trade` bottom panel tabs (Positions, Open Orders, Order History, Assets) will load data via corresponding TanStack Query hooks defined in `client/src/hooks/useLiveTrading.js`.

**Alternatives considered:**
- Storing keys in the Python engine's environment variables (fails the requirement of user settings management in MongoDB and dynamic multi-key or key-rotation support).
- Passing credentials in GET request body (violates REST standard; GET bodies are ignored by many proxy networks/servers).
- Calling Binance directly from the frontend React client (violates security boundaries, exposes keys to client memory, and fails CORS policies).

**Reason:**
Forwarding keys via Express-to-Engine headers keeps them isolated inside the server-to-engine backend network. The Python engine executes the HMAC-SHA256 signing logic natively using standard hashlib and hmac, keeping standard REST paradigms simple without requiring state management or external session storage.

**Impact:**
- Create `engine/services/binance_testnet.py` to hold helper functions for signed REST queries.
- Add routes in `engine/routers/trade.py`: `GET /account`, `GET /positions`, `GET /open-orders` extracting key and secret from headers.
- Add routes in Express server: `GET /api/v1/trade/account`, `GET /api/v1/trade/positions`, `GET /api/v1/trade/open-orders` fetching key/secret from settings and calling the engine.
- Create `client/src/hooks/useTrade.js` containing TanStack hooks `useTradeAccount()`, `useTradePositions()`, `useTradeOpenOrders()`.
- Update `client/src/pages/Trade.jsx` (specifically `BottomPanel` tabs) to render actual fetched states and handle loading/empty skeletons.

---

## 2026-06-03 — Binance Futures Margin & Leverage Controls (Phase 5.5)

**Decision:** Implement margin mode and leverage adjustments using signed Binance Futures REST calls via the Express-to-Engine proxy chain.
- **REST Endpoints:**
  - `POST /api/v1/trade/leverage`: Takes `{ symbol, leverage }`, calls FastAPI engine `POST /trade/leverage` with credentials in headers.
  - `POST /api/v1/trade/margin-type`: Takes `{ symbol, marginType }`, calls FastAPI engine `POST /trade/margin-type` with credentials in headers.
- **FastAPI Params:** The engine transforms the application symbol (`BTC-USDT`) to Binance format (`BTCUSDT`), and maps margin types to Binance strings (`"ISOLATED"` or `"CROSSED"`).
- **Symbol Configuration Hook:** Update the engine `GET /trade/positions` to accept an optional `symbol` query param. This allows the client to fetch leverage and margin type for `BTC-USDT` even if no active position exists.
- **UI State & Controls:** Wire the `OrderForm` Cross/Isolated toggle and Leverage selection button to `useMutation` hooks in `client/src/hooks/useTrade.js`. Successful mutation invalidates the active symbol configuration query and account details query to update the UI instantly.

**Alternatives considered:**
- Hardcoding leverage and margin mode in client (does not work, will cause order execution mismatches if Binance exchange settings differ).
- Polling positions to sync leverage (inefficient; using direct queries by symbol is faster and keeps state accurate).

**Reason:**
Directly integrating these adjustments into the `OrderForm` reflects real exchange settings. Querying by symbol allows accurate rendering of margin/leverage options even with zero balances or no open trades.

**Impact:**
- Update `engine/routers/trade.py` to support `symbol` query parameter in `GET /positions`, and add `POST /leverage` and `POST /margin-type` endpoints.
- Update `server/src/controllers/trade.controller.js` and `server/src/routes/trade.routes.js` to add `changeLeverage` and `changeMarginType` handlers.
- Update `client/src/hooks/useTrade.js` to add `useTradeSymbolConfig(symbol)`, `useChangeLeverage()`, and `useChangeMarginType()` hooks.
- Update `client/src/pages/Trade.jsx` (`OrderForm` component) to query symbol configurations and wire up toggle/button mutations with optimistic invalidation.

---

## 2026-06-03 — Binance Futures Order Placement & Cancellation (Phase 5.6)

**Decision:** Implement manual Limit and Market order execution and order cancellation on the Binance Testnet via the Express-to-Engine proxy chain.
- **REST Endpoints:**
  - `POST /api/v1/trade/order`: Takes `{ symbol, side, type, quantity, price }`, calls engine `POST /trade/order`.
  - `DELETE /api/v1/trade/order`: Takes `?symbol&orderId` as query params, calls engine `DELETE /trade/order`.
- **FastAPI Params:** The engine transforms `BTC-USDT` to `BTCUSDT`. It formats price and quantity parameters as required by the Binance REST API, passing them to the signed request client.
- **UI State & Controls:**
  - In `OrderForm`, the "Buy / Long" and "Sell / Short" buttons trigger the `usePlaceOrder` mutation. All inputs are disabled and a loading state is shown during execution.
  - In `OpenOrdersTable`, the "Cancel" action button triggers the `useCancelOrder` mutation.
  - Success events invalidate active orders, positions, and account details queries to reconcile the terminal state.
- **Error Handling:** Order placement/cancellation errors are caught and rendered as inline alert banners inside `OrderForm` or `BottomPanel`, respecting our `client/CLAUDE.md` rules against thread-blocking `alert()` calls.

**Alternatives considered:**
- Using CCXT library calls for order placement (avoided to maintain uniformity with the manual signing REST service built in previous phases).

**Reason:**
Direct REST proxying with manual signing keeps the codebase compact, removes dependencies on engine-level state, and ensures complete control over parameters (e.g. `timeInForce`).

**Impact:**
- Update `engine/routers/trade.py` to add `POST /order` and `DELETE /order` endpoints.
- Update `server/src/controllers/trade.controller.js` and `server/src/routes/trade.routes.js` to add `placeOrder` and `cancelOrder` proxy handlers.
- Update `client/src/hooks/useTrade.js` to export `usePlaceOrder()` and `useCancelOrder()` mutations.
- Update `client/src/pages/Trade.jsx` (`OrderForm` and `OpenOrdersTable`) to wire up actions and show loader/error states.

---

## 2026-06-03 — Real-Time Sync & State Reconciliation (Phase 5.7)

**Decision:** Implement polling reconciliation (4000ms refetch interval) for private API data queries (`useTradeAccount`, `useTradePositions`, `useTradeOpenOrders`) to keep terminal balances, open orders, and positions synchronized with the Binance exchange.
- **Hook Configuration:** Modify `client/src/hooks/useTrade.js` query hooks to accept an optional TanStack Query options object, forwarding options (including `refetchInterval`) directly to `useQuery`.
- **Active Polling:** The `/trade` page will pass `{ refetchInterval: 4000 }` to these hooks. When the page unmounts or the tab loses focus, TanStack Query automatically suspends polling, preventing network waste.
- **Immediate Mutation Sync:** Instant synchronization remains driven by invalidating queries (`queryClient.invalidateQueries`) inside the mutation success handlers for `usePlaceOrder`, `useCancelOrder`, `useChangeLeverage`, and `useChangeMarginType`.

**Alternatives considered:**
- Building a private WebSocket User Data Stream (Binance `/fapi/v1/listenKey`) (deferred to a later pass due to the complexity of managing listen key keepalives and relaying private frames via server Socket.IO, whereas 4s HTTP polling is lightweight and highly robust for a local single-user terminal).

**Reason:**
A 4-second polling loop is simple, reliable, and keeps the terminal's margin ratios and position unrealized P&L accurate even under rapid market fluctuations or external fills. Integrating the options object into our hooks keeps them highly customizable.

**Impact:**
- Modify `client/src/hooks/useTrade.js` to accept `options` on query hooks.
- Modify `client/src/pages/Trade.jsx` to pass `refetchInterval: 4000` to the hooks in `BottomPanel`.

---

## 2026-06-03 — WebSocket Depth Payload Key Normalization

**Decision:** Normalize depth payloads inside the client-side `onDepth` callback to handle both partial depth snapshots (`asks`/`bids`) and diff updates (`a`/`b`) fallback properties.
- **Payload Fallback:** Retrieve the asks array using `data.asks || data.a || []` and the bids array using `data.bids || data.b || []`.
- **Logic Isolation:** Confine payload mapping inside the `OrderBook` component callback directly.

**Alternatives considered:**
- Creating different callbacks for different levels of depth streams (redundant, adds complexity to stream routing).
- Handling normalization on the backend (not possible for direct-to-exchange public WebSockets).

**Reason:**
Binance USD-M Futures partial depth streams (like `@depth20@100ms`) return structured keys `"asks"` and `"bids"`, whereas diff updates or other depth streams use `"a"` and `"b"`. Checking only `"a"` or `"b"` throws a `TypeError: Cannot read properties of undefined (reading 'slice')` when a partial depth message is received, which crashes and unmounts the entire React app. Normalizing via a fallback array ensures the client handles both formats gracefully.

**Impact:**
- Modify `onDepth` inside `client/src/pages/Trade.jsx` to parse fallback keys.
- Update `client/CLAUDE.md` to establish a new rule for WebSocket depth subscription parsing.

---

## 2026-06-03 — Server-Side Public Market Data Proxy (CORS Fix)

**Decision:** Proxy client requests for historical public candle data (`klines`) through Express and Python FastAPI instead of fetching directly from Binance.
**Alternatives considered:**
- Adding custom HTTP headers in frontend requests (browser-based requests cannot bypass the remote server's Access-Control-Allow-Origin header).
- Querying cached data from TimescaleDB directly (local cache may be incomplete or outdated for the chart's real-time initialization needs).
**Reason:** Binance public REST APIs block CORS requests from frontend browser apps hosted on localhost, preventing TradingView chart initialization.
**Impact:**
- Add backend route `GET /api/v1/trade/klines` in Express.
- Add internal proxy route `GET /trade/klines` in Python FastAPI.
- Client component queries local endpoint `/api/v1/trade/klines?symbol=...&interval=...&limit=...` without origin restrictions.

---

## 2026-06-03 — Margin Mode and Leverage Controls Configuration

**Decision:** Implement leverage modification and margin type adjustment proxy routes from client to FastAPI engine via Express.
**Alternatives considered:**
- Direct ccxt calls in FastAPI router (avoided to maintain consistent design with existing signed request service helper).
- Managing leverage state in React frontend memory (rejected, leverage settings are account-wide exchange parameters and must be synced with the broker).
**Reason:** Users require terminal adjustments of margin risk parameters before manual order placements.
**Impact:**
- Add API endpoints for changing leverage: `POST /api/v1/trade/leverage` (Express) and `POST /trade/leverage` (FastAPI).
- Add API endpoints for changing margin mode: `POST /api/v1/trade/margin-type` (Express) and `POST /trade/margin-type` (FastAPI).
- Support fetching a single symbol position risk layout (using `?symbol=BTC-USDT`) in `GET /api/v1/trade/positions` to parse margin/leverage state when no active positions are held.

---

## 2026-06-03 — Phase 5 fixes: WebSocket depth key fallback, candle proxy, and backend route additions

### a) WebSocket depth payload: dual-key fallback

**Decision:** The `onDepth` callback in the `OrderBook` component normalises depth data by checking both key shapes that Binance sends:
- Partial depth snapshots (`@depth20@100ms`) use `"asks"` / `"bids"`.
- Diff updates and some other depth streams use `"a"` / `"b"`.

The fallback pattern is: `data.asks || data.a || []` for asks and `data.bids || data.b || []` for bids. This is enforced in `client/CLAUDE.md` under "WebSocket depth parsing".

**Reason:** Checking only `"a"` / `"b"` causes `TypeError: Cannot read properties of undefined (reading 'slice')` when a partial depth snapshot arrives, crashing the React tree. The fallback handles both shapes without any stream-routing complexity.
**Impact:** `onDepth` in `client/src/pages/Trade.jsx` updated. `client/CLAUDE.md` updated with the rule.

---

### b) Candle data fetched via Express proxy (CORS fix)

**Decision:** The client never fetches kline/candle data directly from `https://fapi.binance.com`. All candle requests go through `GET /api/v1/trade/klines`, which Express proxies to `GET /trade/klines` on the FastAPI engine, which in turn calls the Binance REST API server-side.

**Reason:** Browsers block cross-origin requests to `fapi.binance.com` from `localhost` origins. The proxy eliminates the CORS restriction entirely because the request originates from the Node server, not the browser.
**Impact:** `client/src/pages/Trade.jsx` (`ChartContainer`) queries `GET /api/v1/trade/klines?symbol=...&interval=...&limit=...`. Direct Binance REST calls from client code are forbidden. Rule added to `client/CLAUDE.md`.

---

### c) Phase 5.4–5.7 backend routes added

**Decision:** The following routes were added to complete Phase 5 live trading functionality:

**FastAPI engine (`engine/routers/trade.py`):**
- `GET /trade/account` — fetch account balances (credentials via `X-Binance-API-Key` / `X-Binance-API-Secret` headers)
- `GET /trade/positions` — fetch position risk; optional `?symbol=` filter
- `GET /trade/open-orders` — fetch open orders
- `POST /trade/leverage` — set leverage for a symbol
- `POST /trade/margin-type` — set margin mode (`ISOLATED` / `CROSSED`)
- `POST /trade/order` — place limit or market order
- `DELETE /trade/order` — cancel order by `symbol` + `orderId`
- `GET /trade/klines` — fetch public historical klines from Binance (CORS proxy)

**Express server (`server/src/routes/trade.routes.js` + `server/src/controllers/trade.controller.js`):**
- Each engine route above is mirrored at `/api/v1/trade/*`
- Express reads `binanceApiKey` and `binanceApiSecret` from the singleton MongoDB `Settings` document and forwards them as `X-Binance-API-Key` / `X-Binance-API-Secret` headers to the engine

**Reason:** All eight route pairs are required to drive the Trade terminal UI: account/position/order display (phases 5.4–5.5), order placement/cancellation (phase 5.6), and candle chart initialisation (CORS fix).
**Impact:** See `engine/routers/trade.py`, `engine/services/binance_testnet.py`, `server/src/controllers/trade.controller.js`, `server/src/routes/trade.routes.js`. Full request/response shapes documented in `docs/API_CONTRACTS.md`.

---

## 2026-06-03 — Isolated margin only (cross margin removed)

**Decision:** The platform supports **ISOLATED margin only**. Cross margin is no longer selectable anywhere. The `POST /trade/margin-type` endpoint chain (client → server → engine) is kept, but the engine hard-locks the applied margin type to `ISOLATED` regardless of the request body. The client margin-mode control no longer offers a "Cross" option.
**Alternatives considered:**
- Removing the margin-type endpoint entirely and auto-setting ISOLATED before each order (more files touched; removes a working endpoint).
- Keeping the Cross/Isolated toggle but defaulting to Isolated (still permits cross — rejected).
**Reason:** Single-user platform with a simpler, more predictable risk model. Isolated margin caps risk per position and avoids account-wide liquidation cascades. Keeping the endpoint (rather than deleting it) preserves the existing proxy chain and the symbol-config display, minimising blast radius.
**Impact:**
- `engine/routers/trade.py` `set_margin_type` always sends `marginType=ISOLATED` to Binance; the `CROSS→CROSSED` mapping is removed. Binance error `-4046` ("No need to change margin type", i.e. already isolated) is treated as success rather than raised as a 400.
- `client/src/pages/Trade.jsx` margin-mode control renders only `Isolated` (no `Cross` button); `activeMarginType` display no longer shows "Cross".
- The `marginType` request field is retained for backward compatibility but is ignored by the engine.
- `docs/API_CONTRACTS.md` updated: `POST /trade/margin-type` and `POST /api/v1/trade/margin-type` document that the engine always applies ISOLATED and that `-4046` is swallowed as success.
