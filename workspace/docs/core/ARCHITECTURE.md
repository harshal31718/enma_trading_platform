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

- **MongoDB (Node/Engine)**: `strategies`, `backtestResults`, `backtestTrades` (split from results to avoid BSON limits), `liveSessions`, `tradeOrders`, `tradeExecutions`, `Settings`.
- **TimescaleDB (Engine only)**: `candles` hypertable. Only Python engine reads/writes candles via asyncpg.
- **Redis (Node/Engine)**: BullMQ (`bull:backtest`), live cache (`live:{botId}`), progress streams (`progress:{jobId}`).

## Binance Environment Model

There are exactly two Binance environments. Only Testnet is implemented today.

| Mode | Base URL | Money | Status |
|---|---|---|---|
| **Testnet** | `https://demo-fapi.binance.com` | Fake | ✅ Active — all orders go here |
| **Mainnet** | `https://fapi.binance.com` | Real | 🔒 Not yet implemented |

Rules:
- The **authenticated/signed** base URLs are defined **once** in `engine/services/binance_testnet.py` (`_BASE_URLS` dict). All signed Binance calls go through `send_signed_request` from that module — no other file defines the *signed* base.
- **Public-data** fetches (OHLCV klines, leverageBracket) intentionally hit **mainnet** `https://fapi.binance.com` directly per `workspace/docs/core/binance-api.md` §2, so that URL also appears literally in `engine/core/live_bot_manager.py`, `engine/routers/trade.py`, `engine/services/candle_importer.py`, and `engine/utils/symbols.py`. That is by design (testnet historical data is unreliable), not a duplication of the signed base.
- All authenticated Binance calls (Trade page, algo bot entries, exits, leverage) use `send_signed_request` from that module.
- `LiveSession.mode` is `"paper" | "live"`. All current sessions are `"paper"` (Binance Testnet).
- There is no Enma-internal paper trading simulation. "Paper trading" = Binance Testnet.
- When Mainnet is added: swap `BINANCE_TESTNET_BASE` for an environment variable and add a `mode` selector to the session start flow (setting the mode to `"live"`).

## Key Architectural Rules

1. **Single User**: No `user_id` scopes anywhere. Data is global.
2. **Engine is the Writer**: Engine writes `backtestResults` and `backtestTrades` directly. Server does NOT double-write these.
3. **Keep-Alive**: Node uses `http.Agent` `keepAlive: true`, and Engine uses `httpx.AsyncClient` connection pooling.
4. **Local Dev**: Fully containerized with `docker-compose`. `node_modules` are in named volumes, TA-Lib is built inside the `engine` Dockerfile.
5. **Binance Testnet rate limits**: Trade page polls account (15 s), positions (10 s), open-orders (10 s). Do not lower these — Binance Testnet has strict per-IP rate limits and will temporarily ban the IP on excess.

## Deployment Targets

- **Frontend**: Vercel
- **Backend/Engine**: Oracle Cloud Free VM (Docker)
- **Databases**: MongoDB Atlas Free, Upstash Redis Free, local TimescaleDB instance.
