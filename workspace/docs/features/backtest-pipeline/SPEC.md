# Feature: Backtest Pipeline

**Status:** Implemented  
**Last updated:** 2026-06-05

---

## What It Does

Executes a full strategy simulation against historical OHLCV candle data. Produces a result document with metrics, equity curve, and paginated trade history. Progress is streamed in real time from the Python engine to the React client via Redis pub/sub → Socket.IO.

---

## Data Flow

```
Client submits BacktestConfigForm
  → Form pre-filled from Exchange Settings (defaultCapital, defaultLeverage, takerFee)
        ↓
POST /api/v1/backtest  (Node server)
  → Reads Exchange Settings (takerFee, slippagePct, fundingEnabled, fundingRate)
  → Injects into BullMQ job payload
        ↓
BacktestResult created in MongoDB (status: queued)
Job enqueued on bull:backtest via BullMQ
        ↓
backtest.worker.js picks up job
  → subscribes to Redis progress:{jobId}
  → sets status: running
  → calls POST {ENGINE_URL}/backtest/run with slippagePct, fundingEnabled, fundingRate
        ↓
Python engine (backtest.py):
  1. ensure_candles_available()   ← auto-fetch if needed
  2. Sequential candle replay (no lookahead)
  3. Orders fill at OPEN of next candle
  4. Entry: Check margin affordability; lock initial_margin; apply slippage
  5. Open candle: Check liquidation BEFORE SL/TP
  6. Exit priority: liquidation → stop-loss → take-profit
  7. Fees: Taker on market fills, maker on limit fills
  8. Funding: Charged at 8h boundaries (if enabled)
  9. Progress published to Redis every 100 candles
  10. Vectorized metrics computed (NumPy)
  11. Equity curve downsampled to ≤1,000 points
  12. Trades batch-inserted into backtestTrades (500/batch)
  13. metrics + equityCurve written to backtestResults
        ↓
socketEmitter.js relays progress:{jobId} → Socket.IO room backtest:{jobId}
        ↓
Client receives backtest:progress events → progress bar update
Client receives backtest:complete → fetches result + trades
```

---

## Service Responsibilities

| Layer | Owns | Does NOT own |
|-------|------|-------------|
| Client | Progress display, result rendering, deep-link routing | Any calculation |
| Node server | Job queue, BacktestResult status field, Redis cancel flag | metrics, equityCurve, backtestTrades |
| Python engine | All computation, all writes to backtestResults (metrics/equityCurve) and backtestTrades | Job queue management |

---

## Key Invariants

- **Engine is the sole writer** of `metrics`, `equityCurve`, and all `backtestTrades` documents. The Node worker only updates `status` and `error` fields.
- **`ensure_candles_available()`** is the only entry point for candle data. Never call `import_candles()` directly from routers or the simulation loop.
- **Candle replay is strictly sequential.** No future data is visible during simulation.
- **Orders fill at OPEN of the next candle** after the signal candle — not at the signal candle's close.
- **Configurable parameters:** All fees, slippage, funding, and capital/leverage defaults come from MongoDB Settings (Exchange Settings), not hardcoded constants. Server reads and injects them into the BullMQ job payload, engine uses per-run overrides.
- **Liquidation before SL/TP:** On each open candle, liquidation is checked first. If liquidated, SL/TP are skipped and position is force-closed with `exitReason="liquidation"`.
- **Cancel flow:** Node proxies `POST /api/v1/backtest/:id/cancel` to Engine `POST /backtest/cancel`. Engine publishes `"cancel"` to Redis pub/sub channel `backtest:cancel:{jobId}`. Engine's async cancel task in the backtest runner detects this and sets `is_cancelled = True`, exiting the simulation loop.
- **Trades storage:** Split into `backtestTrades` collection (separate from `backtestResults`) to stay under MongoDB's 16MB BSON document limit. Inserted in batches of 500.

---

## Cancellation Flow

```
Client calls POST /api/v1/backtest/:jobId/cancel
        ↓
Node server calls engine POST /backtest/cancel
        ↓
Engine publishes to Redis channel: backtest:cancel:{jobId}
And updates BacktestResult status to "cancelled"
        ↓
Engine's async cancel task detects the pub/sub message
        ↓
is_cancelled = True
        ↓
Main simulation loop checks flag every 100 candles
        ↓
Simulation exits, throws "JOB_CANCELLED" and discards partial run
```

---

## Deep-Link Support

Any backtest result is addressable via `?jobId=<id>` on the Backtest page. On mount, `Backtest.jsx` reads `jobId` from `useSearchParams()`, auto-selects the matching history item, and fetches its result + trades. Invalid jobIds show an inline error without crashing.

---

## Error Codes

| Code | Meaning |
|------|---------|
| `INSUFFICIENT_CANDLES` | Not enough candles for the requested date range after auto-fetch |
| `JOB_FAILED` | Engine returned a non-200 response |
| `STRATEGY_ERROR` | Strategy code raised an exception during simulation |

---

## Related Files

| File | Role |
|------|------|
| `server/src/controllers/backtest.controller.js` | Reads Exchange Settings, enqueues job with fees/slippage/funding params, creates BacktestResult |
| `server/src/models/Settings.js` | MongoDB Settings doc with taker/maker fees, slippage, funding config |
| `server/src/workers/backtest.worker.js` | Picks up job with injected settings params, calls engine, updates status |
| `server/src/services/socketEmitter.js` | Relays Redis pub/sub → Socket.IO |
| `engine/routers/backtest.py` | Receives job with slippagePct, fundingEnabled, fundingRate, passes to simulation |
| `engine/services/backtest_runner.py` | Sequential candle replay; applies per-run margin, liquidation, fees, slippage, funding logic |
| `engine/core/position.py` | Position with leverage, isolated margin, liquidation price |
| `engine/core/margin.py` | Binance isolated-margin formula, tiered MMR table |
| `engine/core/strategy.py` | BaseStrategy with centralized risk-sizing helpers |
| `engine/services/candle_manager.py` | Auto-fetch entry point |
| `engine/services/candle_importer.py` | Fetches from Binance, writes to TimescaleDB |
| `engine/services/backtest_runner.py` | Simulation loop + writes results + trades to MongoDB |
| `engine/services/progress.py` | Publishes progress to Redis |
| `client/src/hooks/useBacktest.js` | TanStack Query hooks for backtest |
| `client/src/hooks/useExchangeSettings.js` | Fetch/update exchange settings |
| `client/src/features/backtest/BacktestConfigForm.jsx` | Form with pre-filled capital/leverage from settings |
| `client/src/features/backtest/BacktestHistory.jsx` | History sidebar |
| `client/src/features/backtest/BacktestMetricCard.jsx` | KPI card component |
