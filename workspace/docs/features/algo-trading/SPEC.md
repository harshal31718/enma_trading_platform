# Feature: Algo Trading (Bot Sessions)

**Status:** Implemented  
**Last updated:** 2026-06-05

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
  strategy.should_long() / strategy.should_short()
  → If signal: place order on Binance Testnet
  → Track position, compute unrealized PnL (uses fee_rate on exit)
  strategy.after()
  → Emit session update to Node server
        ↓
Node server broadcasts algo:session:update to all connected clients via Socket.IO
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
- **Multi-symbol sessions.** Each symbol gets its own Kline WebSocket stream. The strategy `should_long()` / `should_short()` is called independently per symbol.
- **Indicator warmup.** Historical candles are loaded before the live stream begins, so indicators have sufficient data on the first signal evaluation.
- **Single engine instance.** `LiveBotManager` is a singleton — it manages all active sessions in one process.

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

---

## Socket.IO Events

| Event | Direction | Payload |
|-------|-----------|---------|
| `algo:session:update` | Engine → Node → Client | `{ sessionId, status, pnl, openPositions, totalTrades }` |
| `algo:session:stopped` | Engine → Node → Client | `{ sessionId }` |

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
| `mode` | Enum | `paper` (Testnet) or `live` |
| `pnl` | String | Current PnL (decimal string) |
| `openPositions` | [Object] | Currently open positions |
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
