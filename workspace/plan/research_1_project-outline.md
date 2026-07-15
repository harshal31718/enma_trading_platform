# 01 — Project Outline & Core Architecture Map

**Shelf:** research · **Date:** 2026-07-14 · **Formerly:** `refinements/01_project_outline.md` (series mapping in `0_plans.md`)
**Date:** 2026-07-14 · **Confidence tags:** [Certain] verified in code · [Likely] strong inference
**Relationship to existing planning:** This outline is the descriptive baseline for the series. The
prescriptive audit already exists at `workspace/plan/audit_1_system-design.md`; remediation plans at
`workspace/plan/2_…` through `8_…`. This file does not restate issues — it maps what exists.

---

## 1. Purpose

[Certain] Enma is a self-hosted, multi-user, full-stack **algorithmic trading platform** for
Binance USDT-M futures: write Python strategies, backtest against historical OHLCV, run live
algo bot sessions (Binance **Testnet** only), and manually trade futures. Fully containerized
via Docker Compose (dev + prod variants).

## 2. Language Stack & Topology

| Service | Stack | Role | Size signal |
|---------|-------|------|-------------|
| `client/` | React 18, Vite 5, Tailwind 3, Zustand, TanStack Query, Socket.IO client, Radix UI, lightweight-charts, recharts | Trading UI (7 pages + admin) | Largest page `Trade.jsx` ≈ 1,760 lines |
| `server/` | Node 20, Express 4, Socket.IO 4, BullMQ 5, Mongoose 7, Passport (Google OAuth), ioredis | API gateway, auth, job queue, realtime fan-out | 12 controllers, 11 models, no service layer |
| `engine/` | Python 3.11, FastAPI, httpx, TA-Lib (+ pandas-ta fallback), asyncpg, motor, websockets | All financial computation: backtest, live execution, indicators, Binance I/O | ~16,700 LoC; largest module `live_bot_manager.py` = 2,002 lines |
| MongoDB | via Mongoose (Node) + motor (engine) | Metadata: users, strategies, backtest results/trades, live sessions, settings, trade records | 11 collections |
| TimescaleDB (pg16) | via asyncpg (engine only) | `candles` hypertable — OHLCV exclusively | Permanent cache, idempotent inserts |
| Redis 7 | BullMQ queues, pub/sub, cache | Job queue + messaging | No auth configured |

**Data flow:** client ↔ server (REST `/api/v1/*` + Socket.IO rooms) ↔ engine (HTTP, `X-API-Key`).
Engine → server callbacks via unauthenticated `/internal/*` PATCH endpoints. Client additionally
opens a **direct Binance public WebSocket** for market data (ticker/klines/depth). Only the engine
calls Binance REST/signed endpoints (documented invariant; see `audit_1_system-design.md` SYS-4 for drift).

## 3. Core Components (foundational blocks)

### 3.1 Authentication & access control — `server/src/config/passport.js`, `middleware/auth.middleware.js`
[Certain] Google OAuth 2.0 (Passport, sessionless) → JWT in `httpOnly` cookie (`enma_jwt`, 7-day,
`sameSite: lax`). Open login (no whitelist). `verifyJWT` globally on `/api/v1/*`, reloads user from
Mongo per request. Roles: `user`/`admin` (`ADMIN_EMAIL` auto-promoted). Per-feature gate:
`requireAlgoAccess` on algo-session start actions only (`User.algoAccess.status` state machine:
`none → requested → granted`, admin-managed). Per-user data scoping via `userId` on all mutable
models; strategies deliberately global (no `userId`).

### 3.2 Persistence layer
- [Certain] **MongoDB** — 11 Mongoose models (`User`, `Strategy`, `Settings`, `BacktestResult`,
  `BacktestTrade`, `BacktestLeverageScenario`, `LiveSession`, `TradeOrder`, `TradeExecution`,
  `TradeTransaction`, `TradeRecord`). Ownership rule: engine is sole writer of
  `backtestResults`/`backtestTrades`/`tradeRecords` (via motor); Node writes the rest.
- [Certain] **TimescaleDB** — single `candles` hypertable, engine-only access via asyncpg;
  candles permanent, `INSERT … ON CONFLICT DO NOTHING`.
- [Certain] **Redis** — BullMQ backtest queue (`server/src/services/backtestQueue.js` +
  `workers/backtest.worker.js`), Socket.IO emission support, cache.

### 3.3 API gateway (Node) — `server/src/`
[Certain] Routes → controllers directly (no service layer). 12 route groups: auth, admin, algo,
backtest, candle, dashboard, orderHistory, risk, settings, strategy, trade, internal. Cross-cutting:
`helmet`, CORS, `express-rate-limit` (10k/15min), `morgan`, central `errorHandler`,
`ApiError`/`ApiResponse` envelopes. `engineClient.js` = axios instance to engine (1-hour timeout).
`symbolLock.js` = mutual exclusion between bot-held and manually-traded symbols.
`reconciliation.js` = startup sweep of orphaned sessions.

### 3.4 Computation engine (Python) — `engine/`
[Certain] FastAPI app (`main.py`) with 9 routers (algo, backtest, candles, dashboard,
leverage_sensitivity, optimize, risk, strategies, trade). Static `X-API-Key` auth. Key subsystems
detailed in §4–5.

### 3.5 Realtime layer
[Certain] Three channels:
1. **Socket.IO** (server→client), per-user rooms (`user:<id>`), JWT-authenticated handshake —
   session status, logs, notifications.
2. **Direct Binance public WS** (client→Binance) — ticker strip, live klines, depth20@100ms,
   recent trades. No server load by design.
3. **Binance User Data Streams** (engine) — two services: `user_data_stream.py` (algo fill
   detection) and `manual_trade_stream.py` (Trade page order/account push; replaced
   high-frequency REST polling, REST demoted to 90/30/60s safety net).

### 3.6 UI framework — `client/src/`
[Certain] Pages (`pages/`) + feature folders (`features/backtest|dashboard|strategies`) +
15 domain hooks (`hooks/useX.js`) + shared UI kit (`components/ui`, Radix-based Badge/Card/Button/
Dialog). State: Zustand (UI) + TanStack Query (server state) — Redux banned. Dark theme,
`emerald-400`/`red-400` P&L invariant. Client tests configured (vitest, RTL, msw, puppeteer in
devDependencies) but **zero test files exist** [Certain].

## 4. Important Features (user/system-facing)

| Feature | Entry points | Notes |
|---------|-------------|-------|
| **Backtesting** | `engine/services/backtest_runner.py` (1,201 ln), BullMQ job via Node | Unified five-model pipeline shared with live; isolated-margin futures realism; multi-symbol shared wallet; TWAP/VWAP/Iceberg slicing; tabbed report UI w/ calendar + buy-&-hold overlay. Spec: `docs/features/backtest-pipeline/SPEC.md` |
| **Live algo trading (bots)** | `engine/core/live_bot_manager.py` (2,002 ln) | Multi-symbol candle-driven sessions on Testnet, same pipeline as backtest; exchange-state reconciliation; OCO/OUO SL/TP safety nets; dynamic pairlist; per-symbol leverage clamp; Chaos Mode multi-strategy stress runs |
| **Manual trading** | `Trade.jsx`, `engine/routers/trade.py` (863 ln) | Market/limit + TP/SL, leverage/margin-type, positions, orderbook, klines chart, order/execution/transaction history, symbol locks |
| **Strategy management** | `engine/routers/strategies.py`, `strategy_seeder.py` | 5 seeded strategies (AdaptiveTrend, BestSupertrend, MicroMacroRSIDivergence, MicroScalper, MultiDivergence); live code editing → validated + hot-reloaded (`importlib.reload`) — global/shared |
| **Parameter optimization** | `engine/services/optimizer.py` (391 ln) | Grid search over typed self-validating strategy params |
| **Risk Intelligence Dashboard** | `RiskDashboard.jsx`, `engine/routers/risk.py`, `monte_carlo.py`, `leverage_sensitivity_runner.py` | Portfolio VaR/CVaR + correlation heatmap; hierarchical risk-limit overrides (global→strategy→symbol); leverage scenarios + Monte Carlo |
| **Candle management** | `engine/services/candle_manager.py`, `candle_importer.py` | `ensure_candles_available()` single entry point; Binance prod REST, 1,000-candle batches, idempotent |
| **Dashboard** | `Dashboard.jsx`, `engine/routers/dashboard.py` | KPI strip, strategy leaderboard, recent runs, testnet+mainnet(read-only) balances, ticker strip |
| **Order history (trade recorder)** | `engine/services/trade_recorder.py` → Mongo `tradeRecords` | Every completed round-trip; engine-write/server-read |
| **Admin panel** | `AdminPanel.jsx`, `admin.controller.js` | User table, algo-access grant/revoke |
| **Per-user settings & credentials** | `Settings` model, `utils/encryption.js` | AES-256-encrypted Binance keys per user, verified on save; exchange-wide defaults (fees, risk model, slippage, funding) as variables |

## 5. Critical Sub-parts (algorithms & utilities that drive the features)

### 5.1 Five-model execution pipeline — `engine/core/models/` + `pipeline.py` + `kernel.py`
[Certain] The architectural heart, shared by backtest and live: **Risk** (`risk.py`, 403 ln —
`AtrBracketRiskModel` w/ optional trailing/breakeven/ATR-percentile veto, cost gate
`min_edge_mult`, portfolio exposure cap), **Portfolio**, **Cost**, **Execution** + **ExecAlgo**
(TWAP/VWAP/Iceberg slicing), **Protections**. `ExecutionKernel` (482 ln) routes signals through
the pipeline identically in both modes (a `LiveAdapter` bridges to the live manager). Each seeded
strategy is bound to a specific Risk/Portfolio pair.

### 5.2 Strategy contract — `engine/core/strategy.py` (557 ln), `params.py` (322 ln)
[Certain] `BaseStrategy` with `prepare()`/`before()` split: indicators precomputed once
(vectorized) in `prepare()`, `before()` is a pure index lookup — replaced a former O(N²)
per-candle recompute. Signals travel as mutable attributes (`strategy.buy = (qty, price)` etc.).
Typed, self-validating parameters (reject, don't clamp). DCA / position adjustment + entry/exit
tagging shared across backtest and live.

### 5.3 Indicator provider architecture — `engine/indicators/`
[Certain] Pluggable backend behind convenience functions (`import engine.indicators as ta`):
TA-Lib default, pandas-ta pure-Python fallback, env-switchable
(`ENMA_INDICATOR_LIBRARY`, auto-fallback). 13 indicators incl. library-agnostic swing-pivot
detectors. `sequential=False/True` dual return modes; NaN-safe SMA warmup.

### 5.4 Exchange I/O — `engine/services/binance_testnet.py`, `utils/rate_limiter.py`
[Certain] Native HMAC-signed REST via httpx (**ccxt explicitly rejected** — DECISIONS.md).
Warmup/HTF candles come from **mainnet** REST while execution + kline WS are testnet.
`OrderRateLimiter` gates entries only. Per-symbol WS connections (not combined streams).

### 5.5 Reconciliation & safety nets
[Certain] `_reconcile_exchange_state` in the live manager (exchange truth vs local dicts,
2–3 signed calls/symbol/candle); OCO groups share `oco_<uuid>_` clientOrderId prefix, dual
notifications on linked fills/cancels; Node-side startup `reconciliation.js`; symbol lock service.

### 5.6 Financial math & utilities
[Certain] `utils/risk_math.py` (risk-% → quantity: `(equity·riskPct)/(entry−stop)`),
`utils/timeframes.py` (single conversion authority), `utils/symbols.py` (662 ln — filters,
precision, pairlist support), `services/metrics.py` (580 ln — Sharpe, Sortino, expectancy,
profit factor, drawdown), `services/curves.py` + `fill_model.py` (equity curves, fill simulation),
`services/pairlist.py` (dynamic pairlist pipeline). Money is **float** throughout (flagged as
ENG-11 in `audit_1_system-design.md`).

### 5.7 Verification machinery
[Certain] `engine/scripts/golden_master.py` — byte-equivalence harness for pipeline refactors
(mandated by CLAUDE.md Rule C); 11 engine test modules (boundary suite, exec-algo slicing,
metrics, pairlist, reconcile, risk math, parity). No CI; no server/client tests.

### 5.8 AI-governance layer (meta, but load-bearing for this repo)
[Certain] `AGENTS.md` (cross-tool entry), `CLAUDE.md` + per-service variants,
`.claude/GOVERNANCE.md`, `workspace/docs/` (core/state/features SPECs), `workspace/plan/`
(numbered plan catalog + tracker + `audit_1_system-design.md` audit), skills (`/add-indicator`, `/add-strategy`,
`/sync-spec`), `drift-reviewer` subagent, `handoff.md` protocol.

## 6. Deployment & environment

[Certain] `docker-compose.yml` (dev: hot-reload watch mode, ports 5173/5000/8000/5432/6379
published) and `docker-compose.prod.yml`. Single shared `.env` injected into **all** containers
(client included). TA-Lib compiled in-container. Healthchecks on all services (engine `/health`
returns ok even with dead DB deps — ENG-13). `keys/` dir holds a testnet env file on disk.

## 7. Known-state summary (pointers, not restatement)

- **Implemented:** everything in §4 (authoritative list: `docs/state/CURRENT_STATE.md`).
- **Deliberately absent:** mainnet order routing (read-only balances only), multi-exchange,
  internal paper-trading sim (testnet *is* paper), Redux, ccxt.
- **Known debt (acknowledged in CURRENT_STATE.md):** estimated exit prices on exchange-sync
  closes; entry fee untracked in session PnL; unconfirmed `ORDER_TRADE_UPDATE` emission for
  conditional orders.
- **Full defect audit:** `workspace/plan/audit_1_system-design.md` (34 issues: SEC-1..10, ENG-1..18,
  SRV-1..5, CLI-1..3, SYS-1..7). Remediation sequencing: `0_tracker.md` (plans 2–8, P0–P3).

---

*Next: [`research_2_market-survey.md`](research_2_market-survey.md) — how industry-standard and top open-source systems
implement each §3–§5 component, with sources.*
