# Enma Trading Platform — Architecture

## Overview
Enma is a full-stack algorithmic trading platform for writing Python strategies, backtesting against Binance data, and running live trades.

## System Diagram

```
┌─────────────────────────────────────────────────────┐
│                   React Frontend                     │
└────────────────────┬────────────────────────────────┘
                     │ REST + WebSocket
┌────────────────────▼────────────────────────────────┐
│              Node.js API Gateway (Express)           │
└──────┬──────────────────────────┬───────────────────┘
       │ HTTP (FastAPI)           │ Mongoose
┌──────▼──────────┐    ┌──────────▼──────────────────┐
│  Python Engine  │    │         MongoDB              │
│  FastAPI server │    │  Metadata & Sessions         │
└──────┬──────────┘    └─────────────────────────────┘
       │               ┌─────────────────────────────┐
       │               │  TimescaleDB (PostgreSQL)   │
       │               │  OHLCV candle data          │
       │               └─────────────────────────────┘
       │               ┌─────────────────────────────┐
       │               │         Redis                │
       │               │  Job Queues & Pub/Sub        │
       ▼               └─────────────────────────────┘
  Binance API
```

## Services Topology

1. **Client (`client/`)**: React 18, Vite 5, TailwindCSS, Zustand, TanStack Query. Subscribes to Binance WS for live tick data, and local Node server for private account state.
2. **Server (`server/`)**: Node.js 20, Express, Socket.IO. Handles Auth, rate limiting, and acts as API gateway. Proxies trade logic to Engine.
3. **Engine (`engine/`)**: Python 3.11, FastAPI, TA-Lib, httpx. Performs all heavy computations, backtest simulation, vectorized metrics, and signs live Binance API requests natively via `services/binance_testnet.py`.

## Database Responsibilities

- **MongoDB (Node/Engine)**: `strategies` (global, no `userId`), `users`, `platformConfig`, `backtestResults`, `backtestTrades` (split from results to avoid BSON limits), `backtestLeverageScenarios`, `liveSessions`, `tradeOrders`, `tradeExecutions`, `tradeRecords`, `tradeTransactions`, `Settings`, `executionEvents` (append-only, engine-written fact log for live-trading state; Plan 5 Step 5.1 — see `CURRENT_STATE.md`).
- **TimescaleDB (Engine only)**: `candles` hypertable. Only Python engine reads/writes candles via asyncpg.
- **Redis (Node/Engine)**: BullMQ (`bull:backtest`), symbol locks (`server/src/services/symbolLock.js`), backtest cancel flags (`backtest:cancel:{jobId}`), progress streams (`progress:{jobId}`), live-metrics cache (`risk:live-metrics:{userId}`, 10s TTL).

## Binance Environment Model

There are exactly two Binance environments. Testnet is fully implemented (order placement + everything else); Mainnet is read-only today (key verification + balance display) — no mainnet order placement exists. See `workspace/docs/core/binance-api.md` for the full read-only mainnet surface.

| Mode | Base URL | Money | Status |
|---|---|---|---|
| **Testnet** | `https://demo-fapi.binance.com` | Fake | ✅ Active — all orders go here |
| **Mainnet** | `https://fapi.binance.com` | Real | 🟡 Read-only only — key verification + balance display (`X-Binance-Mode: mainnet` on `/trade/verify`, `/trade/account`); no order placement |

Rules:
- The **authenticated/signed** base URLs are defined **once** in `engine/services/binance_testnet.py` (`_BASE_URLS` dict). All signed Binance calls go through `send_signed_request` from that module — no other file defines the *signed* base.
- **Public-data** fetches (OHLCV klines, leverageBracket) intentionally hit **mainnet** `https://fapi.binance.com` directly per `workspace/docs/core/binance-api.md` §2, so that URL also appears literally in `engine/core/live_bot_manager.py`, `engine/routers/trade.py`, `engine/services/candle_importer.py`, and `engine/utils/symbols.py`. That is by design (testnet historical data is unreliable), not a duplication of the signed base.
- All authenticated Binance calls (Trade page, algo bot entries, exits, leverage) use `send_signed_request` from that module.
- `LiveSession.mode` is `"paper" | "live"`. All current sessions are `"paper"` (Binance Testnet).
- There is no Enma-internal paper trading simulation. "Paper trading" = Binance Testnet.
- When Mainnet is added: swap `BINANCE_TESTNET_BASE` for an environment variable and add a `mode` selector to the session start flow (setting the mode to `"live"`).

## Key Architectural Rules

1. **Multi-user, open login + per-feature gating**: Google OAuth + JWT cookie; login is open to anyone with a Google account (Plan 1, shipped 2026-07-14 — replaced the earlier invite-only model). `userId` scopes every mutable Mongoose model (`BacktestResult`, `BacktestTrade`, `BacktestLeverageScenario`, `LiveSession`, `Settings`, `TradeOrder`, `TradeExecution`, `TradeTransaction`, `TradeRecord`). `Strategy` stays global by design — no `userId`. Algo Trading start actions are gated per-user via `requireAlgoAccess` (admins bypass by role); Backtest, manual Trade, and Binance key entry are open to all authenticated users.
2. **Engine is the Writer**: Engine writes `backtestResults` and `backtestTrades` directly. Server does NOT double-write these.
3. **Keep-Alive**: Node uses `http.Agent` `keepAlive: true`, and Engine uses `httpx.AsyncClient` connection pooling.
4. **Local Dev**: Fully containerized with `docker-compose`. `node_modules` are in named volumes, TA-Lib is built inside the `engine` Dockerfile.
5. **Binance Testnet rate limits are weight-based and shared across ALL users, not per-user —
   mitigated via WebSocket push, not REST polling.** Binance's `REQUEST_WEIGHT` limit (2400/min,
   confirmed via
   [official docs](https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info))
   is enforced **per source IP** — since the engine proxies every signed call from the VPS's single
   outbound IP, this budget is shared across every concurrently active user, not allocated per user.
   The Trade page previously REST-polled account/positions/open-orders at 30s/3s/10s — `open-orders`
   alone cost ~480 weight/min per user (`GET /fapi/v1/openOrders`/`openAlgoOrders` cost weight 40
   each without a `symbol` param, vs. 1 with one, and neither call passed one), which at the shared
   2400/min budget meant roughly 4 concurrently active users exhausted it. **Fixed 2026-07-02**: the
   Trade page now uses a per-user Binance User Data Stream (`engine/services/manual_trade_stream.py`,
   reusing the `UserDataStreamManager` already built for live bots — F-020) for real-time
   order/account push over WebSocket, matching Binance's own recommended architecture. REST polling
   is now a long-interval (90s/30s/60s) safety net, not the primary source — see
   `workspace/docs/features/live-trading/SPEC.md`. Positions/account still need one real REST call on
   change (debounced ~2s) since `ACCOUNT_UPDATE` lacks `markPrice`/`liquidationPrice`; open-orders
   patches the query cache directly with zero REST cost.

## Deployment Targets

- **Frontend**: Static build served by host Nginx on the same Oracle Cloud VPS (`/opt/enma/client/dist`) — not Vercel. See `workspace/docs/ops/DEPLOYMENT.md`.
- **Backend/Engine**: Oracle Cloud Free VM (Docker)
- **Databases**: MongoDB Atlas Free, self-hosted Redis via Docker Compose (Docker network only, not Upstash), local TimescaleDB instance.
