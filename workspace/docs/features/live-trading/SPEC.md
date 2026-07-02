# Feature: Live Trading (Trade Page)

**Status:** Implemented
**Last updated:** 2026-07-02 — added the manual-trading WebSocket User Data Stream (real-time
account/order push, replaces high-frequency REST polling), corrected the Risk Management section (no
`OrderPanel.jsx`/risk-to-stop calc exists for manual trading), and per-user credential sourcing;
previous version dated 2026-06-05.

---

## What It Does

Full-featured manual trading terminal for Binance Futures (Testnet). Displays real-time market data via WebSocket, allows placing market/limit orders with optional TP/SL, managing positions, and viewing account balances. A symbol lock system prevents conflicts between manual trading and running algo bots.

---

## Data Flow

```
User navigates to Trade page
        ↓
useTradeStream() mounts:
  POST /api/v1/trade/stream/start
        ↓
  Node server calls engine POST /trade/stream/start (userId + decrypted credentials)
        ↓
  engine/services/manual_trade_stream.py starts a per-user UserDataStreamManager
  (POST /fapi/v1/listenKey, connects wss://fstream.binancefuture.com/ws/{listenKey})
        ↓
  Every ORDER_TRADE_UPDATE / ACCOUNT_UPDATE event -> published to Redis trade-stream:{userId}
        ↓
  server/src/services/socketEmitter.js relays -> io.to('user:{userId}').emit('trade:stream-update', ...)
        ↓
  Client patches TanStack Query cache directly (open-orders: exact patch by orderId;
  positions/account: debounced 2s invalidation — ACCOUNT_UPDATE lacks markPrice/liquidationPrice,
  so those two still need one real REST fetch, just event-driven instead of a fixed short timer)
        ↓
useTradeStream() re-POSTs /stream/start every 120s as a heartbeat (keeps the engine-side idle
reaper — IDLE_TIMEOUT_SECONDS=300 — from stopping the stream); POSTs /stream/stop on unmount

TanStack Query still polls as a safety net, at much longer intervals now that WS is primary:
GET /api/v1/trade/account      (refetch every 90s, weight 5)
GET /api/v1/trade/positions    (refetch every 30s, weight 5)
GET /api/v1/trade/open-orders  (refetch every 60s, weight 40+40 — no symbol filter passed)
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
| Node server | Route proxy, symbol lock enforcement, decrypting per-user MongoDB Binance credentials (`requireBinanceCredentials`) | Order logic |
| Python engine | All Binance REST calls (account, orders, positions), HMAC signing | WebSocket management |
| Binance Testnet | Order execution, position state, balance | — |

---

## Key Invariants

- **Binance Testnet only.** All orders target `https://demo-fapi.binance.com` (the `_BASE_URLS["testnet"]` base in `engine/services/binance_testnet.py`). Mainnet is not implemented.
- **No direct client-to-Binance REST calls.** All REST calls go through server → engine.
- **Symbol lock mutual exclusion.** A symbol locked by a bot session cannot be manually traded, and a manually active symbol blocks bot entry. Lock state stored in Redis.
- **ISOLATED margin type only.** CROSS margin is not supported.
- **OCO order prefix.** OCO groups use `clientOrderId` prefix `oco_<uuid>_`. Canceling or filling either leg emits dual notifications (toast + banner).
- **Fixed 2026-07-02 — WebSocket User Data Stream replaces high-frequency REST polling.** Binance's
  rate limit is weight-based (`REQUEST_WEIGHT`, 2400/min **per IP**, shared across every user proxied
  through this server's one outbound IP — see `ARCHITECTURE.md` rule 5), and Binance's own docs
  recommend sourcing real-time order/position state from the User Data Stream rather than polling.
  `useTradeStream()` now does exactly that: one REST call to establish state, then WS push for
  changes. The REST hooks in `useTrade.js` kept their `refetchInterval`s, just lengthened
  substantially (90s/30s/60s) — they're a safety net for WS drops/reconnects, not the primary source.
  **Known gap, not yet closed:** `ACCOUNT_UPDATE` events don't carry `markPrice`/`liquidationPrice`,
  so positions/account still trigger a real (debounced) REST fetch on change rather than a pure
  cache patch — meaningfully less frequent than the old fixed 3s timer, but not zero-weight the way
  open-orders patching is. Algo/conditional orders (SL/TP placed via `/fapi/v1/algoOrder`) may or may
  not emit `ORDER_TRADE_UPDATE` — unconfirmed against live Binance (Docker wasn't running to verify);
  if they don't, they simply fall back to the 60s REST safety net rather than showing stale-wrong
  data, since the cache patch only touches entries matching a received `orderId`.
- **OrderBook fallback keys.** Binance depth stream returns `asks`/`bids` (snapshot) or `a`/`b` (delta). Both must be handled.

---

## REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/trade/account` | Wallet balance, margin balance, unrealized PnL |
| GET | `/api/v1/trade/positions` | Open positions with leverage, entry price, margin type |
| GET | `/api/v1/trade/open-orders` | Active orders |
| GET | `/api/v1/trade/klines` | Historical klines (proxied from Binance) |
| POST | `/api/v1/trade/stream/start` | Start/heartbeat this user's manual-trading WS User Data Stream |
| POST | `/api/v1/trade/stream/stop` | Stop it |
| POST | `/api/v1/trade/order` | Place market or limit order |
| POST | `/api/v1/trade/order/with_tp_sl` | Place order with attached TP and SL |
| POST | `/api/v1/trade/order/oco_futures` | Place OCO order pair |
| GET | `/api/v1/trade/order` | Get single order status |
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

**Correction (2026-07-02): this section previously described a feature that does not exist for
manual trading.** There is no `OrderPanel.jsx` component and no risk-to-stop-distance quantity
calculation anywhere in `client/src/pages/Trade.jsx` (`OrderForm()` is inline; verified by grep — no
`riskPct`/stop-distance math exists in the file). The only quantity assist on the manual order form
is `handlePctClick()`, which sizes by a flat percentage of available balance × leverage (25/50/75/100%
buttons) — not by risk-to-stop distance.

Root `CLAUDE.md` Core Rule 6 ("Auto-compute quantity if Max Risk % of Equity is provided:
`(equity * riskPct) / (entryPrice - stopPrice)`") **is real, but only applies to the Backtest and Bot
wizards** (`client/src/components/RiskParamsFields.jsx`, engine `size_by_risk`) — not to this page's
manual order form. If risk-based manual sizing is wanted, it needs to be built; this doc should not be
read as evidence that it already exists.

---

## Related Files

| File | Role |
|------|------|
| `client/src/pages/Trade.jsx` | Main trading terminal page; calls `useTradeStream()` once in `TradeInner()` |
| `client/src/hooks/useTrade.js` | All TanStack Query hooks for account, positions, orders, mutations; `useTradeStream()` (WS lifecycle + cache patching) |
| `client/src/hooks/useBinanceWS.js` | WebSocket subscription management (public market-data streams — separate from the private user-data stream) |
| `client/src/lib/socket.js` | Socket.IO client singleton — `useTradeStream()` listens for `trade:stream-update` on it |
| `server/src/routes/trade.routes.js` | Route definitions, incl. `/stream/start` \| `/stop` |
| `server/src/controllers/trade.controller.js` | Proxy logic for all trade endpoints, incl. `startTradeStream`/`stopTradeStream` |
| `server/src/services/socketEmitter.js` | Redis pub/sub → Socket.IO relay; `subscribeToTradeStream`/`unsubscribeFromTradeStream` for `trade-stream:{userId}` |
| `server/src/middleware/requireBinanceCredentials.js` | Ensures API credentials exist before trade routes |
| `server/src/services/symbolLock.js` | Redis-backed symbol lock: lock, release, check |
| `engine/routers/trade.py` | All Binance REST call implementations, incl. `/stream/start` \| `/stop` |
| `engine/services/binance_testnet.py` | HMAC-SHA256 signed request helper for Binance FAPI |
| `engine/services/manual_trade_stream.py` | Per-user `UserDataStreamManager` registry for manual trading — start/stop/idle-reap, publishes to Redis `trade-stream:{userId}` |
| `engine/services/user_data_stream.py` | `UserDataStreamManager` — WS connection, listen-key lifecycle, event parsing; `register_stream_callback()` (unfiltered, used here) vs. `register_fill_callback()` (per-symbol FILLED-only, used by the live bot) |
