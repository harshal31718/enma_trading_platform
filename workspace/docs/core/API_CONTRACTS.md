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

> All `/api/v1/*` routes require `verifyJWT` (httpOnly `enma_jwt` cookie) except `/api/v1/auth/*` and `/api/v1/health`. See Auth section below — added 2026-07-01 (UI Refinement Phase 2, §3.13).

### Auth
- **`GET /api/v1/auth/google`** -> redirects to Google OAuth consent (Passport `passport-google-oauth20`, scopes `profile email`, sessionless)
- **`GET /api/v1/auth/google/callback`** -> Google redirects here. On success: signs a 7-day JWT (`{ userId, role }`), sets it as `enma_jwt` (`httpOnly`, `sameSite: lax`, `secure` in prod), redirects to `CLIENT_URL/`. On failure (email not in whitelist): redirects to `CLIENT_URL/login?error=not_invited`.
- **`POST /api/v1/auth/logout`** -> clears the `enma_jwt` cookie -> `{ success: true, data: null }`
- **`GET /api/v1/auth/me`** -> requires `verifyJWT` -> `{ id, email, name, avatar, role: "user"|"admin" }`

### Admin (admin-only, `requireAdmin` middleware)
- **`GET /api/v1/admin/allowed-emails`** -> `{ success: true, data: { email, addedBy, addedAt }[] }`
- **`POST /api/v1/admin/allowed-emails`** -> Req: `{ email }` -> `{ email }`. 409 `CONFLICT` if already whitelisted.
- **`DELETE /api/v1/admin/allowed-emails/:email`** -> `{ success: true, data: null }`. 403 `FORBIDDEN` if attempting to remove the env `ADMIN_EMAIL`.

### Risk (Risk Intelligence Dashboard, `/risk-dashboard`)
```typescript
type GlobalHardLimits = { maxLeverageAllowed: number, maxSessionDrawdown: number, maxRiskPctPerTrade: number, cooldownPeriodHours: number }
type StrategyOverride = { riskPct?: number, riskRewardRatio?: number, maxSessionDrawdown?: number, liqBufferPct?: number, minEdgeMult?: number, customAtrMult?: number }
type SymbolOverride = { maxLeverage?: number, volatilityMultiplier?: number, maxExposureNotional?: number }
```
- **`GET /api/v1/risk/settings`** -> `{ globalHardLimits: GlobalHardLimits, strategyOverrides: { [strategyName]: StrategyOverride }, symbolOverrides: { [symbol]: SymbolOverride } }` (per-user `Settings` doc, upserted on first access)
- **`PUT /api/v1/risk/settings`** -> Req: `{ globalHardLimits?, strategyOverrides?, symbolOverrides? }` (partial; overrides keyed by name/symbol are replaced wholesale, not merged) -> same shape as GET. Server-side range validation per field (400 `VALIDATION_ERROR` with field detail on violation); `strategyOverrides` keys must match an existing `Strategy.name`.
- **`GET /api/v1/risk/live-metrics`** -> requires Binance headers (`requireBinanceCredentials`) -> proxies to engine `GET /risk/live-metrics`, cached 10s server-side in Redis per-user (`risk:live-metrics:{userId}`) -> locked margin, free balance, net leverage, long/short notional exposure, 1-day VaR/CVaR (95%/99%), 30-day correlation heatmap (Zone 1 data).
- **`GET /api/v1/risk/backtest/:id/simulation`** -> 404 if backtest not found, 400 if not `status: "completed"` -> proxies to engine `POST /backtest/run/leverage-sensitivity` -> leverage-scenario `[1,2,5,10,20]` re-runs + Monte Carlo (N=2000) ruin-probability/drawdown-exceedance curves (Zone 3 data).

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
- **`POST /api/v1/backtest`** -> Req: `{ strategyId, exchange, symbol, timeframe, startDate, endDate, capital, leverage, feeRate, riskParams?, alphaParams? }` -> `{ jobId, status }`. `alphaParams` is an optional per-run override of the strategy's Tier-3 PARAMS (keyed by PARAM name); omitted/`{}` ⇒ engine uses each PARAM's default. Server forwards it through the BullMQ payload to the engine's `alphaParams` field (mapped to `alpha_params`).
- **`GET /api/v1/backtest/:id`** -> `{ id, jobId, status, metrics: BacktestMetric, tradeCount: number, equityCurve: {timestamp, balance}[], underwaterCurve: {timestamp, drawdownPct}[], rollingMetricsCurve: {index, sharpe, volatility}[], returnsHistogram: {label, count, lo, hi}[], mfeMaeScatter: {mfePct, maePct, exitReason, pnl}[] }`
- **`GET /api/v1/backtest/:id/trades`** -> `Paginated<Trade> (key "trades")`
- **`GET /api/v1/backtest/:id/benchmark`** -> `{ benchmark: {timestamp, buyHold}[] }` — Buy & Hold equity path normalized to starting capital (`capital × close/firstClose`), read from the same TimescaleDB OHLCV candles the run used and aligned 1:1 to the saved equity-curve timestamps. Engine computes; server proxies. Empty array if no equity curve / candles.
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
- **`POST /api/v1/trade/order/with_tp_sl`** -> Req: `{ symbol, side, type, quantity, price?, stopLoss, takeProfit }` -> `{ entry: Order, sl: Order, tp: Order, tpslId: string }`. Per CORE RULE 5 (OCO), the SL and TP legs share a `clientAlgoId` prefix `tpsl_<uuid8>_` (suffixed `sl`/`tp`) so they can be tracked and peer-cancelled as one-updates-the-other (OUO) — see `_reconcile_exchange_state()` / F-019 in CURRENT_STATE.md. Manual OCO via `/oco_futures` uses the same prefix format from `oco_<uuid>_`.
- **`POST /api/v1/trade/order/oco_futures`** -> Req: `{ symbol, side, quantity, stopPrice?, takeProfitPrice? }` -> `{ orders: Order[] }`. Shares the `oco_<uuid>_<sl|tp>` clientOrderId prefix convention.
- **`POST /api/v1/trade/order/close`** -> Req: `{ symbol }` -> `Order` (market reduceOnly fill)
- **`DELETE /api/v1/trade/order`** -> Req: `?symbol=&orderId=` -> `Order` (cancelled)
- **`DELETE /api/v1/trade/all-orders`** -> Req: `?symbol=` -> `Order[]` (cancelled)
- **`GET /api/v1/trade/order/history`** -> `Paginated<Order> (key "orders")`
- **`GET /api/v1/trade/executions/history`** -> `Paginated<Execution> (key "executions")`
- **`GET /api/v1/trade/transactions/history`** -> `Paginated<Transaction> (key "transactions")`
- **`GET /api/v1/trade/klines`** -> Req: `?symbol=&interval=&limit=` -> `[openTime, o, h, l, c, v, closeTime, qv, trades, takerBase, takerQuote, ignore][]`

## Server ↔ Engine (HTTP)
- Mirror routes approximately (engine paths may simplify the REST path, e.g. server `/api/v1/trade/order/history` → engine `/trade/history-orders`). Express adds `X-Binance-API-Key` and `X-Binance-API-Secret`.

## Client ↔ Binance (Public WebSockets)
- Endpoint: `wss://fstream.binance.com/ws`
- Streams:
  - `<symbol_lower>@ticker`: 24hr stats `{ c: "lastPrice", v: "volume", P: "pctChange" }`
  - `<symbol_lower>@trade`: Real-time trades `{ p: "price", q: "qty", m: isMaker }`
  - `<symbol_lower>@depth20@100ms`: Orderbook `{ bids: [price, qty][], asks: [price, qty][] }`
  - `<symbol_lower>@kline_1m`: Live candlestick `{ k: { o, h, l, c, v, x: isClosed } }`

### AlgoTrading (Algo Bot Sessions)
```typescript
type LiveSession = { _id: string, strategyId: string, strategyName: string, symbols: string[], timeframe: string, params: object, mode: "paper"|"live", status: "starting"|"running"|"stopping"|"stopped"|"error", capital: string, leverage: number, pnl: string, openPositions: string[], positionDetails: { [symbol: string]: { side, qty, price, leverage } }, createdAt: string, stoppedAt?: string, errorMessage?: string }
// positionDetails: open-position snapshots persisted on position:open / cleared on position:close, so a reloaded client can value live PnL for positions opened before its socket connected.
type SymbolLock = { reason: "bot"|"manual", sessionId: string|null, lockedAt: string }
```
- **`POST /api/v1/algo/sessions`** -> Req: `{ strategyId, symbols, timeframe, params, capital, leverage }` -> `{ sessionId, status }`
- **`POST /api/v1/algo/chaos`** -> Req (optional): `{ timeframe?, strategies?: { name, symbols? }[], risk?: { capital?, leverage?, riskReward?, maxDrawdown?, riskPct?, minEdgeMult? } }` -> `{ launched: { strategy, sessionId, symbols, status }[], errors: { strategy, error }[], dropped: string[], note: string }` — testnet-only; launches the specified strategies (or fallback recent strategies up to `chaosMaxStrategies` cap) on Binance Testnet. Each strategy's manual symbol picks are guaranteed, and the remaining pool of curated symbols is round-robin partitioned equally per volume tier (high/mid/low). HTTP 207 if partial/complete success, 502 if all failed.
- **`GET /api/v1/algo/chaos/symbols`** -> `{ tieredSymbols: { symbol, tier: "high"|"mid"|"low" }[] }`
- **`GET /api/v1/algo/sessions`** -> `{ sessions: LiveSession[] }`
- **`GET /api/v1/algo/sessions/:id`** -> `{ session: LiveSession }`
- **`GET /api/v1/algo/sessions/:id/equity`** -> `{ equity: 