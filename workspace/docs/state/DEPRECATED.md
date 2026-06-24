# ENMA — Deprecated & Removed

Tracks systems, files, workflows, and approaches that have been removed from ENMA.

**Purpose:** Prevent AI agents from referencing, reconstructing, or re-implementing these systems.
If something appears here, it does not exist in the codebase and must not be referenced in any document.

---

## Removed Documentation Files

| File | Status | Why Removed | Replacement |
|------|--------|-------------|-------------|
| `workspace/docs/complete_plan.md` | Does not exist | Phase-based planning dropped early in development | `workspace/docs/state/CURRENT_STATE.md` |
| `workspace/docs/phases.md` | Does not exist | Same as above | `workspace/docs/state/CURRENT_STATE.md` |
| `workspace/docs/WORKFLOW.md` | Does not exist | Superseded by Workflow V2 | `AGENTS.md` (entry point; `BOOTSTRAP.md` was later folded into it) |
| `workspace/docs/ARCHITECTURE.md` | Moved | Reorganized to `workspace/docs/core/` | `workspace/docs/core/ARCHITECTURE.md` |
| `workspace/docs/DECISIONS.md` | Moved | Reorganized to `workspace/docs/core/` | `workspace/docs/core/DECISIONS.md` |
| `workspace/docs/API_CONTRACTS.md` | Moved | Reorganized to `workspace/docs/core/` | `workspace/docs/core/API_CONTRACTS.md` |
| `workspace/docs/binance-api.md` | Moved | Reorganized to `workspace/docs/core/` | `workspace/docs/core/binance-api.md` |

**Removed 2026-06-20:** three point-in-time reports — `ai_architecture_report.md`, `ai_infrastructure_audit.md`, `workflow_v2_stabilization_report.md` (all dated 2026-06-05) — were archived to `workspace/docs/archive/` on 2026-06-14, then **deleted** 2026-06-20 as fully superseded by `.claude/GOVERNANCE.md` and `AGENTS.md`. Do not reconstruct. The `workspace/docs/archive/` directory no longer exists; the sole archive root is now `workspace/archive/`.

---

## Removed Application Features

| System | Removed When | Why | Replacement |
|--------|-------------|-----|-------------|
| Candle import as separate BullMQ job | Mid-development | Unnecessary queue complexity | Auto-fetch inside backtest pipeline via `ensure_candles_available()` |
| `candle.worker.js` | Same | Part of candle import job removal | N/A |
| `candleQueue.js` (`bull:candles`) | Same | Part of candle import job removal | N/A |
| `CandleImport` MongoDB collection | Same | Candle fetch history not needed | N/A |
| `candleImports` MongoDB collection | Same | Same | N/A |
| "Import Candles" nav item | Mid-development | Candles auto-fetched before backtest | N/A |
| Sidebar navigation (`Sidebar.jsx`) | Mid-development | Replaced with horizontal top navbar | `Navbar.jsx` / `TopBar.jsx` |
| `useUIStore.js` (Zustand) | With sidebar removal | Tracked sidebar open/close state | N/A |
| `DataTable.jsx` | UI refactor | Never imported anywhere | N/A |
| `EmptyState.jsx` | UI refactor | Never imported anywhere | N/A |
| `StatusBadge.jsx` | UI refactor | Never imported anywhere | N/A |
| Root-level `StatCard.jsx` | UI refactor | Duplicate of `features/dashboard/StatCard.jsx` | `features/dashboard/StatCard.jsx` |
| `importCandles` controller method | With candle import job removal | N/A | N/A |
| `getAvailable` controller method | With candle import job removal | N/A | N/A |
| `useAvailableImports()` hook | With candle import job removal | N/A | N/A |
| `useImportCandles()` hook | With candle import job removal | N/A | N/A |

---

## Removed Strategies

| Strategy | Removed When | Why | Replacement |
|----------|-------------|-----|-------------|
| `SimpleEMACross` | 2026-06-14 | Removed in full — folder, seeder entry, UI type map, and MongoDB document all deleted | N/A |
| `RSIReversion` | 2026-06-14 | Same — removed in full | N/A |
| `DonchianBreakout` | 2026-06-14 | Same — removed in full (the `donchian` *indicator* in `engine/indicators/` is unrelated and remains) | N/A |

Seeded strategies are now 5: `MicroScalper`, `AdaptiveTrend`, `BestSupertrend`, `MicroMacroRSIDivergence`, `MultiDivergence`.

---

## Purged Run History

| Data | When | Why |
|------|------|-----|
| All `backtestResults` + `backtestTrades` | 2026-06-14 | User-requested wipe of backtest run history (engine-owned collections cleared) |
| All `liveSessions` (bot run history) | 2026-06-14 | User-requested wipe of live bot run history |

Candles in TimescaleDB are permanent and were **not** touched.

---

## Removed Engine Internal Modules

| Module | Removed When | Why | Replacement |
|--------|-------------|-----|-------------|
| `engine/core/backtest.py` | Engine refactor | Extracted to a dedicated service layer | `engine/services/backtest_runner.py` |
| `engine/core/order.py` | Engine refactor | Order logic absorbed into `position.py` and `backtest_runner.py` | N/A |
| `engine/core/exchange.py` | Engine refactor | "Legacy, not used" per old docs; httpx + binance_testnet.py replaced it | `engine/services/binance_testnet.py` |
| `engine/services/result_store.py` | Engine refactor | Motor writes inlined into `backtest_runner.py` | N/A |
| `engine/services/candle_store.py` | Engine refactor | asyncpg access inlined into `candle_importer.py` and `candle_manager.py` | N/A |

## Removed Server Modules

| Module | Status | Why | Replacement |
|--------|--------|-----|-------------|
| `server/src/middleware/auth.js` | Never implemented | JWT auth middleware was planned but not built; auth routes not mounted | N/A — auth is deferred |
| `server/src/middleware/validate.js` | Never implemented | express-validator wrapper was planned but not built | Input validation inline in controllers |
| `server/src/middleware/rateLimiter.js` | Never implemented | Rate limiting is defined inline in `app.js` | `express-rate-limit` in `app.js` |
| `server/src/services/liveQueue.js` | Never implemented | Live bot sessions are managed directly by engine; no BullMQ queue needed | N/A |
| `server/src/workers/live.worker.js` | Never implemented | Same reason as liveQueue.js | N/A |

### Client Auth Scaffolding (removed 2026-06-22)

The orphaned client-side auth scaffolding (never wired to any login UI on this single-user platform) was deleted:

| Item | Status | Why | Replacement |
|------|--------|-----|-------------|
| `client/src/store/useAuthStore.js` | **Deleted** | Zustand auth store consumed by no login UI | N/A — single-user, no auth |
| `client/src/lib/axios.js` JWT interceptors | **Removed** | Request `Authorization: Bearer` injector + 401→`/login` redirect referenced the deleted store; no token ever issued | Plain axios instance (baseURL only) |
| `bcryptjs` dependency | **Removed** from `server/package.json` | No server code hashed passwords | N/A |
| `jsonwebtoken` dependency | **Removed** from `server/package.json` | No server code signed/verified JWTs | N/A |

Do not reintroduce these unless multi-user support is actually built (see `CURRENT_STATE.md` → Planned → Authentication).

---

## Removed Agent / Workflow Infrastructure

| Item | Removed When | Why | Replacement |
|------|-------------|-----|-------------|
| `workspace/docs/WORKFLOW.md` "chatname_app_work" model | Workflow V2 redesign (2026-06-05) | Stale naming, stale references to non-existent files | `AGENTS.md` (`BOOTSTRAP.md` was later folded into it) |
| `.claude/commands/add-exchange.md` | Workflow stabilization (2026-06-05) | Aspirational — no implementation exists; no workflow steps were valid | N/A — add only when Binance is no longer the only exchange |
| `.claude/commands/monte-carlo.md` | Workflow stabilization (2026-06-05) | Aspirational — `/optimize` endpoint not implemented; referenced non-existent "Phase 6" | N/A — create when optimization is actually built |
| `.claude/AGENTS.md` | Clean up (2026-06-13) | Removed the theoretical multi-agent model (Claude Code, Brain, PromptGeneratorPipeline, WarmUpExecutor) and subagents (client-dev, engine-dev, reviewer) | Focus exclusively on Claude Code as a single agent (`.claude/BOOTSTRAP.md`) |
| `.claude/agents/` | Clean up (2026-06-13) | Same as above | N/A |

> **Update (2026-06-14): `.claude/agents/` reinstated.** Three focused, single-purpose Claude Code subagents were added — `drift-reviewer`, `doc-syncer`, `spec-explorer`. This is **not** a return to the removed theoretical model (Brain / PromptGeneratorPipeline / WarmUpExecutor); the abandoned `.claude/AGENTS.md` multi-agent doc stays removed. The root `AGENTS.md` (cross-tool entry pointer) is a different, unrelated file. _(Superseded 2026-06-20 — see next entry; only `drift-reviewer` survives.)_

> **Update (2026-06-20): `.claude/` consolidation — cut to 1 agent, 6 commands, 1 root doc.** Canonical inventory now lives in `.claude/GOVERNANCE.md` Part 2.
> - **Agents removed:** `doc-syncer` (merged into the `/sync-spec` command), `spec-explorer` (use the built-in Explore agent). Only `drift-reviewer` remains.
> - **Commands removed:** `review-drift` (→ `drift-reviewer` agent), `new-feature` (completion gate folded into `/sync-spec`), `setup` (merged into `/verify`), and the four domain primers `client-ui` / `server-api` / `engine-algo` / `binance-api` (redundant with the service `CLAUDE.md` files and `workspace/docs/core/binance-api.md`). Remaining: `add-strategy`, `add-indicator`, `add-endpoint`, `sync-spec`, `security-review`, `verify`.
> - **Root docs removed:** `.claude/BOOTSTRAP.md` (folded into `AGENTS.md`) and `.claude/AI_INFRASTRUCTURE.md` (folded into `.claude/GOVERNANCE.md` Part 2). `GOVERNANCE.md` is now the sole `.claude/` root doc.
> Do not reconstruct any of these — their content lives in the merge targets named above.

## Renamed Commands / Skills (historical — all four were later REMOVED)

> **These commands no longer exist.** They were renamed mid-development (below), then **removed
> entirely on 2026-06-20** (see "Removed Agent / Workflow Infrastructure" above — the four domain
> primers were redundant with the service `CLAUDE.md` files and `binance-api.md`). This table is kept
> only as rename history; do not treat the "New Command" column as invocable.

| Old Name | Renamed To (since removed) | Old Command | Renamed Command (since removed) |
|----------|----------|-------------|-------------|
| `client-ui-skill.md` | `client-ui.md` | `/client-ui-skill` | `/client-ui` |
| `server-api-skill.md` | `server-api.md` | `/server-api-skill` | `/server-api` |
| `engine-algo-skill.md` | `engine-algo.md` | `/engine-algo-skill` | `/engine-algo` |
| `binance-api-skill.md` | `binance-api.md` | `/binance-api-skill` | `/binance-api` |

---

## Rejected Approaches

| Approach | Why Rejected |
|----------|-------------|
| Redux for state management | Zustand + TanStack Query covers all needs without the boilerplate and complexity |
| CSS modules / styled-components | TailwindCSS utility-first handles all styling; no need for a second system |
| Internal paper trading simulation | Creates a confusing intermediate layer; Binance Testnet is the paper trading environment |
| MongoDB for candle storage | TimescaleDB hypertables are purpose-built and far more efficient for OHLCV time-series |
| `ccxt` for private order execution | Insufficient granular control; replaced by native hmac-signed REST calls via Engine |
| Bouncing tick data through Node server | Too much latency; client connects directly to Binance WebSocket for public market data |
| `pymongo` for MongoDB in engine | `motor` (async) is the correct choice for FastAPI; pymongo is synchronous |
