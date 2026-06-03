# Enma — API Contracts

> Defines exact request/response shapes for all inter-service communication.
> Claude Code must read this before writing any route handler, API call, or engine endpoint.
> Update this file whenever a new endpoint is added or an existing one changes.

---

## Conventions

- All dates: ISO 8601 strings (`"2024-01-15T10:30:00Z"`)
- All prices: strings (avoid float precision issues) — `"43521.50"`
- All quantities: strings — `"0.001"`
- Errors always return `{ success: false, error: { code, message } }`
- Success always returns `{ success: true, data: { ... } }`
- Pagination: `{ data: [...], pagination: { page, limit, total } }`

---

## Client ↔ Server (REST)

### Auth

#### POST `/api/v1/auth/register`
```json
// Request
{ "email": "user@example.com", "password": "min8chars" }

// Response 201
{
  "success": true,
  "data": {
    "user": { "id": "...", "email": "user@example.com" },
    "token": "jwt_token_here",
    "refreshToken": "refresh_token_here"
  }
}
```

#### POST `/api/v1/auth/login`
```json
// Request
{ "email": "user@example.com", "password": "..." }

// Response 200 — same shape as register
```

---

### Settings & Keys

#### GET `/api/v1/settings/keys`
```json
// Response 200
{
  "success": true,
  "data": {
    "paperTrading": true,
    "binanceApiKey": "ABCD****************EFGH"
  }
}
```

#### POST `/api/v1/settings/keys`
```json
// Request
{
  "binanceApiKey": "your_api_key_here",
  "binanceApiSecret": "your_api_secret_here",
  "paperTrading": true
}

// Response 200
{
  "success": true,
  "data": {
    "saved": true
  }
}
```

---

### Strategies

#### GET `/api/v1/strategies`
```json
// Response 200
{
  "success": true,
  "data": {
    "strategies": [
      {
        "id": "...",
        "name": "MyStrategy",
        "description": "EMA crossover",
        "filePath": "strategies/MyStrategy/__init__.py",
        "createdAt": "2024-01-15T10:30:00Z",
        "updatedAt": "2024-01-15T10:30:00Z"
      }
    ]
  }
}
```

#### POST `/api/v1/strategies`
```json
// Request
{ "name": "MyStrategy", "description": "optional" }

// Response 201
{ "success": true, "data": { "strategy": { ...same shape as above... } } }
```

#### GET `/api/v1/strategies/:id/code`
```json
// Response 200
{
  "success": true,
  "data": {
    "code": "from engine.core.strategy import BaseStrategy\n..."
  }
}
```

#### PUT `/api/v1/strategies/:id/code`
```json
// Request
{ "code": "class MyStrategy(BaseStrategy):\n    ..." }

// Response 200
{ "success": true, "data": { "savedAt": "2024-01-15T10:30:00Z" } }
```

---

### Dashboard

#### GET `/api/v1/dashboard/stats`
```json
// Proxies engine GET /dashboard/stats
// Response 200
{
  "success": true,
  "data": {
    "stats": {
      "totalRuns": 42,
      "bestStrategy": "SimpleEMACross",
      "averageWinRate": "0.54"
    },
    "leaderboard": [
      {
        "strategyName": "SimpleEMACross",
        "runs": 18,
        "averageWinRate": "0.58",
        "averageNetProfit": "2841.20",
        "averageSharpe": "1.38"
      }
    ]
  }
}
```

---

### Candles

#### GET `/api/v1/candles/symbols`
```json
// Proxies engine GET /candles/symbols
// Response 200
{
  "success": true,
  "data": {
    "futures": ["BTC-USDT", "ETH-USDT", "BNB-USDT", "..."],
    "spot": []
  }
}
```

#### GET `/api/v1/candles/cached`
```json
// Proxies engine GET /candles/cached
// Response 200
{
  "success": true,
  "data": {
    "cached": [
      {
        "symbol": "BTC-USDT",
        "timeframe": "1h",
        "exchange": "binance",
        "instrument_type": "futures",
        "start_date": "2023-01-01T00:00:00Z",
        "end_date": "2024-01-01T00:00:00Z",
        "total_candles": 8760
      }
    ]
  }
}
```

// NOTE: POST /api/v1/candles/import and GET /api/v1/candles/available are removed.
// Candles are auto-fetched by the engine when a backtest is submitted.
// See DECISIONS.md "Import Candles page removed entirely".

---

### Backtest

#### POST `/api/v1/backtest`
```json
// Request
{
  "strategyId": "...",
  "exchange": "Binance Spot",
  "symbol": "BTC-USDT",
  "timeframe": "1h",
  "startDate": "2023-01-01",
  "endDate": "2024-01-01",
  "capital": "10000",
  "leverage": 1,
  "feeRate": "0.001"
}

// Response 202
{ "success": true, "data": { "jobId": "...", "status": "queued" } }
```

#### GET `/api/v1/backtest/:id`
```json
// Response 200
{
  "success": true,
  "data": {
    "id": "...",
    "jobId": "...",
    "strategyId": "...",
    "strategyName": "...",
    "exchange": "Binance Futures",
    "symbol": "BTC-USDT",
    "timeframe": "1h",
    "startDate": "2023-01-01T00:00:00Z",
    "endDate": "2023-12-31T23:00:00Z",
    "capital": 10000,
    "leverage": 1,
    "feeRate": 0.001,
    "status": "completed",
    "metrics": {
      "totalTrades": 142,
      "winRate": "0.58",
      "netProfit": "3241.50",
      "netProfitPct": "32.41",
      "maxDrawdown": "-12.30",
      "sharpeRatio": "1.42",
      "calmarRatio": "2.63",
      "sortinoRatio": "1.87",
      "startingBalance": "10000.00",
      "finishingBalance": "13241.50",
      "totalFees": "124.50",
      "winningTrades": 82,
      "losingTrades": 60,
      "averageWin": "187.50",
      "averageLoss": "-98.20",
      "largestWin": "843.20",
      "largestLoss": "-412.10",
      "averageHoldingPeriod": "14400"
    },
    "tradeCount": 142,
    "equityCurve": [
      { "timestamp": "2023-01-01T00:00:00Z", "balance": "10000.00" }
    ]
  }
}
```

#### GET `/api/v1/backtest/:id/trades`
```json
// Request: GET /api/v1/backtest/:id/trades?page=1&limit=50
// Response 200
{
  "success": true,
  "data": {
    "trades": [
      {
        "tradeIndex": 1,
        "type": "long",
        "qty": "0.1",
        "entryPrice": "43200.50",
        "exitPrice": "44100.00",
        "entryAt": "2023-03-15T10:00:00Z",
        "exitAt": "2023-03-16T14:00:00Z",
        "exitReason": "take_profit",
        "pnl": "89.95",
        "pnlPct": "2.08"
      }
    ],
    "pagination": {
      "page": 1,
      "limit": 50,
      "total": 142,
      "totalPages": 3
    }
  }
}
```

#### GET `/api/v1/backtest` (list)
```json
// Request: GET /api/v1/backtest?limit=20&before=ObjectId
// Response 200
{
  "success": true,
  "data": {
    "backtests": [
      {
        "id": "...",
        "jobId": "...",
        "strategyName": "SimpleEMACross",
        "symbol": "BTC-USDT",
        "timeframe": "1h",
        "status": "completed",
        "exchange": "Binance Futures",
        "createdAt": "2026-06-03T14:00:00.000Z",
        "error": null,
        "tradeCount": 142
      }
    ],
    "nextCursor": "mongodb_id_string_or_null"
  }
}
```

---

### Phase 5 — Live Trading (Trade Terminal)

All endpoints below are part of Phase 5. The Express routes (`/api/v1/trade/*`) proxy to the
FastAPI engine (`/trade/*`). Express attaches `X-Binance-API-Key` and `X-Binance-API-Secret`
headers (read from the singleton `Settings` MongoDB document) before forwarding.

#### Engine endpoints (FastAPI, port 8000)

| Method | Path | Body / Query | Response `data` shape |
|--------|------|-------------|----------------------|
| `GET` | `/trade/account` | — | `{ totalWalletBalance, availableBalance, totalUnrealizedProfit, assets[] }` |
| `GET` | `/trade/positions` | `?symbol=BTC-USDT` (optional) | `{ positions: [ { symbol, positionAmt, entryPrice, unrealizedProfit, leverage, marginType } ] }` |
| `GET` | `/trade/open-orders` | — | `{ orders: [ { orderId, symbol, side, type, origQty, price, status } ] }` |
| `POST` | `/trade/leverage` | `{ symbol, leverage }` | `{ symbol, leverage, maxNotionalValue }` |
| `POST` | `/trade/margin-type` | `{ symbol, marginType }` (field ignored — engine always applies `ISOLATED`) | `{ code, msg }` |
| `POST` | `/trade/order` | `{ symbol, side, type, quantity, price? }` | full order object |
| `POST` | `/trade/close-position` | `{ symbol }` | full order object (market reduceOnly fill) |
| `DELETE` | `/trade/order` | `?symbol=&orderId=` | cancelled order object |
| `GET` | `/trade/klines` | `?symbol=&interval=&limit=` | `[[openTime, o, h, l, c, v, ...]]` |

All engine trade routes require `X-Binance-API-Key` and `X-Binance-API-Secret` request headers
(except `GET /trade/klines` which is a public market-data proxy).

#### Server proxy endpoints (Express, port 5000)

All are mirrored at `/api/v1/trade/*` with identical bodies/query params:

| Method | Path |
|--------|------|
| `GET` | `/api/v1/trade/account` |
| `GET` | `/api/v1/trade/positions` |
| `GET` | `/api/v1/trade/open-orders` |
| `POST` | `/api/v1/trade/leverage` |
| `POST` | `/api/v1/trade/margin-type` |
| `POST` | `/api/v1/trade/order` |
| `POST` | `/api/v1/trade/close-position` |
| `DELETE` | `/api/v1/trade/order` |
| `GET` | `/api/v1/trade/klines` |

Full request/response JSON examples for each endpoint are documented below under
"Client ↔ Server (REST)" (the `GET /api/v1/trade/*` blocks) and under
"Server ↔ Engine (HTTP)" (the `GET/POST/DELETE {ENGINE_URL}/trade/*` blocks).

---

### Live Trading (Phase 1 strategy-driven sessions — deferred)

#### POST `/api/v1/live/start`
```json
// Request
{
  "strategyId": "...",
  "exchange": "Binance Spot",
  "symbol": "BTC-USDT",
  "timeframe": "1h",
  "capital": "1000",
  "leverage": 1,
  "paperTrade": true
}

// Response 200
{ "success": true, "data": { "sessionId": "...", "status": "starting" } }
```

#### POST `/api/v1/live/stop`
```json
// Request
{ "sessionId": "..." }

// Response 200
{ "success": true, "data": { "status": "stopped" } }
```

#### GET `/api/v1/live/sessions`
```json
// Response 200
{
  "success": true,
  "data": {
    "sessions": [
      {
        "id": "...",
        "strategyName": "...",
        "symbol": "BTC-USDT",
        "status": "running",
        "paperTrade": true,
        "startedAt": "2024-01-15T10:00:00Z",
        "pnl": "142.50",
        "pnlPct": "14.25"
      }
    ]
  }
}
```

#### GET `/api/v1/trade/klines`
// Query parameters: symbol (string, hyphenated e.g. BTC-USDT), interval (string, e.g. 1m), limit (number, default 200)
// Response 200
{
  "success": true,
  "data": [
    [
      1689412320000,
      "65415.00",
      "65425.00",
      "65410.00",
      "65420.00",
      "10.450",
      1689412379999,
      "683745.20",
      21,
      "5.225",
      "341872.60",
      "0"
    ]
  ]
}

#### GET `/api/v1/trade/account`
```json
// Response 200
{
  "success": true,
  "data": {
    "assets": [
      {
        "asset": "USDT",
        "walletBalance": "10000.00",
        "availableBalance": "9500.00",
        "unrealizedProfit": "50.00"
      }
    ],
    "totalWalletBalance": "10000.00",
    "totalMarginBalance": "10050.00",
    "totalAvailableBalance": "9500.00"
  }
}
```

#### GET `/api/v1/trade/positions`
// Optional Query Param: ?symbol=BTC-USDT (returns details such as leverage and margin type even if active position size is 0)
// Response 200
{
  "success": true,
  "data": {
    "positions": [
      {
        "symbol": "BTC-USDT",
        "positionAmt": "0.050",
        "entryPrice": "65400.00",
        "markPrice": "65420.00",
        "unrealizedProfit": "1.00",
        "liquidationPrice": "62100.00",
        "leverage": "20",
        "marginType": "cross"
      }
    ]
  }
}
```

#### GET `/api/v1/trade/open-orders`
```json
// Response 200
{
  "success": true,
  "data": {
    "orders": [
      {
        "orderId": 82749502,
        "symbol": "BTC-USDT",
        "status": "NEW",
        "clientOrderId": "web_x92837",
        "price": "65000.00",
        "origQty": "0.010",
        "executedQty": "0.000",
        "side": "BUY",
        "type": "LIMIT",
        "timeInForce": "GTC",
        "time": 1689412345000
      }
    ]
  }
}
```

#### POST `/api/v1/trade/leverage`
```json
// Request
{
  "symbol": "BTC-USDT",
  "leverage": 20
}

// Response 200
{
  "success": true,
  "data": {
    "symbol": "BTCUSDT",
    "leverage": 20,
    "maxNotionalValue": "20000000"
  }
}
```

#### POST `/api/v1/trade/margin-type`
```json
// Request
{
  "symbol": "BTC-USDT",
  "marginType": "ISOLATED"  // field retained for compatibility but IGNORED — engine always applies ISOLATED
}

// Response 200
{
  "success": true,
  "data": {
    "code": 200,
    "msg": "success"
  }
}
```
// Isolated margin only — cross margin is removed platform-wide. The engine always sends
// marginType=ISOLATED to Binance regardless of the request body. If the symbol is already
// isolated, Binance returns code -4046 ("No need to change margin type"); the engine treats
// this as success. See DECISIONS.md "Isolated margin only (cross margin removed)".

#### POST `/api/v1/trade/order`
```json
// Request
{
  "symbol": "BTC-USDT",
  "side": "BUY",              // "BUY" or "SELL"
  "type": "LIMIT",            // "LIMIT" or "MARKET"
  "quantity": "0.005",        // Size of the order in BTC units
  "price": "65000.00",        // Required if type is LIMIT
  "timeInForce": "GTC"        // Optional (default GTC)
}

// Response 201
{
  "success": true,
  "data": {
    "orderId": 82749503,
    "symbol": "BTCUSDT",
    "status": "NEW",
    "clientOrderId": "web_x92838",
    "price": "65000.00",
    "origQty": "0.005",
    "executedQty": "0.000",
    "side": "BUY",
    "type": "LIMIT",
    "timeInForce": "GTC",
    "updateTime": 1689412347000
  }
}
```

#### POST `/api/v1/trade/close-position`
```json
// Request
{
  "symbol": "BTC-USDT"        // closes the entire current position for this symbol
}

// Response 200
{
  "success": true,
  "data": {
    "orderId": 82749510,
    "symbol": "BTCUSDT",
    "status": "FILLED",
    "side": "SELL",            // opposite of the open position side
    "type": "MARKET",
    "origQty": "0.050",        // absolute size of the closed position
    "reduceOnly": true,
    "updateTime": 1689412350000
  }
}
// If there is no open position for the symbol the engine returns 400 NO_POSITION.
```

The engine reads the current `positionAmt` for the symbol, then submits a `MARKET` order
with `reduceOnly=true` for the opposite side and the absolute position size. This guarantees
the order only ever reduces/flattens the position and never accidentally opens a new one.

#### DELETE `/api/v1/trade/order`
```json
// Request Query Params: ?symbol=BTC-USDT&orderId=82749503
// Response 200
{
  "success": true,
  "data": {
    "orderId": 82749503,
    "symbol": "BTCUSDT",
    "status": "CANCELED",
    "clientOrderId": "web_x92838",
    "price": "65000.00",
    "origQty": "0.005",
    "executedQty": "0.000",
    "side": "BUY",
    "type": "LIMIT",
    "timeInForce": "GTC"
  }
}
```

---

## Client ↔ Server (WebSocket events)

All Socket.IO events use this envelope:
```json
{ "event": "event_name", "data": { ... } }
```

### Backtest progress

Progress events cover both the candle auto-fetch phase and the simulation phase. The `message` field is always a human-readable string describing the current phase and percentage.

```json
// Server → Client

// During auto-fetch phase (engine is fetching missing candles from Binance):
{ "event": "backtest:progress", "data": { "jobId": "...", "pct": 15, "message": "Fetching candles... 15%" } }

// During simulation phase (engine is replaying candles):
{ "event": "backtest:progress", "data": { "jobId": "...", "pct": 60, "message": "Simulating BTC-USDT 1h — 60% (6000/10000 candles)" } }

// On completion:
{ "event": "backtest:complete", "data": { "jobId": "...", "resultId": "..." } }

// On error (includes cancellation):
{ "event": "backtest:error", "data": { "jobId": "...", "error": "Strategy raised an exception..." } }
```

### Live trading
```json
// Server → Client
{ "event": "live:candle",    "data": { "sessionId": "...", "candle": { "open": "...", "close": "...", "high": "...", "low": "...", "volume": "...", "timestamp": "..." } } }
{ "event": "live:order",     "data": { "sessionId": "...", "order": { "type": "buy", "price": "...", "qty": "...", "status": "filled" } } }
{ "event": "live:position",  "data": { "sessionId": "...", "position": { "type": "long", "entryPrice": "...", "qty": "...", "pnl": "...", "pnlPct": "..." } } }
{ "event": "live:error",     "data": { "sessionId": "...", "error": "..." } }
```

// NOTE: candles:progress and candles:complete Socket.IO events are removed.
// There is no separate candle import job flow. Candle fetch progress is reported
// via backtest:progress events during the auto-fetch phase.

---

## Client ↔ Binance (Public WebSockets)

Direct WebSocket connections from the client to the Binance USD-M Futures WebSockets feed.
Base URL: `wss://fstream.binance.com/ws`

### Streams & Event Data Shapes

#### 24h Ticker Stream: `<symbol_lower>@ticker`
```json
{
  "e": "24hrTicker",      // Event type
  "E": 1689412345000,     // Event time
  "s": "BTCUSDT",         // Symbol
  "p": "120.50",          // Price change
  "P": "0.18",            // Price change percent (unsigned string format)
  "w": "65123.45",        // Weighted average price
  "c": "65420.00",        // Last price
  "Q": "0.050",           // Last quantity
  "o": "65300.00",        // Open price
  "h": "66120.00",        // High price
  "l": "63850.00",        // Low price
  "v": "18432.000",       // Total traded base asset volume (BTC)
  "q": "1204321000.00"    // Total traded quote asset volume (USDT)
}
```

#### Trade Stream: `<symbol_lower>@trade`
```json
{
  "e": "trade",           // Event type
  "E": 1689412346000,     // Event time
  "s": "BTCUSDT",         // Symbol
  "t": 41238495,          // Trade ID
  "p": "65422.50",        // Price
  "q": "0.012",           // Quantity
  "b": 128384938,         // Buyer order ID
  "a": 128384945,         // Seller order ID
  "T": 1689412345950,     // Trade time
  "m": true               // Is the buyer the market maker? (determines Red/Green styling)
}
```

#### Order Book (Depth) Stream: `<symbol_lower>@depth20@100ms`
```json
{
  "lastUpdateId": 12048593, // Last update ID
  "E": 1689412346100,       // Event time
  "T": 1689412346050,       // Transaction time
  "bids": [
    ["65421.50", "0.250"],  // [Price, Qty]
    ["65420.00", "1.412"]
  ],
  "asks": [
    ["65422.50", "0.050"],
    ["65423.00", "0.985"]
  ]
}
```

#### Live Candlestick (Kline) Stream: `<symbol_lower>@kline_1m`
```json
{
  "e": "kline",             // Event type
  "E": 1689412346200,       // Event time
  "s": "BTCUSDT",           // Symbol
  "k": {
    "t": 1689412320000,     // Kline start time (ms)
    "T": 1689412379999,     // Kline close time (ms)
    "s": "BTCUSDT",         // Symbol
    "i": "1m",              // Interval
    "f": 41238490,          // First trade ID
    "L": 41238510,          // Last trade ID
    "o": "65415.00",        // Open price
    "c": "65420.00",        // Close price
    "h": "65425.00",        // High price
    "l": "65410.00",        // Low price
    "v": "10.450",          // Base asset volume
    "n": 21,                // Number of trades
    "x": false,             // Is this kline closed? (false = in progress)
    "q": "683745.20"        // Quote asset volume
  }
}
```

---

## Server ↔ Engine (HTTP)

The Node server calls the Python FastAPI engine via internal HTTP.
Base URL stored in env: `ENGINE_URL=http://localhost:8000`
All requests include header: `X-API-Key: {ENGINE_API_KEY}`

#### GET `{ENGINE_URL}/strategies`
```json
// Response 200
{
  "success": true,
  "data": {
    "strategies": [
      {
        "name": "SimpleEMACross",
        "description": "Fast/slow EMA crossover strategy",
        "filePath": "strategies/SimpleEMACross/__init__.py",
        "createdAt": "2024-01-15T10:30:00Z",
        "updatedAt": "2024-01-15T10:30:00Z"
      }
    ]
  }
}
```

#### GET `{ENGINE_URL}/strategies/:name/code`
```json
// Response 200
{
  "success": true,
  "data": {
    "code": "from engine.core.strategy import BaseStrategy\n...",
    "name": "SimpleEMACross",
    "filePath": "strategies/SimpleEMACross/__init__.py"
  }
}
```

#### POST `{ENGINE_URL}/backtest/run`
```json
// Request (server → engine)
{
  "jobId": "...",
  "strategyFile": "strategies/MyStrategy/__init__.py",
  "exchange": "Binance Spot",
  "symbol": "BTC-USDT",
  "timeframe": "1h",
  "startDate": "2023-01-01",
  "endDate": "2024-01-01",
  "capital": 10000,
  "leverage": 1,
  "feeRate": 0.001
}

// Response 200 (engine → server) — full result same as backtest GET above
```

#### GET `{ENGINE_URL}/candles/symbols`
```json
// Response 200
{
  "success": true,
  "data": {
    "futures": ["BTC-USDT", "ETH-USDT", "BNB-USDT", "..."],
    "spot": []
  }
}
```

#### GET `{ENGINE_URL}/candles/cached`
```json
// Runs GROUP BY query on TimescaleDB candles hypertable
// Groups by (exchange, symbol, timeframe, instrument_type)
// Response 200
{
  "success": true,
  "data": {
    "cached": [
      {
        "symbol": "BTC-USDT",
        "timeframe": "1h",
        "exchange": "binance",
        "instrument_type": "futures",
        "start_date": "2023-01-01T00:00:00Z",
        "end_date": "2024-01-01T00:00:00Z",
        "total_candles": 8760
      }
    ]
  }
}
```

#### GET `{ENGINE_URL}/dashboard/stats`
```json
// Reads backtestResults from MongoDB (motor) and aggregates
// Response 200
{
  "success": true,
  "data": {
    "stats": {
      "totalRuns": 42,
      "bestStrategy": "SimpleEMACross",
      "averageWinRate": "0.54"
    },
    "leaderboard": [
      {
        "strategyName": "SimpleEMACross",
        "runs": 18,
        "averageWinRate": "0.58",
        "averageNetProfit": "2841.20",
        "averageSharpe": "1.38"
      }
    ]
  }
}
```

// NOTE: POST {ENGINE_URL}/candles/import is removed.
// Candle fetching is handled internally by the engine inside run_backtest_simulation()
// via ensure_candles_available(). The server never calls the engine to import candles.

#### POST `{ENGINE_URL}/live/start`
```json
// Request
{
  "sessionId": "...",
  "strategyFile": "strategies/MyStrategy/__init__.py",
  "exchange": "Binance Spot",
  "symbol": "BTC-USDT",
  "timeframe": "1h",
  "capital": 1000,
  "leverage": 1,
  "paperTrade": true,
  "redisUrl": "redis://localhost:6379"
}

// Response 200
{ "success": true, "status": "started" }
```

#### POST `{ENGINE_URL}/trade/verify`
```json
// Request
{
  "binanceApiKey": "api_key",
  "binanceApiSecret": "api_secret"
}

// Response 200
{
  "success": true
}
```

#### GET `{ENGINE_URL}/trade/klines`
// Query parameters: symbol (string, e.g. BTC-USDT), interval (string), limit (number)
// Response 200
{
  "success": true,
  "data": [
    [
      1689412320000,
      "65415.00",
      "65425.00",
      "65410.00",
      "65420.00",
      "10.450",
      1689412379999,
      "683745.20",
      21,
      "5.225",
      "341872.60",
      "0"
    ]
  ]
}

#### GET `{ENGINE_URL}/trade/account`
// Headers:
// X-Binance-API-Key: api_key
// X-Binance-API-Secret: api_secret
// Response 200
{
  "success": true,
  "data": {
    "assets": [
      {
        "asset": "USDT",
        "walletBalance": "10000.00",
        "availableBalance": "9500.00",
        "unrealizedProfit": "50.00"
      }
    ],
    "totalWalletBalance": "10000.00",
    "totalMarginBalance": "10050.00",
    "totalAvailableBalance": "9500.00"
  }
}

#### GET `{ENGINE_URL}/trade/positions`
// Headers:
// X-Binance-API-Key: api_key
// X-Binance-API-Secret: api_secret
// Optional Query Param: ?symbol=BTC-USDT (returns details such as leverage and margin type even if active position size is 0)
// Response 200
{
  "success": true,
  "data": {
    "positions": [
      {
        "symbol": "BTC-USDT",
        "positionAmt": "0.050",
        "entryPrice": "65400.00",
        "markPrice": "65420.00",
        "unrealizedProfit": "1.00",
        "liquidationPrice": "62100.00",
        "leverage": "20",
        "marginType": "cross"
      }
    ]
  }
}

#### GET `{ENGINE_URL}/trade/open-orders`
// Headers:
// X-Binance-API-Key: api_key
// X-Binance-API-Secret: api_secret
// Response 200
{
  "success": true,
  "data": {
    "orders": [
      {
        "orderId": 82749502,
        "symbol": "BTC-USDT",
        "status": "NEW",
        "clientOrderId": "web_x92837",
        "price": "65000.00",
        "origQty": "0.010",
        "executedQty": "0.000",
        "side": "BUY",
        "type": "LIMIT",
        "timeInForce": "GTC",
        "time": 1689412345000
      }
    ]
  }
}

#### POST `{ENGINE_URL}/trade/leverage`
// Headers:
// X-Binance-API-Key: api_key
// X-Binance-API-Secret: api_secret
// Request Body
{
  "symbol": "BTC-USDT",
  "leverage": 20
}

// Response 200
{
  "success": true,
  "data": {
    "symbol": "BTCUSDT",
    "leverage": 20,
    "maxNotionalValue": "20000000"
  }
}

#### POST `{ENGINE_URL}/trade/margin-type`
// Headers:
// X-Binance-API-Key: api_key
// X-Binance-API-Secret: api_secret
// Request Body
{
  "symbol": "BTC-USDT",
  "marginType": "ISOLATED"  // field retained for compatibility but IGNORED — engine always applies ISOLATED
}

// Response 200
{
  "success": true,
  "data": {
    "code": 200,
    "msg": "success"
  }
}
// Isolated margin only. The engine always sends marginType=ISOLATED to Binance. Binance
// error -4046 ("No need to change margin type") is treated as success.

#### POST `{ENGINE_URL}/trade/order`
// Headers:
// X-Binance-API-Key: api_key
// X-Binance-API-Secret: api_secret
// Request Body
{
  "symbol": "BTC-USDT",
  "side": "BUY",
  "type": "LIMIT",
  "quantity": "0.005",
  "price": "65000.00",
  "timeInForce": "GTC"
}

// Response 200
{
  "success": true,
  "data": {
    "orderId": 82749503,
    "symbol": "BTCUSDT",
    "status": "NEW",
    "clientOrderId": "web_x92838",
    "price": "65000.00",
    "origQty": "0.005",
    "executedQty": "0.000",
    "side": "BUY",
    "type": "LIMIT",
    "timeInForce": "GTC",
    "updateTime": 1689412347000
  }
}

#### DELETE `{ENGINE_URL}/trade/order`
// Headers:
// X-Binance-API-Key: api_key
// X-Binance-API-Secret: api_secret
// Request Query Params: ?symbol=BTC-USDT&orderId=82749503
// Response 200
{
  "success": true,
  "data": {
    "orderId": 82749503,
    "symbol": "BTCUSDT",
    "status": "CANCELED",
    "clientOrderId": "web_x92838",
    "price": "65000.00",
    "origQty": "0.005",
    "executedQty": "0.000",
    "side": "BUY",
    "type": "LIMIT",
    "timeInForce": "GTC"
  }
}

---

## Error codes

| Code | Meaning |
|---|---|
| `AUTH_REQUIRED` | No token provided |
| `AUTH_INVALID` | Token invalid or expired |
| `NOT_FOUND` | Resource not found |
| `VALIDATION_ERROR` | Request body failed validation |
| `STRATEGY_ERROR` | Strategy file has a Python error |
| `ENGINE_UNAVAILABLE` | Python engine is not responding |
| `INSUFFICIENT_CANDLES` | Not enough candle data for the date range |
| `EXCHANGE_ERROR` | Binance API returned an error |
| `JOB_FAILED` | BullMQ job failed — check logs |
