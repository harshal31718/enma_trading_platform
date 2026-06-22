# Enma — API Contracts

> Concise API shape definitions. All dates are ISO 8601 strings. All numeric values (prices, quantities) are strings to prevent float precision loss, except pagination.
> All responses wrap data in: `{ success: boolean, data?: any, error?: { code, message } }`

## Common Types
```typescript
type Pagination = { page: number, limit: number, total: number, totalPages?: number }
type Paginated<T> = { [key: string]: T[], pagination: Pagination, synced?: boolean }

type Strategy = { id: string, name: string, description: string, filePath: string, createdAt: string, updatedAt: string }
type SideMetric = { totalTrades: number, winningTrades: number, losingTrades: number, winRate: string, netProfit: string, netProfitPct: string, grossProfit: string, grossLoss: string, profitFactor: string, averageWin: string, averageLoss: string, payoffRatio: string, averageHoldingPeriod: string, maxConsecutiveWins: number, maxConsecutiveLosses: number }
type BacktestMetric = { totalTrades: number, winRate: string, netProfit: string, netProfitPct: string, maxDrawdown: string, sharpeRatio: string, sortinoRatio: string, calmarRatio: string, startingBalance: string, finishingBalance: string, totalFees: string, totalFunding: string, liquidations: number, leverage: number, winningTrades: number, losingTrades: number, averageWin: string, averageLoss: string, largestWin: string, largestLoss: string, averageHoldingPeriod: string, grossProfit: string, grossLoss: string, profitFactor: string, expectancy: string, payoffRatio: string, maxRunup: string, buyHoldReturnPct: string, maxConsecutiveWins: number, maxConsecutiveLosses: number, bySide: { all: SideMetric, long: SideMetric, short: SideMetric } }
type Trade = { tradeIndex: number, type: string, qty: string, entryPrice: string, exitPrice: string, entryAt: string, exitAt: string, exitReason: string, pnl: string, pnlPct: string, leverage: number, liqPrice: string, runUpPct?: string, drawdownPct?: string, barsHeld?: number }
type Order = { orderId: number, symbol: string, status: string, side: string, type: string, origQty: string, executedQty: string, price: string, timeInForce: string }
type Position = { symbol: string, positionAmt: string, entryPrice: string, unrealizedProfit: string, leverage: string, marginType: string }
type Balance = { asset: string, walletBalance: string, availableBalance: string, unrealizedProfit: string }
```

## Client ↔ Server (REST)

> **Note:** Auth routes (`/api/v1/auth/register`, `/login`) are not yet mounted — no route file or controller exists. Remove from any active implementation reference.

### Settings
- **`GET /api/v1/trade/settings/keys`** -> `{ mode: "testnet" | "mainnet" }`
- **`POST /api/v1/trade/settings/keys`** -> Req: `{ mode: "testnet" | "mainnet" }` -> `{ saved: true, mode }`
- **`POST /api/v1/trade/settings/verify`** -> `{ verified: true, mode }` (verifies `.env` credentials against Binance)
- **`GET /api/v1/settings/exchange`** -> `{ takerFee, makerFee, slippagePct, fundingEnabled, fundingRate, defaultCapital, defaultLeverage, defaultBotCapital, defaultBotLeverage, minEdgeMult }`
- **`PUT /api/v1/settings/exchange`** -> Req: `{ takerFee?, makerFee?, slippagePct?, fundingEnabled?, fundingRate?, defaultCapital?, defaultLeverage?, defaultBotCapital?, defaultBotLeverage?, minEdgeMult? }` -> `{ takerFee, makerFee, ..., minEdgeMult }`

### Strategies & Backtesting
- **`GET /api/v1/strategies`** -> `{ strategies: Strategy[] }`
- **`POST /api/v1/strategies`** -> Req: `{ name, description, sourceName?, template? }` -> `{ strategy: Strategy }`
  - `sourceName` clones an existing strategy by name
  - `template: 'blank'` scaffolds a new blank strategy
- **`GET /api/v1/strategies/:id/code`** -> `{ code: string }`
- **`PUT /api/v1/strategies/:id/code`** -> Req: `{ code: string }` -> `{ savedAt: string }`
- **`GET /api/v1/strategies/:id/params`** -> `{ params: { [key]: { type, default, min, max, label } } }`
- **`POST /api/v1/backtest`** -> Req: `{ strategyId, exchange, symbol, timeframe, startDate, endDate, capital, leverage, feeRate }` -> `{ jobId, status }`
- **`GET /api/v1/backtest/:id`** -> `{ id, jobId, status, metrics: BacktestMetric, tradeCount: number, equityCurve: {timestamp, balance}[] }`
- **`GET /api/v1/backtest/:id/trades`** -> `Paginated<Trade> (key "trades")`
- **`POST /api/v1/backtest/:id/cancel`** -> `{ success: true, data: { jobId: string, status: "cancelled" } }`
- **`GET /api/v1/backtest` (List)** -> `{ backtests: BacktestListObj[], nextCursor: string }`

### Health
- **`GET /api/v1/health`** -> `{ status: "ok"|"degraded", mongo: "connected"|"error", redis: "connected"|"error" }` (no auth required)

### Dashboard & Data
- **`GET /api/v1/dashboard/stats`** -> `{ stats: { totalRuns, bestStrategy, averageWinRate }, leaderboard: { strategyName, runs, averageNetProfit... }[] }`
- **`GET /api/v1/candles/symbols`** -> `{ futures: string[], spot: string[] }`
- **`GET /api/v1/candles/cached`** -> `{ cached: { symbol, timeframe, start_date, end_date, total_candles }[] }`

### Live Trading (Trade Proxy - requires X-Binance Headers)
- **`GET /api/v1/trade/account`** -> `{ assets: Balance[], totalWalletBalance, totalMarginBalance, totalAvailableBalance }`
- **`GET /api/v1/trade/positions[?symbol]`** -> `{ positions: Position[] }`
- **`GET /api/v1/trade/open-orders`** -> `{ orders: Order[] }`
- **`POST /api/v1/trade/leverage`** -> Req: `{ symbol, leverage }` -> `{ symbol, leverage, maxNotionalValue, effectiveLeverage: number }` (effectiveLeverage = min(requested, symbol_max); may be lower than requested if symbol cap exceeded)
- **`POST /api/v1/trade/margin-type`** -> Req: `{ symbol, marginType: "ISOLATED" | "CROSSED" }` -> `{ code: 200, msg: "success" }`
- **`POST /api/v1/trade/order`** -> Req: `{ symbol, side, type, quantity, price? }` -> `Order`
- **`POST /api/v1/trade/order/with_tp_sl`** -> Req: `{ symbol, side, type, quantity, price?, stopLoss, takeProfit }` -> `{ entry: Order, sl: Order, tp: Order }`
- **`POST /api/v1/trade/order/oco_futures`** -> Req: `{ symbol, side, quantity, stopPrice?, takeProfitPrice? }` -> `{ orders: Order[] }`
- **`POST /api/v1/trade/order/close`** -> Req: `{ symbol }` -> `Order` (market reduceOnly fill)
- **`DELETE /api/v1/trade/order`** -> Req: `?symbol=&orderId=` -> `Order` (cancelled)
- **`DELETE /api/v1/trade/all-orders`** -> Req: `?symbol=` -> `Order[]` (cancelled)
- **`GET /api/v1/trade/order/history`** -> `Paginated<Order> (key "orders")`
- **`GET /api/v1/trade/executions/history`** -> `Paginated<Execution> (key "executions")`
- **`GET /api/v1/trade/transactions/history`** -> `Paginated<Transaction> (key "transactions")`
- **`GET /api/v1/trade/klines`** -> Req: `?symbol=&interval=&limit=` -> `[openTime, o, h, l, c, v, closeTime, qv, trades, takerBase, takerQuote, ignore][]`

## Server ↔ Engine (HTTP)
- Mirror routes exactly as above, prepended with `{ENGINE_URL}` instead of `/api/v1`. Express adds `X-Binance-API-Key` and `X-Binance-API-Secret`.

## Client ↔ Binance (Public WebSockets)
- Endpoint: `wss://fstream.binance.com/ws`
- Streams:
  - `<symbol_lower>@ticker`: 24hr stats `{ c: "lastPrice", v: "volume", P: "pctChange" }`
  - `<symbol_lower>@trade`: Real-time trades `{ p: "price", q: "qty", m: isMaker }`
  - `<symbol_lower>@depth20@100ms`: Orderbook `{ bids: [price, qty][], asks: [price, qty][] }`
  - `<symbol_lower>@kline_1m`: Live candlestick `{ k: { o, h, l, c, v, x: isClosed } }`

### AlgoTrading (Algo Bot Sessions)
```typescript
type LiveSession = { _id: string, strategyId: string, strategyName: string, symbols: string[], timeframe: string, params: object, mode: "testnet"|"mainnet", status: "starting"|"running"|"stopping"|"stopped"|"error", capital: string, leverage: number, pnl: string, openPositions: string[], createdAt: string, stoppedAt?: string, errorMessage?: string }
type SymbolLock = { reason: "bot"|"manual", sessionId: string|null, lockedAt: string }
```
- **`POST /api/v1/algo/sessions`** -> Req: `{ strategyId, symbols, timeframe, params, capital, leverage }` -> `{ sessionId, status }`
- **`POST /api/v1/algo/chaos`** -> No body required -> `{ launched: { strategy, sessionId, symbols, status }[], errors: { strategy, error }[], note: string }` — testnet-only; launches all 5 strategies with max-volatility params on 1m TF, dynamically allocating symbols from a Fisher-Yates–shuffled pool of the 70 top Binance Futures symbols (`server/src/constants/top_symbols.js`) — locked symbols are skipped and returned to the pool. HTTP 207 if partial success, 502 if all failed.
- **`GET /api/v1/algo/sessions`** -> `{ sessions: LiveSession[] }`
- **`GET /api/v1/algo/sessions/:id`** -> `{ session: LiveSession }`
- **`GET /api/v1/algo/sessions/:id/equity`** -> `{ equity: string, pnl: string }`
- **`POST /api/v1/algo/sessions/:id/stop`** -> `{ status: "stopping" }`
- **`DELETE /api/v1/algo/sessions/:id`** -> `{ deleted: true }` (stopped sessions only)
- **`DELETE /api/v1/algo/sessions`** -> `{ deleted: number }` (bulk delete all stopped)
- **`GET /api/v1/algo/symbols/locked`** -> `{ locked: { [symbol]: SymbolLock } }`

### Order History
```typescript
type TradeRecord = { tradeId: string, source: "bot"|"manual", executedBy: string, symbol: string, side: "long"|"short", qty: string, entryPrice: string, exitPrice: string, slOrderPrice?: string, tpOrderPrice?: string, margin?: string, liquidationPrice?: string, leverage?: number, netPnl: string, pnlPct?: string, fee?: string, exitReason: string, sessionId?: string, strategyName?: string, entryTime: string, exitTime: string, createdAt: string }
```
- **`GET /api/v1/order-history`** -> Query: `?symbol?&source?&side?&executedBy?&page?&limit?` -> `{ records: TradeRecord[], pagination: Pagination }` (default page=1, limit=50, max limit=200; sorted by exitTime DESC; engine is sole writer, server reads)

### Engine ↔ Node (Internal — not exposed to client)
- **`PATCH /internal/algo/sessions/:id/stats`** (Engine → Node) -> Req: `{ pnl, openPositions, status?, event?, eventData? }`
- **`POST /internal/algo/sessions/:id/place-order`** (Engine → Node) -> Binance order proxied through server credentials
- **`POST /internal/algo/sessions/:id/close-position`** (Engine → Node) -> Market reduceOnly close via server credentials
- **`POST /internal/algo/sessions/:id/set-leverage`** (Engine → Node) -> Set leverage via server credentials
- **`POST /internal/algo/sessions/:id/get-position`** (Engine → Node) -> Query current position via server credentials

### Engine AlgoTrading Routes (Node → Engine)
- **`POST /algo/sessions`** -> Req: `{ session_id, strategy_name, symbols, timeframe, params, capital, leverage, fee_rate }` (no `paper_trading` field — engine always targets Binance Testnet; `fee_rate` injected from Exchange Settings)
- **`POST /algo/sessions/:id/stop`**
- **`GET /algo/sessions/:id/status`** -> `{ status, pnl, openPositions }`

## Socket.IO Events
- Envelope: `{ event: string, data: any }`
- `backtest:progress` -> `{ jobId, pct, message }`
- `backtest:complete` -> `{ jobId, resultId }`
- `algo:session:update` -> `{ sessionId, status?, pnl?, openPositions?, symbolStats? }` — **partial**: clients merge only the fields present. Most emits carry `status`/`pnl`/`openPositions`; the per-symbol aggregation emits carry only `symbolStats` (a `{ [symbol]: { trades, qty, notional, realisedPnl, leverage } }` map re-derived from `tradeRecords` on each close and on session stop; also persisted on the `LiveSession` doc).
- `algo:position:open` -> `{ sessionId, symbol, side, qty, price, leverage, timestamp }` (`leverage` = per-symbol clamped value)
- `algo:position:close` -> `{ sessionId, symbol, pnl, exitPrice, exitReason, timestamp }`

## Error Codes
`AUTH_REQUIRED`, `AUTH_INVALID`, `NOT_FOUND`, `VALIDATION_ERROR`, `STRATEGY_ERROR`, `ENGINE_UNAVAILABLE`, `INSUFFICIENT_CANDLES`, `EXCHANGE_ERROR`, `JOB_FAILED`, `TOO_MANY_REQUESTS`, `DB_SYNC_ERROR`, `SYMBOL_LOCKED`, `SESSION_NOT_FOUND`, `SESSION_NOT_RUNNING`, `BOT_START_FAILED`.
