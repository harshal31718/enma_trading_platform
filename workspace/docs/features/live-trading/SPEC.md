# Feature: Live Trading (Trade Page)

**Status:** Implemented  
**Last updated:** 2026-06-05

---

## What It Does

Full-featured manual trading terminal for Binance Futures (Testnet). Displays real-time market data via WebSocket, allows placing market/limit orders with optional TP/SL, managing positions, and viewing account balances. A symbol lock system prevents conflicts between manual trading and running algo bots.

---

## Data Flow

```
User navigates to Trade page
        ↓
TanStack Query fetches account, positions, open orders (REST polling)
        ↓
GET /api/v1/trade/account      (refetch every 15s)
GET /api/v1/trade/positions    (refetch every 10s)
GET /api/v1/trade/open-orders  (refetch every 10s)
        ↓
Node server proxies each → engine → Binance Testnet FAPI

User selects symbol
        ↓
WebSocket streams connect directly from client to Binance:
  {symbol}@ticker         → TickerBar
  {symbol}@kline_{tf}     → ChartContainer (updates imperatively via ref)
  {symbol}@depth20@100ms  → OrderBook
  {symbol}@aggTrade        → RecentTrades
Historical klines initialized from:
  GET /api/v1/trade/klines  (proxied to engine → Binance /fapi/v1/klines)

User places order
        ↓
POST /api/v1/trade/order (or /order/with_tp_sl)
        ↓
Node server proxies → engine → Binance Testnet /fapi/v1/order
        ↓
TanStack Query invalidates positions + open orders queries
```

---

## Service Responsibilities

| Layer | Owns | Does NOT own |
|-------|------|-------------|
| Client | WebSocket subscriptions for public feeds, chart rendering, order form | Any Binance API calls |
| Node server | Route proxy, symbol lock enforcement, Binance credential injection | Order logic |
| Python engine | All Binance REST calls (account, orders, positions), HMAC signing | WebSocket management |
| Binance Testnet | Order execution, position state, balance | — |

---

## Key Invariants

- **Binance Testnet only.** All orders target `https://demo-fapi.binance.com` (the `_BASE_URLS["testnet"]` base in `engine/services/binance_testnet.py`). Mainnet is not implemented.
- **No direct client-to-Binance REST calls.** All REST calls go through server → engine.
- **Symbol lock mutual exclusion.** A symbol locked by a bot session cannot be manually traded, and a manually active symbol blocks bot entry. Lock state stored in Redis.
- **ISOLATED margin type only.** CROSS margin is not supported.
- **OCO order prefix.** OCO groups use `clientOrderId` prefix `oco_<uuid>_`. Canceling or filling either leg emits dual notifications (toast + banner).
- **Polling intervals must not be lowered.** Account: 15s minimum, Positions/Orders: 10s minimum (Binance Testnet rate limit).
- **OrderBook fallback keys.** Binance depth stream returns `asks`/`bids` (snapshot) or `a`/`b` (delta). Both must be handled.

---

## REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/trade/account` | Wallet balance, margin balance, unrealized PnL |
| GET | `/api/v1/trade/positions` | Open positions with leverage, entry price, margin type |
| GET | `/api/v1/trade/open-orders` | Active orders |
| GET | `/api/v1/trade/klines` | Historical klines (proxied from Binance) |
| POST | `/api/v1/trade/order` | Place market or limit order |
| POST | `/api/v1/trade/order/with_tp_sl` | Place order with attached TP and SL |
| POST | `/api/v1/trade/order/oco_futures` | Place OCO order pair |
| DELETE | `/api/v1/trade/order` | Cancel single order |
| DELETE | `/api/v1/trade/all-orders` | Cancel all open orders for a symbol |
| POST | `/api/v1/trade/order/close` | Close position (market, reduceOnly) |
| POST | `/api/v1/trade/leverage` | Change symbol leverage |
| POST | `/api/v1/trade/margin-type` | Change margin type (ISOLATED only) |
| GET | `/api/v1/trade/order/history` | Paginated order history |
| GET | `/api/v1/trade/executions/history` | Paginated execution (fill) history |
| GET | `/api/v1/trade/transactions/history` | Paginated income/transaction history |

---

## WebSocket Streams (client → Binance, direct)

| Stream | Purpose | Update Rate |
|--------|---------|-------------|
| `{symbol}@ticker` | Price, 24h change, high/low, volume | ~1s |
| `{symbol}@kline_{interval}` | Live candle updates for chart | Per candle close |
| `{symbol}@depth20@100ms` | Order book (top 20 levels) | 100ms |
| `{symbol}@aggTrade` | Recent trades feed | Per trade |
| All-ticker stream | Symbol search price feed (only while dropdown open) | ~1s |

---

## Symbol Lock System

| Scenario | Lock Type | Result |
|----------|-----------|--------|
| Bot session starts on BTCUSDT | `bot` lock in Redis | Manual order on BTCUSDT rejected |
| User manually trades BTCUSDT | `manual` lock in Redis | Bot session start on BTCUSDT rejected |
| Bot session stops | Lock released | Manual trading allowed again |

Redis key: `lock:symbol:{symbol}` → `{ type: 'bot' | 'manual', sessionId }`

---

## Risk Management

Auto-compute quantity when `Max Risk % of Equity` is provided:

```
quantity = (equity × riskPct) / (entryPrice - stopPrice)
```

This is computed client-side in the OrderPanel form before the POST is sent.

---

## Related Files

| File | Role |
|------|------|
| `client/src/pages/Trade.jsx` | Main trading terminal page |
| `client/src/hooks/useTrade.js` | All TanStack Query hooks for account, positions, orders, mutations |
| `client/src/hooks/useBinanceWS.js` | WebSocket subscription management |
| `server/src/routes/trade.routes.js` | Route definitions |
| `server/src/controllers/trade.controller.js` | Proxy logic for all trade endpoints |
| `server/src/middleware/requireBinanceCredentials.js` | Ensures API credentials exist before trade routes |
| `server/src/services/symbolLock.js` | Redis-backed symbol lock: lock, release, check |
| `engine/routers/trade.py` | All Binance REST call implementations |
| `engine/services/binance_testnet.py` | HMAC-SHA256 signed request helper for Binance FAPI |
