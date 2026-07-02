# Feature: Algo Trading (Bot Sessions)

**Status:** Implemented
**Last updated:** 2026-07-02 — refreshed for the 2026-07-01 multi-user auth rollout, the trading-state
kill-switch, pairlist preview, and per-symbol leverage clamping; previous version dated 2026-06-05.

---

## What It Does

Runs a Python trading strategy as a live autonomous bot against Binance Testnet. A single session can trade multiple symbols simultaneously. The bot subscribes to Binance Kline WebSocket streams and evaluates strategy logic on each candle close. Session status and PnL stream in real-time via Socket.IO.

---

## Data Flow

```
User opens NewSessionWizard
  → Form pre-filled with defaultBotCapital and defaultBotLeverage from Exchange Settings
        ↓
Selects: strategy, symbols (multi), params, capital, leverage
        ↓
POST /api/v1/algo/sessions  (Node server)
  → Reads Exchange Settings (takerFee) 
  → Injects fee_rate into engine session config
        ↓
Server checks Redis symbol lock for each symbol
        ↓
If free: creates LiveSession doc (status='starting')
        Locks all symbols in Redis (type='bot')
        Calls engine POST /algo/sessions with fee_rate
        ↓
Engine starts session in background task:
  1. Dynamic import of strategy class
  2. Load historical candles for indicator warmup
  3. Subscribe to Binance Kline WS: {symbol}@kline_{timeframe} (per symbol)
  4. Set strategy.fee_rate from session_config (not hardcoded)
        ↓
On each candle close event (per symbol):
  strategy.before()
  pipeline.evaluate(strategy, current_holding)  → Alpha forecast() → Risk → Cost → Portfolio → Execution
  → If the Execution model emits an OrderPlan: place order on Binance Testnet
  → Track position, compute unrealized PnL (uses fee_rate on exit)
  strategy.after()
  → Emit session update to Node server
        ↓
Node server emits algo:session:update to the owning user's room only (io.to('user:' + userId).emit(...))
        ↓
Client updates SessionCard in real-time (status, PnL, open positions)

User clicks "Stop"
        ↓
POST /api/v1/algo/sessions/:id/stop
        ↓
Server updates status to 'stopping', calls engine POST /algo/sessions/{id}/stop
        ↓
Engine gracefully exits loop, closes all open positions, releases symbol locks
        ↓
Socket.IO emits algo:session:stopped → client sets status to 'stopped'
```

---

## Service Responsibilities

| Layer | Owns | Does NOT own |
|-------|------|-------------|
| Client | Session list UI, NewSessionWizard, SessionCard real-time updates | Session logic |
| Node server | LiveSession MongoDB doc lifecycle, symbol lock management, engine proxy | Strategy execution |
| Python engine | Strategy execution loop, Binance WS subscription, order placement | Session persistence |

---

## Key Invariants

- **All sessions target Binance Testnet.** No real money involved.
- **Symbol lock is enforced before session start.** If any symbol is already locked (by another bot or manual trading), the session start is rejected with an error.
- **Fee rate from settings.** `strategy.fee_rate` is injected from Exchange Settings (takerFee) at session start, not hardcoded. Used to compute position exit costs.
- **Bot defaults pre-fill.** NewSessionWizard pre-fills capital and leverage from Exchange Settings one-time on load, user can override.
- **Graceful stop.** When stopped, the engine closes all open positions before exiting the loop. The session does not terminate mid-trade.
- **Candle-driven execution.** Strategy logic runs only on confirmed candle close events (not tick data). This matches backtest behavior.
- **Multi-symbol sessions.** Each symbol gets its own Kline WebSocket stream and its own strategy instance; `pipeline.evaluate()` (Alpha `forecast()` → Risk → Cost → Portfolio → Execution) runs independently per symbol.
- **Indicator warmup.** Historical candles are loaded before the live stream begins, so indicators have sufficient data on the first signal evaluation.
- **Single engine instance.** `LiveBotManager` is a singleton — it manages all active sessions in one process.
- **DCA and entry/exit tagging are shared with backtest, not live-only.** `Strategy.adjust_trade_position()`
  and `Position.add_qty()`/`reduce_qty()` (A-014) plus `Signal`/`OrderPlan` tagging (A-015) are
  evaluated by the same `ExecutionKernel` on both the live and backtest adapters — see
  `workspace/docs/features/backtest-pipeline/SPEC.md` "Execution & Risk Mechanics" for the mechanism;
  this doc doesn't duplicate it.

---

## Exchange State Reconciliation

- **Unified Exchange Reconciliation (F-001/F-002/F-004)**: `_reconcile_exchange_state()` in
  `live_bot_manager.py` queries Binance directly for position AND open orders every loop,
  unconditionally, before any exit/entry decision — self-healing when the engine wrongly believes it
  is flat. Handles 3 cases: restores orphan positions, closes stale local state, updates unrealised
  PnL from exchange mark price.
- **Orphan-position restore (I-07)**: rebuilds a lost-track position with exchange-truth `leverage`
  / `isolatedWallet` / `liquidationPrice` from `positionRisk` (not a bare `leverage=1` guess) and
  re-arms `stop_loss`/`take_profit` + `algo_ids` from the open algo orders, so a restored position is
  protected and OUO peer-cancel (below) can fire for it.
- **Open Orders Reconciliation (F-002)**: fetches both standard `/fapi/v1/openOrders` and conditional
  `/fapi/v1/openAlgoOrders` (SL/TP) each loop. Filled/cancelled orders are also detected between
  candle closes via the Binance User Data Stream (`services/user_data_stream.py` —
  `UserDataStreamManager` singleton, listen-key lifecycle, `wss://fstream.binancefuture.com/ws/{listenKey}`,
  processes `ORDER_TRADE_UPDATE` in real time, auto-reconnect with exponential backoff, 30-min
  keep-alive; per-symbol fill callbacks trigger immediate reconciliation).
- **Exchange-Reconciled Position Record (F-021)**: `LiveSession.positionDetails` is sourced from
  exchange-truth reconciliation. `_push_stats()` sends `mark_price`, `unrealized_pnl`, and
  `price_missing` per symbol; `SessionCard` uses exchange-reported `unrealized_pnl` first, falling
  back to local calc with mark price, then last price.
- **Direct Binance Placement (F-003)**: algo order placement calls `send_signed_request()` directly
  from the engine for entry, exit, and stop-close — no engine→Node→engine→Binance hop chain.
- **Mark-Price PnL Fallback Chain (F-023/A-013)**: primary source is exchange-reported
  `unRealizedProfit`. Mark price is parsed as optional (not coerced to `0`), fallback chain
  `markPrice` → cached 24h last price → engine last close. `price_missing` is set only when no
  source yields a usable price (a legitimate `0.0` PnL is preserved, not dropped — audit I-05).

## SL/TP & OCO Safety

- **Emergency Market Exit on SL Placement Failure (F-018)**: in `LiveAdapter.execute_entry()`, if a
  stop-loss conditional order fails to place after a MARKET entry fills, the engine immediately sends
  a MARKET close order, records the trade with `exit_reason="emergency_exit"`, returns `False` —
  matches freqtrade's `emergency_exit()` pattern. Position never runs naked.
- **OUO Partial-Fill Peer-Cancel (F-019)**: SL/TP algo order IDs are tracked in
  `session["open_positions"][symbol]["algo_ids"]`. Two safety nets: (1) the user-data-stream `_on_fill`
  callback cancels the peer leg (`DELETE /fapi/v1/algoOrder`) immediately when a tracked `tpsl_*`
  order reports `FILLED`/`PARTIALLY_FILLED`; (2) `_reconcile_exchange_state()` cross-checks tracked
  algo IDs against the exchange's open algo orders and cancels the peer if one leg is missing. Mirrors
  nautilus `ContingencyType.OUO` semantics for Binance conditional orders with `closePosition: "true"`.

## Dynamic Pairlist & Symbol Management

- **Unified Symbol Source (F-009)**: `GET /candles/symbols` returns `all` — every TRADING symbol
  from cached Binance exchangeInfo, enriched with volume-based tiers (`high`/`mid`/`low` from 24hr
  `quoteVolume`), base/quote asset, status. `load_symbol_volume_tiers()` populates the tier + ticker
  cache at engine startup. `symbolService.js` fetches from the engine on startup (5-min TTL), falling
  back to a static 80-symbol list (`top_symbols.js`) when the engine is unreachable.
- **Dynamic Pairlist Pipeline (A-004)**: `engine/services/pairlist.py` — composable pipeline:
  `VolumePairList` (ranks by 24h `quoteVolume` descending), `SpreadFilter` (drops wide bid/ask spreads
  via the book-ticker cache — the 24hr ticker carries no bid/ask for USDⓈ-M futures), `VolatilityFilter`
  (24h high/low band), `PrecisionFilter` (drops pairs where `tickSize/price` exceeds a threshold),
  `AgeFilter` (drops pairs listed fewer than `min_days_listed` days via exchangeInfo `onboardDate`).
  `pairlist_from_config()` builds a `PairlistPipeline` from session config; if `start_session()` gets
  empty `symbols` and `risk_params.pairlist` is configured, the pipeline generates the list
  dynamically. `POST /algo/pairlist/preview` (proxied via `POST /api/v1/algo/pairlist/preview`) dry-runs
  a config without starting a session.
- **Ticker / Book-Ticker / Listing caches**: `load_symbol_volume_tiers()` populates `_ticker_cache`;
  `load_book_tickers()` populates `_book_ticker_cache` (best bid/ask); both run at engine startup and
  feed the pairlist filters.
- **Per-symbol leverage clamping** (`engine/utils/symbols.py → clamp_leverage()`): applies
  `min(requested, symbol_max)` on every path — live bot (signed `/fapi/v1/leverageBracket` fetch +
  cache, logs when reduced), manual `POST /leverage` (returns `effectiveLeverage`), backtest (offline
  hardcoded fallback map, deterministic for golden master).

## Chaos Mode (testnet-only stress tool)

`POST /api/v1/algo/chaos` accepts custom strategies, manual/auto symbol allocation, and risk
overrides. `GET /api/v1/algo/chaos/symbols` exposes the curated tier-tagged pool (80 symbols,
`high`/`mid`/`low` by volume). The client's 4-step Chaos Wizard supports multi-strategy selection,
manual/auto symbol mapping per strategy with cap enforcement (`chaosMaxStrategies`,
`chaosMaxManualSymbols`) and live allocation previews (manual picks guaranteed, remaining symbols
round-robin partitioned per tier), timeframe/capital/leverage defaults (Chaos Settings section on the
Settings page), and a review screen before launch. `engine/scripts/chaos_runner.py` is a thin console
client with a live status table and `--stop` teardown.

## Resilience & Stats

- **Resilient order placement**: failed testnet orders in `live_bot_manager._execute_entry()` log the
  error, emit a Socket.IO notification, clear pending `buy`/`sell` signals, and return gracefully —
  no longer propagates as an unhandled exception that could crash the symbol loop.
- **Per-symbol live session stats** (`LiveSession.symbolStats`): on each position close and on session
  stop, the server re-aggregates `tradeRecords` by symbol (`computeSymbolStats` in
  `algo.controller.js`) and pushes it via a partial `algo:session:update` emit. Engine remains sole
  writer of `tradeRecords`; server reads/aggregates only. The engine calls `record_trade()` **before**
  notifying Node on close so the aggregation sees the just-closed trade; `position:open` carries the
  per-symbol clamped `leverage`.
- **SessionCard UI**: collapsed bar shows Started · Capital · Leverage · Trades (open/closed, live) ·
  P&L (realised + live-unrealized). Expanded view: Equity Curve, Session Stats grid (open/closed
  trades, win rate, avg PnL, live PnL, realised PnL, drawdown current/max), Activity Log, and an Open
  Positions panel bucket-ordered Open → Traded → Remaining (side/leverage/live-PnL plus cumulative
  trades/qty/margin/notional/realised PnL from `symbolStats`).

---

## REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/algo/sessions` | Start a new bot session |
| GET | `/api/v1/algo/sessions` | List all sessions |
| DELETE | `/api/v1/algo/sessions` | Delete all stopped/errored sessions |
| GET | `/api/v1/algo/sessions/:id` | Get single session detail |
| GET | `/api/v1/algo/sessions/:id/equity` | Get session equity curve |
| POST | `/api/v1/algo/sessions/:id/stop` | Stop a running session |
| DELETE | `/api/v1/algo/sessions/:id` | Delete a session (only if stopped/errored) |
| GET | `/api/v1/algo/symbols/locked` | Get all currently locked symbols |
| POST | `/api/v1/algo/chaos` | Launch Chaos Mode (testnet-only multi-strategy stress run) |
| GET | `/api/v1/algo/chaos/symbols` | Curated tier-tagged symbol pool for Chaos Mode |
| POST | `/api/v1/algo/sessions/:id/trading-state` | Kill-switch: set `active`/`reducing`/`halted` |
| POST | `/api/v1/algo/pairlist/preview` | Dry-run the dynamic pairlist pipeline without starting a session |

---

## Socket.IO Events

| Event | Direction | Payload |
|-------|-----------|---------|
| `algo:session:update` | Node → Client | **Partial** — clients merge only present fields. Most carry `{ sessionId, status?, pnl?, openPositions? }`; the per-symbol aggregation emit carries `{ sessionId, symbolStats }` only. |
| `algo:position:open` | Node → Client | `{ sessionId, symbol, side, qty, price, leverage, timestamp }` |
| `algo:position:close` | Node → Client | `{ sessionId, symbol, pnl, exitPrice, exitReason, timestamp }` |
| `algo:session:log` | Node → Client | `{ sessionId, type, message, timestamp }` |

> There is no `algo:session:stopped` event — a stop is communicated via `algo:session:update` with `status: "stopped"`.

---

## Session Status Lifecycle

```
starting → running → stopping → stopped
                 ↘ error
```

| Status | Description |
|--------|-------------|
| `starting` | Node created doc; engine not yet confirmed |
| `running` | Engine confirmed active, Kline WS subscribed |
| `stopping` | Stop requested; engine closing positions |
| `stopped` | Session cleanly exited, positions closed |
| `error` | Session crashed; requires manual deletion |

---

## LiveSession Model Fields

| Field | Type | Description |
|-------|------|-------------|
| `strategyId` | ObjectId | Ref to Strategy doc |
| `strategyName` | String | Strategy display name |
| `symbols` | [String] | Traded symbols |
| `timeframe` | String | Candle timeframe (e.g. `1h`) |
| `params` | Object | Strategy-specific parameters |
| `capital` | String | Starting capital (decimal string) |
| `leverage` | Number | Leverage applied |
| `status` | Enum | See lifecycle above |
| `tradingState` | Enum | `active`/`reducing`/`halted` — kill-switch, independent of `status` |
| `riskParams` | Object | Per-session risk-model override (risk %, R:R, drawdown cap, etc.) |
| `mode` | Enum | `paper` (Testnet) or `live` |
| `pnl` | String | Current PnL (decimal string) |
| `openPositions` | [Object] | Currently open positions |
| `positionDetails` | Object | `{ [symbol]: { side, qty, price, leverage } }` — reload-safe PnL snapshots, persisted on `position:open`/cleared on `position:close` (F-021) |
| `symbolStats` | Object | `{ [symbol]: { trades, qty, notional, realisedPnl, leverage } }` — per-symbol aggregation re-derived from `tradeRecords` |
| `totalTrades` | Number | Trade count since session start |
| `tradeHistory` | [Object] | `{ timestamp, balance }` for equity curve |
| `logs` | [Object] | `{ type, message, timestamp }` for session log |

---

## Related Files

| File | Role |
|------|------|
| `client/src/pages/AlgoTrading.jsx` | Session list page |
| `client/src/components/algo/NewSessionWizard.jsx` | Multi-step session creation form, pre-fills from settings |
| `client/src/components/algo/SessionCard.jsx` | Per-session card with status, PnL, stop button |
| `client/src/hooks/useAlgoSessions.js` | TanStack Query hooks for all session operations |
| `client/src/hooks/useExchangeSettings.js` | Fetch exchange settings for pre-fill |
| `client/src/hooks/useSocket.js` | Socket.IO event subscription helper |
| `server/src/routes/algo.routes.js` | Route definitions |
| `server/src/controllers/algo.controller.js` | Reads Exchange Settings (takerFee), injects fee_rate into engine call |
| `server/src/models/Settings.js` | MongoDB Settings doc with exchange configuration |
| `server/src/models/LiveSession.js` | Mongoose model |
| `server/src/services/symbolLock.js` | Redis symbol lock: lock, release, isSymbolFree |
| `engine/routers/algo.py` | POST /sessions (accepts fee_rate), POST /sessions/{id}/stop |
| `engine/core/live_bot_manager.py` | Reads fee_rate from session_config, passes to strategy; Kline WS handler, strategy execution loop |
