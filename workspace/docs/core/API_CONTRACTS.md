# Enma — API Contracts

> Concise API shape definitions. All dates are ISO 8601 strings. All numeric values (prices, quantities) are strings to prevent float precision loss, except pagination.
> All responses wrap data in: `{ success: boolean, data?: any, error?: { code, message } }`

## Common Types
```typescript
type Pagination = { page: number, limit: number, total: number, totalPages?: number }
type Paginated<T> = { [key: string]: T[], pagination: Pagination, synced?: boolean }
// Note: getTradeOrders/getTradeExecutions/getTradeTransactions (§ Live Trading, /history endpoints)
// do NOT actually include `pagination` despite being labeled Paginated<T> below — they return only
// `{ [key]: T[], synced }`. Treat those three as `{ [key: string]: T[], synced?: boolean }`, not
// full Paginated<T>, until the controllers are updated to match.
type BacktestListObj = { id: string, jobId: string, status: string, strategyId: string, symbol: string, timeframe: string, createdAt: string, netProfitPct?: string, winRate?: string }

type Strategy = { id: string, name: string, description: string, filePath: string, createdAt: string, updatedAt: string }
type SideMetric = { totalTrades: number, winningTrades: number, losingTrades: number, winRate: string, netProfit: string, netProfitPct: string, grossProfit: string, grossLoss: string, profitFactor: string, averageWin: string, averageLoss: string, payoffRatio: string, averageHoldingPeriod: string, maxConsecutiveWins: number, maxConsecutiveLosses: number }
type BacktestMetric = { totalTrades: number, winRate: string, netProfit: string, netProfitPct: string, maxDrawdown: string, sharpeRatio: string, sortinoRatio: string, calmarRatio: string, startingBalance: string, finishingBalance: string, totalFees: string, totalFunding: string, liquidations: number, leverage: number, winningTrades: number, losingTrades: number, averageWin: string, averageLoss: string, largestWin: string, largestLoss: string, averageHoldingPeriod: string, grossProfit: string, grossLoss: string, profitFactor: string, expectancy: string, payoffRatio: string, maxRunup: string, buyHoldReturnPct: string, maxConsecutiveWins: number, maxConsecutiveLosses: number, bySide: { all: SideMetric, long: SideMetric, short: SideMetric } }
type Trade = { tradeIndex: number, type: string, qty: string, entryPrice: string, exitPrice: string, entryAt: string, exitAt: string, exitReason: string, pnl: string, pnlPct: string, leverage: number, liqPrice: string, runUpPct?: string, drawdownPct?: string, barsHeld?: number, entryTag?: string, exitTag?: string }
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
- **`GET /api/v1/trade/settings/keys`** -> `{ mode: "testnet", hasApiKey, hasApiSecret, hasMainnetApiKey, hasMainnetApiSecret }` (booleans). `mode` is always `"testnet"` (vestigial — trading is pinned to testnet).
- **`POST /api/v1/trade/settings/keys`** -> Req: `{ env?: "testnet" | "mainnet", apiKey?, apiSecret? }` (`env` defaults `"testnet"`) -> `{ saved: true, env }`.
  - `env: "testnet"` — saves either/both fields (partial update allowed). Existing testnet trading pair.
  - `env: "mainnet"` — **requires both** `apiKey` + `apiSecret`, and is **verified against Binance mainnet before storage** (read-only balance display; 400 `VERIFICATION_FAILED` on a bad key). Stored in `encryptedMainnetApiKey/Secret`.
  - Sending a `mode` field is **rejected** (400) — mainnet is read-only; trading cannot be switched to mainnet.
- **`POST /api/v1/trade/settings/verify`** -> Req: `{ env?: "testnet" | "mainnet" }` (default `"testnet"`) -> `{ verified: true, env }` (verifies the selected per-user encrypted pair against Binance with `X-Binance-Mode: env` — not `.env`).
- **`GET /api/v1/trade/balances`** -> `{ testnet, mainnet, fetchedAt }` where each env is `{ configured: false }` OR `{ configured: true, ok: true, totalWalletBalance, totalMarginBalance, totalUnrealizedProfit, availableBalance }` OR `{ configured: true, ok: false, error }`. Public route (JWT only, **not** `requireBinanceCredentials`); server decrypts both key pairs and fans out two engine `GET /trade/account` calls (`X-Binance-Mode: testnet|mainnet`) via `Promise.all`, tolerating a missing/failing env. Backs the Dashboard `AccountOverview`.
- **`GET /api/v1/settings/exchange`** -> `{ takerFee, makerFee, slippagePct, fundingEnabled, fundingRate, defaultCapital, defaultLeverage, defaultBotCapital, defaultBotLeverage, minEdgeMult, riskPct, riskRewardRatio, maxSessionDrawdown, liqBufferPct, chaosMaxManualSymbols, chaosDefaultCapital, chaosDefaultLeverage, chaosDefaultTimeframe, chaosMaxTotalSymbols, limits: { testnet: { maxSymbolsPerBot, maxConcurrentBots }, mainnet: { maxSymbolsPerBot, maxConcurrentBots } } }` — `chaosMaxStrategies` removed 2026-07-03 (superseded by `limits.testnet.maxConcurrentBots`, see DECISIONS.md). `limits.mainnet` is future-proofing only — no code path can start a mainnet session today.
- **`PUT /api/v1/settings/exchange`** -> Req: same field set as GET, all optional; `limits` is written via a dedicated nested-object validator (not the flat-field loop) so a partial payload (e.g. only `limits.testnet.maxSymbolsPerBot`) updates just that leaf -> same shape as GET

### Strategies & Backtesting
- **`GET /api/v1/strategies`** -> `{ strategies: Strategy[] }`
- **`POST /api/v1/strategies`** -> Req: `{ name, description, sourceName?, template? }` -> `{ strategy: Strategy }`
  - `sourceName` clones an existing strategy by name
  - `template: 'blank'` scaffolds a new blank strategy
- **`GET /api/v1/strategies/:id/code`** -> `{ code: string }`
- **`PUT /api/v1/strategies/:id/code`** -> Req: `{ code: string }` -> `{ savedAt: string }`
- **`GET /api/v1/strategies/:id/params`** -> `{ params: { [key]: { type, default, min, max, label, description } } }` — `type: "categorical"|"boolean"` params return `categories` instead of `min`/`max`.
- **`POST /api/v1/backtest`** -> Req: `{ strategyId, exchange, symbol, timeframe, startDate, endDate, capital, leverage, feeRate, riskParams?, alphaParams? }` -> `{ jobId, status }`. `alphaParams` is an optional per-run override of the strategy's Tier-3 PARAMS (keyed by PARAM name); omitted/`{}` ⇒ engine uses each PARAM's default. Server forwards it through the BullMQ payload to the engine's `alphaParams` field (mapped to `alpha_params`).
- **`GET /api/v1/backtest/:id`** -> `{ id, jobId, status, metrics: BacktestMetric, tradeCount: number, equityCurve: {timestamp, balance}[], underwaterCurve: {timestamp, drawdownPct}[], rollingMetricsCurve: {index, sharpe, volatility}[], returnsHistogram: {label, count, lo, hi}[], mfeMaeScatter: {mfePct, maePct, exitReason, pnl}[] }`
- **`GET /api/v1/backtest/:id/trades`** -> `Paginated<Trade> (key "trades")`
- **`GET /api/v1/backtest/:id/benchmark`** -> `{ benchmark: {timestamp, buyHold}[] }` — Buy & Hold equity path normalized to starting capital (`capital × close/firstClose`), read from the same TimescaleDB OHLCV candles the run used and aligned 1:1 to the saved equity-curve timestamps. Engine computes; server proxies. Empty array if no equity curve / candles.
- **`POST /api/v1/backtest/:id/cancel`** -> `{ success: true, data: { jobId: string, status: "cancelled" } }`
- **`GET /api/v1/backtest` (List)** -> `{ backtests: BacktestListObj[], nextCursor: string }`

### Optimization
- **`GET /api/v1/optimize/objectives`** -> `{ objectives: string[] }` (e.g. `netProfit`, `sharpeRatio`, `profitFactor`) — proxies engine `GET /optimize/objectives`
- **`POST /api/v1/optimize/run`** -> Req: `{ strategyId, exchange, symbol, timeframe, startDate, endDate, capital, leverage, feeRate, paramGrid, objective }` -> `{ jobId, status }` — proxies engine `POST /optimize/run`. Grid search only (`itertools.product` over `paramGrid`); no Bayesian/optuna support (`workspace/next_phase/S8-bayesian-hyperopt.md`).
- **`GET /api/v1/optimize/:id/status`** -> `{ jobId, status, progressPct? }` — proxies engine `GET /optimize/{job_id}/status`
- **`GET /api/v1/optimize/:id/results`** -> `{ jobId, results: { params: object, metrics: BacktestMetric }[] }`, sorted by the requested objective — proxies engine `GET /optimize/{job_id}/results`

### Health
- **`GET /api/v1/health`** -> `{ status: "ok"|"degraded", mongo: "connected"|"error", redis: "connected"|"error" }` (no auth required)

### Dashboard & Data
- **`GET /api/v1/dashboard/stats`** -> `{ stats: { totalRuns, bestStrategy, averageWinRate }, leaderboard: { strategyName, runs, averageNetProfit... }[] }` — server forwards `{ params: { userId: req.user.id } }` to the engine; response is user-scoped.
- **`GET /api/v1/dashboard/performance-calendar`** -> `{ calendar: { date, netProfit, tradeCount }[] }` — backs `DashboardCalendar.jsx` (built but not yet wired into `Dashboard.jsx`).
- **`GET /api/v1/candles/symbols`** -> `{ futures: string[], spot: string[], all: string[], rules: { [symbol]: { pricePrecision, qtyPrecision, tickSize, stepSize, maxLeverage } } }` — `all` is the Phase 7 unified/tiered symbol list; `rules` backs per-symbol order-form precision/leverage limits.
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
- **`GET /api/v1/trade/order`** -> Req: `?symbol=&orderId=` -> `Order` (single order status)
- **`DELETE /api/v1/trade/order`** -> Req: `?symbol=&orderId=` -> `Order` (cancelled)
- **`DELETE /api/v1/trade/all-orders`** -> Req: `?symbol=` -> `Order[]` (cancelled)
- **`GET /api/v1/trade/order/history`** -> `Paginated<Order> (key "orders")`
- **`GET /api/v1/trade/executions/history`** -> `Paginated<Execution> (key "executions")`
- **`GET /api/v1/trade/transactions/history`** -> `Paginated<Transaction> (key "transactions")`
- **`GET /api/v1/trade/klines`** -> Req: `?symbol=&interval=&limit=` -> `[openTime, o, h, l, c, v, closeTime, qv, trades, takerBase, takerQuote, ignore][]`
- **`POST /api/v1/trade/stream/start`** -> `{ started: true }` — starts (or heartbeat-refreshes) this user's manual-trading Binance User Data Stream; called by `useTradeStream()` on Trade page mount and every 120s while mounted. Proxies to engine `POST /trade/stream/start`.
- **`POST /api/v1/trade/stream/stop`** -> `{ stopped: true }` — stops it; called on Trade page unmount. Proxies to engine `POST /trade/stream/stop`.

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
type LiveSession = { _id: string, strategyId: string, strategyName: string, symbols: string[], timeframe: string, params: object, mode: "paper"|"live", status: "starting"|"running"|"stopping"|"stopped"|"error", tradingState: "active"|"reducing"|"halted", riskParams: object, capital: string, leverage: number, pnl: string, totalTrades: number, openPositions: string[], positionDetails: { [symbol: string]: { side, qty, price, leverage } }, symbolStats: { [symbol: string]: { trades, qty, notional, realisedPnl, leverage } }, tradeHistory: object[], createdAt: string, stoppedAt?: string, errorMessage?: string }
// positionDetails: open-position snapshots persisted on position:open / cleared on position:close, so a reloaded client can value live PnL for positions opened before its socket connected.
type SymbolLock = { reason: "bot"|"manual", sessionId: string|null, lockedAt: string }
```
- **`POST /api/v1/algo/sessions`** -> Req: `{ strategyId, symbols, timeframe, params, capital, leverage }` -> `{ sessionId, status }`. 400 `SYMBOL_CAP_EXCEEDED` if `symbols.length` exceeds `Settings.limits.testnet.maxSymbolsPerBot`; 409 `BOT_LIMIT_REACHED` if the user is already at `Settings.limits.testnet.maxConcurrentBots` running/starting/stopping sessions (2026-07-03, see DECISIONS.md).
- **`POST /api/v1/algo/sessions/:id/trading-state`** -> Req: `{ tradingState: "active"|"reducing"|"halted" }` -> `{ tradingState }` — kill-switch: `halted` blocks new entries, `reducing` allows exits only
- **`POST /api/v1/algo/pairlist/preview`** -> Req: `{ strategyName?, timeframe?, filters? }` -> `{ symbols: string[] }` — dry-run of the dynamic pairlist pipeline (`engine/services/pairlist.py`) without starting a session
- **`POST /api/v1/algo/chaos`** -> Req (optional): `{ timeframe?, strategies?: { name, symbols? }[], risk?: { capital?, leverage?, riskReward?, maxDrawdown?, riskPct?, minEdgeMult? } }` -> `{ launched: { strategy, sessionId, symbols, status }[], errors: { strategy, error }[], dropped: string[], note: string }` — testnet-only; auto-selects ALL known strategies when `strategies` is omitted (no strategy-count cap), then truncates to however many `Settings.limits.testnet.maxConcurrentBots` slots the user has left (running/starting/stopping sessions counted first) — truncated strategies appear in `errors` as `{ strategy, error: "Skipped — concurrent bot limit reached..." }`, not a hard rejection. 409 `BOT_LIMIT_REACHED` only if zero slots are available. Each strategy's manual symbol picks are guaranteed (400 `CHAOS_SYMBOL_PER_BOT_CAP_EXCEEDED` / `CHAOS_TOTAL_CAP_EXCEEDED` if manual picks alone exceed `limits.testnet.maxSymbolsPerBot` or `chaosMaxTotalSymbols`), and the remaining pool of curated symbols is round-robin partitioned per volume tier (high/mid/low), bounded by both caps — symbols that don't fit either cap land in `dropped`. HTTP 207 if partial/complete success, 502 if all failed. (2026-07-03, see DECISIONS.md)
- **`GET /api/v1/algo/chaos/symbols`** -> `{ tieredSymbols: { symbol, tier: "high"|"mid"|"low" }[] }`
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
- **`POST /internal/algo/sessions/:id/get-open-orders`** (Engine → Node) -> Query open orders via server credentials
- **`POST /internal/algo/engine-startup`** (Engine → Node) -> Engine-restart reconciliation signal — lets Node re-sync live-session state after an engine process restart

### Engine AlgoTrading Routes (Node → Engine)
- **`POST /algo/sessions`** -> Req: `{ session_id, strategy_name, symbols, timeframe, params, capital, leverage, fee_rate }` (no `paper_trading` field — engine always targets Binance Testnet; `fee_rate` injected from Exchange Settings). `symbols` capped at 250 entries (Pydantic `max_length`) as a defensive belt-and-suspenders check — real enforcement of `maxSymbolsPerBot`/`chaosMaxTotalSymbols` happens Node-side before this call (2026-07-03).
- **`POST /algo/sessions/:id/stop`**
- **`GET /algo/sessions/:id/status`** -> `{ status, pnl, openPositions }`
- **`POST /algo/sessions/:id/trading-state`** -> Req: `{ tradingState }` -> `{ tradingState }` (`engine/routers/algo.py`)
- **`POST /algo/pairlist/preview`** -> Req: `{ strategy_name?, timeframe?, filters? }` -> `{ symbols: string[] }` (`engine/routers/algo.py`)

### Engine Optimize Routes (Node → Engine)
- **`GET /optimize/objectives`**, **`POST /optimize/run`**, **`GET /optimize/{job_id}/status`**,
  **`GET /optimize/{job_id}/results`** (`engine/routers/optimize.py`, mounted `engine/main.py`) — see
  the `/api/v1/optimize/*` section above for the Node-facing shapes; Node mirrors these paths
  approximately, same pattern as other engine proxies.

## Socket.IO Events
- Envelope: `{ event: string, data: any }`
- `backtest:progress` -> `{ jobId, pct, message }`
- `backtest:complete` -> `{ jobId, resultId }`
- `algo:session:update` -> `{ sessionId, status?, pnl?, openPositions?, symbolStats?, tradingState? }` — **partial**: clients merge only the fields present. Most emits carry `status`/`pnl`/`openPositions`; the per-symbol aggregation emits carry only `symbolStats` (a `{ [symbol]: { trades, qty, notional, realisedPnl, leverage } }` map re-derived from `tradeRecords` on each close and on session stop; also persisted on the `LiveSession` doc); `tradingState` changes are emitted by the kill-switch endpoint.
- `algo:session:log` -> `{ sessionId, message: string, level?: "info"|"warn"|"error", timestamp }` — free-text session log lines, emitted repeatedly throughout a session's lifecycle (start, order placement, errors, stop).
- `algo:position:open` -> `{ sessionId, symbol, side, qty, price, leverage, timestamp }` (`leverage` = per-symbol clamped value)
- `algo:position:close` -> `{ sessionId, symbol, pnl, exitPrice, exitReason, timestamp }`
- `trade:stream-update` -> `{ type: "ORDER_TRADE_UPDATE" | "ACCOUNT_UPDATE", data: object }` — relayed 1:1 from the user's manual-trading Binance User Data Stream (raw `o`/`a` sub-object, Binance field names unchanged, e.g. `s`=symbol, `X`=order status, `i`=orderId). Sent only to the emitting user's `user:<userId>` room. See `workspace/docs/features/live-trading/SPEC.md`.

## Error Codes
`UNAUTHORIZED`, `FORBIDDEN`, `NOT_FOUND`, `BAD_REQUEST`, `VALIDATION_ERROR`, `CONFLICT`, `NO_CREDENTIALS`, `VERIFICATION_FAILED`, `STRATEGY_ERROR`, `ENGINE_ERROR`, `ENGINE_UNAVAILABLE`, `INSUFFICIENT_CANDLES`, `JOB_FAILED`, `TOO_MANY_REQUESTS`, `DB_SYNC_ERROR`, `SYMBOL_LOCKED`, `SESSION_NOT_FOUND`, `SESSION_NOT_RUNNING`, `SESSION_ACTIVE`, `INVALID_STATE`, `BOT_START_FAILED`, `SYMBOL_CAP_EXCEEDED`, `BOT_LIMIT_REACHED`, `CHAOS_SYMBOL_PER_BOT_CAP_EXCEEDED`, `CHAOS_TOTAL_CAP_EXCEEDED` (last four added 2026-07-03 — bot session caps, see DECISIONS.md).
> Previously listed `AUTH_REQUIRED`/`AUTH_INVALID`/`EXCHANGE_ERROR` do not exist in code — the real
> auth failure code is `UNAUTHORIZED` (`server/src/middleware/auth.middleware.js`).
