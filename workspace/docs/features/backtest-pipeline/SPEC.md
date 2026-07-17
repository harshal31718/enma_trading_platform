# Feature: Backtest Pipeline

**Status:** Implemented
**Last updated:** 2026-07-02 — added the Phase-2 realism-curve fields, multi-symbol shared-wallet path,
and the Unified Execution Kernel to the data flow below; previous version dated 2026-06-05.

---

## What It Does

Executes a full strategy simulation against historical OHLCV candle data. Produces a result document with metrics, equity curve, and paginated trade history. Progress is streamed in real time from the Python engine to the React client via Redis pub/sub → Socket.IO.

---

## Data Flow

```
Client submits NewBacktestWizard (multi-step dialog launched from the "New Backtest" header button)
  → Wizard pre-filled from Exchange Settings (defaultCapital, defaultLeverage, takerFee, risk)
  → Optional per-run strategy alphaParams collected on the Parameters step
        ↓
POST /api/v1/backtest  (Node server)
  → Reads Exchange Settings (takerFee, slippagePct, fundingEnabled, fundingRate)
  → Injects into BullMQ job payload (incl. alphaParams forwarded to the engine)
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
  13. metrics, equityCurve, underwaterCurve, rollingMetricsCurve, returnsHistogram, mfeMaeScatter,
      and the per-run alphaParams/riskParams written to backtestResults
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

## Execution & Risk Mechanics

- **Five-model pipeline** (`pipeline.evaluate(s, current_holding)`, unconditional every candle, no
  early return for open positions — signed `current_holding` flows through all five models): Alpha
  emits `Signal` via `forecast()` only; Risk owns stops/trailing/drawdown breaker (`assess()`); Cost
  owns fee/slippage estimation (`estimate()`); Portfolio owns sizing/veto (`construct()`); Execution
  is the sole writer of `buy`/`sell`/`stop_loss`/`take_profit`/`_pending_flip`/`_close_at_open`
  (`route()`, 5 paths: flat→flat, hold→close, flat→enter, flip, maintain bracket). Full model
  contracts: `workspace/docs/core/MODELS.md`.
- **Isolated-margin futures model**: real leverage (initial margin locked on entry, affordability
  checked), Binance tiered-MMR liquidation checked *before* SL/TP each open candle (loss capped at
  forfeited isolated margin, `pnlPct=-100`), maker/taker fees, adverse slippage on market fills,
  optional funding at 8h boundaries (off by default; longs pay / shorts receive on a positive rate)
  — see `DECISIONS.md` #10.
- **Risk-based position sizing**: centralized in `BaseStrategy` (`size_by_risk`, `atr_stop`,
  `rr_target`, `trail_stop`, `move_to_breakeven`); all 5 seeded strategies size via pluggable
  `PortfolioModel` subclasses. Per-run risk overrides (`risk_pct`, `rrr`, `max_session_dd`,
  `liq_buffer_pct`) come from the wizard's Settings step, pre-filled from Exchange Settings
  defaults, merged server-side (`utils/risk.js → resolveRiskParams`) over saved defaults, mapped to
  the engine's snake_case `riskParams`, persisted on `backtestResults`.
- **Multi-symbol shared wallet (F-017)**: comma-separated symbols (`BTCUSDT,ETHUSDT`) run through
  `_run_shared_portfolio()` — all symbols advance together in timestamp order against ONE balance
  with shared isolated margin (every position competes for the same capital, mirroring multi-symbol
  live) rather than pre-split per-symbol capital. Entry affordability checks free capital
  (`balance − Σ open-position margin`). Portfolio equity recorded once per timestamp; trades
  chronologically merged with sequential IDs. Single-symbol runs use the original per-symbol loop,
  verified golden-master byte-identical to the shared-wallet path's single-symbol case.
- **Unified Execution Kernel (F-024)**: `engine/core/kernel.py`'s `ExecutionKernel` unifies the
  backtest and live execution driver loops via the `ExecutionAdapter` Callback/Adapter pattern
  (`BacktestAdapter`/`LiveAdapter`) — same entry/exit/flip logic on both paths, no driver-level
  asymmetry.
- **Pluggable execution algorithms (A-016)**: TWAP/VWAP/Iceberg (`core/models/exec_algo.py`)
  intercept the pipeline's `OrderPlan` and slice the parent order. The kernel routes the first slice
  as the entry and every subsequent slice through the position-adjust ("add") path, so the full
  parent quantity fills across candles.
- **Metric-definition corrections** (standardise audit): Calmar = CAGR over max drawdown, not total
  return; Sortino measures downside deviation against a 0 target over all periods
  (freqtrade-equivalent); ProfitFactor/PayoffRatio return `inf` for a no-loss run instead of `0.00`;
  take-profit prices round away from entry like stops, on both backtest and live paths.
- **Reject, don't clamp, param overrides (F-015/F-016)**: backtest and live param injection raises
  `ValueError` when a param is out of range or unknown, instead of silently clamping or dropping.
  Applies to both dict-style and typed `PARAMS`.
- **Typed self-validating parameters (A-005)**: `engine/core/params.py` — `IntParameter`,
  `FloatParameter`, `DecimalParameter`, `CategoricalParameter`, `BooleanParameter`; bounds validated at
  construction, type coercion, `.to_dict()` for the API. Backward-compatible with legacy dict-style
  `PARAMS` via shared helpers (`param_coerce`, `param_validate`, `param_default`, `param_to_dict`).
- **Position adjustment / DCA (A-014)**: `Position.add_qty()` (scale-in: recalculates average entry
  price, merges fees) and `Position.reduce_qty()` (partial close: returns realized P&L, keeps the
  position open). `Strategy.adjust_trade_position()` hook (returns `(qty_delta, tag) | None`,
  freqtrade-DCA-style) is evaluated by the `ExecutionKernel` whenever a position is open; a non-zero
  qty delta routes through the adapter (`BacktestAdapter`/`LiveAdapter` — same hook, same code path
  live per algo-trading/SPEC.md). Backward compatible: strategies that don't override the hook return
  `None`, zero behavior change.
- **Entry/exit tagging end-to-end (A-015)**: `Signal.entry_tag`/`exit_tag` (set in `forecast()` or
  `adjust_trade_position()`) and `OrderPlan.intent`("enter"|"add"|"reduce"|"exit")/`entry_tag`
  propagate through `build_trade_record()` and persist on both `BacktestTrade.entryTag`/`exitTag` and
  `TradeRecord.entryTag`/`exitTag` — enables per-tag analytics independent of per-strategy analytics.

---

## Optimization (Grid Search)

`engine/services/optimizer.py` runs a grid search over parameter combinations (int step/range, float
linspace, categorical values, random-subset support) against 8 objective functions (sharpe, sortino,
calmar, profit, profit_pct, drawdown, sqn, multi). Results persist to MongoDB `optimizationResults`.
Router: `engine/routers/optimize.py` — `GET /optimize/objectives`, `POST /optimize/run`,
`GET /optimize/{id}/status`, `GET /optimize/{id}/results` (mirrored at `/api/v1/optimize/*`, see
`API_CONTRACTS.md`). No Bayesian/optuna support yet — grid search only (`workspace/plan/19_bayesian-hyperopt.md`).

---

## Report UI

- **Tabbed result view**: Overview (14-metric headline 2×7 grid — Net Profit, Net P&L %, Max
  Drawdown vs allowed `max_session_dd`, Win Rate, Total Trades, Profit Factor, Sharpe, Sortino,
  Calmar, Expectancy, Leverage, Fee Rate, Total Fees, Liquidations — plus Equity/Drawdown/Benchmark
  chart and Performance Calendar), Performance Summary (comparative All/Long/Short table), List of
  Trades (log table with MFE/MAE excursions and bars-held).
- **Equity curve**: dynamic color (emerald-400 profitable / red-400 losing) with a true Buy & Hold
  benchmark overlay — `GET /api/v1/backtest/:id/benchmark` re-reads the same TimescaleDB candles the
  run used, normalizes to starting capital, aligned 1:1 to the saved equity-curve timestamps.
- **Performance Calendar**: Day/Week/Month/Quarter P&L heatmap in the Overview tab, backed by
  `backtest-analytics.js` + `useAllBacktestTrades`.

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
| `engine/services/backtest_runner.py` | Sequential candle replay; applies per-run margin, liquidation, fees, slippage, funding logic; writes results + trades to MongoDB |
| `engine/core/kernel.py` | `ExecutionKernel`/`ExecutionAdapter` — unifies backtest/live order-routing logic (F-024) |
| `engine/core/models/exec_algo.py` | TWAP/VWAP/Iceberg order-splitting algorithms (A-016), if configured |
| `engine/core/position.py` | Position with leverage, isolated margin, liquidation price; `add_qty()`/`reduce_qty()` for DCA (A-014) |
| `engine/core/margin.py` | Binance isolated-margin formula, tiered MMR table |
| `engine/core/strategy.py` | BaseStrategy with centralized risk-sizing helpers; `adjust_trade_position()` DCA hook |
| `engine/core/params.py` | Typed self-validating parameter classes (A-005) |
| `engine/services/optimizer.py` | Grid-search parameter optimization (A-006) |
| `engine/routers/optimize.py` | `GET /optimize/objectives`, `POST /optimize/run`, `GET /optimize/{id}/status`, `GET /optimize/{id}/results` |
| `engine/services/candle_manager.py` | Auto-fetch entry point |
| `engine/services/candle_importer.py` | Fetches from Binance, writes to TimescaleDB |
| `engine/services/curves.py` | Computes underwaterCurve/rollingMetricsCurve/returnsHistogram/mfeMaeScatter |
| `engine/services/progress.py` | Publishes progress to Redis |
| `client/src/hooks/useBacktest.js` | TanStack Query hooks for backtest |
| `client/src/hooks/useExchangeSettings.js` | Fetch/update exchange settings |
| `client/src/features/backtest/NewBacktestWizard.jsx` | Multi-step launch wizard (dialog) with pre-filled capital/leverage/fee/risk from settings + per-run alphaParams |
| `client/src/features/backtest/BacktestHistory.jsx` | History sidebar |
| `client/src/features/backtest/BacktestMetricCard.jsx` | KPI card component |
