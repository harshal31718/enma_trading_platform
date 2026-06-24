# ENMA — Current State

**Authority:** This is the single source of truth for what ENMA currently does.
Read this before starting any work. If this conflicts with chat history, this document wins.

Last updated: 2026-06-24

---

## Implemented Features

### Settings & Credentials
- **No authentication layer.** This is a single-user, self-hosted platform — there are no register/login endpoints, no auth middleware, and `/api/v1/auth/*` is never mounted (see `DEPRECATED.md` → "Removed Server Modules"). The previously-orphaned auth scaffolding has now been **fully removed (2026-06-22)**: `bcryptjs` + `jsonwebtoken` deleted from `server/package.json`, `client/src/store/useAuthStore.js` deleted, and the JWT request / 401-redirect interceptors stripped from `client/src/lib/axios.js`.
- Binance API key storage: AES-256 encrypted, stored in MongoDB `Settings` collection
- Key verification against Binance Testnet on save
- **Exchange Settings**: Centralized configuration for trading fees, backtest defaults, bot defaults, simulation parameters (slippage, funding), and **risk-model defaults** (risk % per trade, reward:risk ratio, max session drawdown, liquidation buffer). All values stored as variables — no hardcoded numbers. Accessible via GET/PUT `/api/v1/settings/exchange`. Forms pre-fill from saved defaults.

### Strategy Management
- List all strategies (metadata: name, description, filePath)
- Create a new strategy (scaffolds file on disk + MongoDB metadata)
- Clone an existing strategy into a new name
- View strategy source code (read-only modal)
- Extract strategy params (dynamic from Python file inspection)
- 5 strategies seeded on startup — each ported to the Narang Black-Box architecture (defines `forecast()`, binds specific risk/portfolio model, does not own `go_long`/`go_short`/`update_position`). The seeder also prunes any MongoDB strategy documents whose name is not in `DEFAULT_STRATEGIES` (e.g., stale `PnlFixer` remnant):
  - `MicroScalper` — `AtrBracketRiskModel` + `RiskBudgetPortfolio`; volatility-gated momentum crossover; flips while holding
  - `AdaptiveTrend` — `ChandelierRiskModel` + `RiskBudgetPortfolio`; regime-aware trend follower with chandelier trailing exit
  - `BestSupertrend` — `AtrBracketRiskModel` + `NotionalPortfolio`; multi-timeframe Supertrend + SMA crossovers with a hard ATR stop (replaced the earlier `SignalExitRiskModel`); closes via `_close_at_open` (intentional behavioral change from prior `liquidate()`); has `_safe_sma()` helper to guard against `period > data_length` TA errors
  - `MicroMacroRSIDivergence` — `AtrBracketRiskModel` + `RiskBudgetPortfolio`; RSI divergence with micro+macro pivot confluence; optional opposite-divergence exit
  - `MultiDivergence` — `AtrBracketRiskModel` + `RiskBudgetPortfolio`; multi-oscillator divergence confluence (9 sources: RSI, MFI, Stochastic, Z-Score, ADX, MACD, OBV, price-action, swing-volume)

### Backtesting
- BullMQ job queue (`bull:backtest`) — Node server enqueues, engine executes
- Candle auto-fetch before backtest via `ensure_candles_available()` — no manual import step needed
- Backtest simulation: strict sequential candle replay, no lookahead
- Orders execute at OPEN of next candle after signal
- **Narang Strict Black-Box Five-Model Pipeline**: All five models (Alpha → Risk → TCM → PCM → Execution) now have clean, non-leaking boundaries. `pipeline.evaluate(s, current_holding)` is unconditional every-candle — no early return for open positions. `current_holding` (signed: +long, -short, 0=flat) flows through all five models. Alpha (strategy) only emits `Signal` via `forecast()` — no account/order writes. Risk owns stops/trailing/drawdown breaker via `assess()`. TCM owns cost estimation via `estimate()`. PCM owns sizing/veto via `construct()`. Execution is sole writer of buy/sell/stop_loss/take_profit/_pending_flip/_close_at_open via `route()` (5 paths: flat→flat, hold→flat close, flat→enter, flip, maintain bracket).
- **Isolated-margin futures model**: real leverage (initial margin locked on entry, affordability check), Binance tiered-MMR **liquidation** checked before SL/TP (loss capped at the forfeited isolated margin, `pnlPct=-100`), **maker/taker fees**, **adverse slippage** on market fills, and **optional funding** (off by default; longs pay / shorts receive on a positive rate) — see DECISIONS.md #10
- **Risk-based position sizing** centralized in `BaseStrategy` (`size_by_risk`, `atr_stop`, `rr_target`, `trail_stop`, `move_to_breakeven`); all 5 strategies size via pluggable `PortfolioModel` subclasses (rule #6)
- **UI-configurable risk model**: `risk_pct`, `rrr`, `max_session_dd`, and `liq_buffer_pct` are editable per-run from the BacktestConfigForm (pre-filled from the global Risk Management defaults in Exchange Settings, overridable per run). The server merges per-run override over saved defaults (`utils/risk.js → resolveRiskParams`), maps to the engine's snake_case `riskParams` dict, persists it on `backtestResults`, and forwards it through the worker; the engine injects it in `backtest_runner` step 6b
- **Configurable simulation parameters**: Trading fees (taker/maker %), slippage %, funding rate, and capital/leverage defaults are all stored in MongoDB Settings (Exchange Settings form), not hardcoded. Defaults: taker 0.05%, maker 0.02%, slippage 0.05%, funding off
- Stop-loss / take-profit checked on every candle's high/low
- Real-time progress streaming: engine → Redis pub/sub → Node → Socket.IO → client
- Equity curve stored (downsampled to ≤1,000 points) with a **true Buy & Hold benchmark overlay** — `GET /api/v1/backtest/:id/benchmark` re-reads the same TimescaleDB OHLCV candles the run used and returns the actual price path normalized to starting capital (`capital × close/firstClose`), aligned 1:1 to the saved equity-curve timestamps; the result is fetched via `useBacktestBenchmark` and passed as `benchmark` prop to `<EquityCurve>`. Chart falls back to the old straight-line approximation only while the request is in-flight. Sharing the equity dollar scale removes any price-range/log-axis concern. **Equity line color is dynamic**: emerald-400 for profitable runs, red-400 for losing runs. Chart titles are "Equity" and "Drawdown %"
- Trades stored in `backtestTrades` collection (split to avoid BSON limits, batch-inserted in groups of 500), including per-trade run-up (MFE), drawdown (MAE), and bars held
- Paginated trade history in result view, showing Run-up, Drawdown, and Bars columns
- Cancel in-progress backtest (Redis cancel flag)
- Deep-link to any result via `?jobId=` query param
- Vectorized metric calculations using NumPy (drawdown, Sharpe, Sortino, Calmar, gross profit/loss, profit factor, expectancy, payoff ratio, streaks, and buy & hold benchmark)
- Detailed tabbed report UI: Overview (14-metric headline grid + Equity/Drawdown/Benchmark chart + Performance Calendar), Performance Summary (comparative All / Long / Short table), and List of Trades (log table with excursions). The Overview headline is a 2×7 grid — Net Profit, Net P&L %, Max Drawdown (actual `/` allowed `max_session_dd`), Win Rate, Total Trades, Profit Factor, Sharpe, Sortino, Calmar, Expectancy, Leverage, Fee Rate, Total Fees, Liquidations. The "Export JSON" action sits in the tab header bar (right-aligned, matched to the page-header "Run Backtest" button); the former bottom "Simulation Config" and "Export Results" blocks were removed.
- **Performance Calendar**: Visualizes backtest results by Day, Week, Month, or Quarter in the Overview tab. Color-coded by P&L intensity (emerald-400 for profit, red-400 for loss). Supported by `backtest-analytics.js` utility and `useAllBacktestTrades` hook.
- Backtests are launched from a multi-step dialog wizard (`NewBacktestWizard`, opened by a "New Backtest" button in the page header — mirrors the AlgoTrading "New Bot" pipeline). Steps: Strategy → Parameters (skipped when the strategy has no PARAMS) → Market → Settings → Review. The Backtest page left column is now Run History only (the inline `BacktestConfigForm` was removed). The wizard pre-fills capital/leverage/fee/risk from Exchange Settings defaults and supports per-run strategy `alphaParams` overrides (forwarded server → engine).
- **Phase 2 Metrics & Realism**: Backtesting uses a pluggable statistic registry (`StatisticRegistry` in `engine/services/metrics.py`) providing CAGR, SQN, expectancyRatio, drawdown duration (`maxDrawdownDurationCandles`), and exit-reason breakdown tables (`byExitReason`). Stored on MongoDB backtest results are additional analytics curves and datasets: Underwater/drawdown curve (`underwaterCurve`), Returns histogram (`returnsHistogram`), MFE/MAE scatter (`mfeMaeScatter`), and rolling Sharpe/volatility curves (`rollingMetricsCurve`). Fills model gap-through stops (fill at candle OPEN when range gaps stop-loss, `gap_through_stop_price()`) and candle-bounded exit fills (`bounded_exit_price()`) are implemented for realistic backtest execution.
- **Multi-Symbol Backtesting (F-017)**: The backtest runner supports comma-separated symbols (e.g., `BTCUSDT,ETHUSDT`). The starting capital is split using the portfolio model's allocation (`DefaultPortfolioModel().allocate()`), simulations are run sequentially for each symbol, trades are chronologically merged with sequential ID indexing, and equity curves are summed. Portfolio-wide metrics are then computed over the combined balance and trade list via the pluggable metric registry.
- **Unified Execution Kernel (F-024)**: Unifies the execution driver loops for both backtest simulation (`backtest_runner.py`) and live websocket trading (`live_bot_manager.py`) into `ExecutionKernel` in `engine/core/kernel.py`. The kernel uses a Callback/Adapter pattern via `ExecutionAdapter` (implemented as `BacktestAdapter` and `LiveAdapter`) to execute entry, exit, and flip transitions. This ensures perfect backtest-live execution parity and prevents driver-level asymmetries.
- **Pluggable Execution Algorithms (A-016)**: Introduces support for TWAP, VWAP, and Iceberg execution algorithms in `engine/core/models/exec_algo.py`. The execution algorithms can intercept the `OrderPlan` generated by the pipeline's `evaluate()` call, slicing entry/exit/bracket orders into steps managed sequentially by the unified kernel.

### Phase 5 — State Truth & Reconciliation
- **Unified Exchange Reconciliation (F-001/F-002/F-004)**: New `_reconcile_exchange_state()` in `live_bot_manager.py` queries Binance directly for position AND open orders every loop, unconditionally. Handles 3 cases: restores orphan positions, closes stale local state, and updates unrealised PnL from exchange mark price. Runs before any exit/entry decision — self-healing when engine wrongly believes it is flat.
- **Open Orders Reconciliation (F-002)**: `_reconcile_exchange_state()` fetches both standard `/fapi/v1/openOrders` and conditional `/fapi/v1/openAlgoOrders` (SL/TP) each loop. Filled/cancelled orders are detected between candle closes via the Binance user data stream.
- **Exchange-Reconciled Position Record (F-021)**: `positionDetails` on `LiveSession` is now sourced from exchange-truth reconciliation. `_push_stats()` sends mark_price, unrealized_pnl, and price_missing flag per symbol. `handleEngineStats` stores these in MongoDB. Client `SessionCard` uses exchange-reported `unrealized_pnl` first, falling back to local calculation with mark price, then last price.
- **User Data Stream (F-020)**: New `services/user_data_stream.py` — `UserDataStreamManager` singleton creates a Binance Futures listen key, connects to `wss://fstream.binancefuture.com/ws/{listenKey}`, processes `ORDER_TRADE_UPDATE` events in real time. Auto-reconnect with exponential backoff, 30-minute keep-alive. Registered per-symbol callbacks from `_run_symbol_loop` trigger immediate reconciliation on fill events.
- **Direct Binance Placement (F-003)**: Algo order placement now calls `send_signed_request()` directly from the engine for entry, exit, and stop-close — eliminating the engine→Node→engine→Binance hop chain. Affected methods: `execute_entry()`, `execute_exit()`, `_close_position_on_stop()`, `_reconcile_exchange_state()`.
- **Mark-Price PnL Fallback Chain (F-023/A-013)**: Live PnL uses exchange-reported `unRealizedProfit` from positionRisk as primary source, falls back to `markPrice`, then last price. `price_missing` flag set when no price source is available, propagated through `positionDetails` to the UI.


### Dashboard
- Total runs, best strategy, average win rate stats
- Strategy leaderboard (per-strategy averaged metrics, sorted by net profit)
- Recent activity table (last 5 completed backtests with deep-link to results)
- Cached candles table (TimescaleDB inventory: symbol, timeframe, exchange, type, date range, count)

### Risk Intelligence Dashboard
- **Centralized Risk Page**: Accessible at `/risk-dashboard` in the header bar between Strategies and Backtest.
- **Zone 1: Real-Time Portfolio Risk**: Visualizes aggregate locked initial margin, free wallet balance, net portfolio leverage, and net Long vs Short stacked notional exposure. Calculates live 1-day portfolio Value-at-Risk (VaR) and CVaR at 95% and 99% confidence levels, along with a Pearson correlation heatmap showing rolling 30-day close returns relationships.
- **Zone 2: Hierarchical Settings Overrides**: Configures and updates global hard limits (margin/leverage ceiling circuit breakers), strategy-specific overrides, and symbol-specific overrides. Overrides are evaluated through standard launches, chaos runs, and backtests via a cascading resolver.
- **Zone 3: Historical Simulations**: Re-runs completed backtests under leverage scenarios `[1, 2, 5, 10, 20]` using cached candles. Executes Monte Carlo bootstrap resampling (N=2000 paths) to extract ruin probabilities and drawdown exceedance curves.
- **Rate Limit Protection**: Proxy requests to engine are protected by a 10-second server-side Redis cache.

### Candle Management
- Auto-fetches OHLCV from Binance production REST API (`fapi.binance.com`) using httpx
- Stores in TimescaleDB `candles` hypertable (1,000-candle batches, 200ms inter-batch delay)
- Idempotent: `INSERT ... ON CONFLICT DO NOTHING`
- Candles are permanent — never deleted, reused across all future backtests for same symbol/timeframe
- `ensure_candles_available()` in `candle_manager.py` is the single entry point — never bypassed

### Live Trading — Trade Page
- Account info: balances, wallet balance, margin balance, unrealized PnL
- Open positions with unrealized PnL, leverage, margin type
- Open orders list
- Order placement: market, limit, with optional TP/SL
- Cancel single order, cancel all orders
- Close position (market, reduceOnly)
- Set leverage per symbol
- Set margin type (ISOLATED only)
- Live klines chart (lightweight-charts, initialized from server-proxied `/api/v1/trade/klines`, updated via Binance WS)
- Live orderbook (depth20@100ms stream, with fallback key handling for `asks`/`a`, `bids`/`b`)
- Live recent trades stream
- Order history, execution history, transaction history (all paginated)
- Symbol lock system: a symbol locked by a bot cannot be manually traded; a manually-locked symbol blocks bot entry
- All orders target Binance Testnet

### Algo Trading (Bot Sessions)
- Start a strategy as a live bot session (multi-symbol support)
- NewSessionWizard pre-fills bot capital and leverage from Exchange Settings defaults
- Strategy execution loop (candle-driven via Binance Kline WS)
- Live PnL tracking per session — **reload-safe**: open-position snapshots are persisted on the `liveSessions` doc as `positionDetails` (`{ [symbol]: { side, qty, price, leverage } }`, written on `position:open`, cleared on `position:close` by `handleEngineStats`). `SessionCard` seeds its `positionDetails` state from the session doc on mount, so live PnL resolves after a page reload instead of showing `—` for positions opened before the socket connected.
- Open position tracking
- Session status updates emitted via Socket.IO (`algo:session:update`)
- Position open/close events emitted via Socket.IO
- Symbol lock enforcement (bot-locked vs manual-locked)
- **Fee rate read from settings**: Live bot reads `takerFee` from Exchange Settings and applies it to position exit calculations
- **UI-configurable risk model**: NewSessionWizard exposes the 4 risk fields (pre-filled from global defaults, overridable per session). The server resolves and forwards them as `risk_params` to the engine, which injects them onto each per-symbol strategy instance in `live_bot_manager._run_symbol_loop` (slippage left at default — live uses real fills). Persisted on the `liveSessions` doc
- **Unified Execution Kernel & Decision Pipeline (F-024)**: Live sessions evaluate signals through the unified `ExecutionKernel` (`engine/core/kernel.py`), which runs the canonical Alpha → Risk → Portfolio → Cost → Execution quant pipeline, evaluates order plans, and checks stops, ensuring exact backtest-live logic parity.
- **Per-symbol leverage clamping** (`engine/utils/symbols.py → clamp_leverage()`): applies `min(requested, symbol_max)` on every execution path — live bot (signed `/fapi/v1/leverageBracket` fetch + cache, logs when reduced), manual `POST /leverage` (returns `effectiveLeverage` in response), backtest (offline hardcoded fallback map, silent, deterministic for golden master).
- **Chaos Mode** (testnet-only stress tool): `POST /api/v1/algo/chaos` now accepts a body for custom strategies, manual/auto symbol allocation, and risk overrides. Curated symbols list is exposed via `GET /api/v1/algo/chaos/symbols`, tier-tagging 80 symbols by trading volume (`high`, `mid`, `low`). The frontend features a beautiful 4-step Chaos Wizard Dialog supporting multi-strategy selection, manual/auto symbol mapping per strategy with cap enforcement (`chaosMaxStrategies`, `chaosMaxManualSymbols`) and live allocation previews (guaranteeing manual picks and round-robin partitioning remaining symbols equally per tier), timeframe / capital / leverage defaults (configured in a dedicated Chaos Settings section on the Settings page), and a comprehensive review screen before launch. `engine/scripts/chaos_runner.py` is a thin console client with a live status table and `--stop` teardown.
- Stop a running session
- **Resilient order placement**: failed testnet orders in `live_bot_manager._execute_entry()` now log the error, emit a Socket.IO notification, clear pending `buy`/`sell` signals, and return gracefully — no longer propagates as an unhandled exception that could crash the symbol loop
- **Per-symbol live session stats** (`LiveSession.symbolStats`): on each position close (and on session stop) the server re-aggregates the `tradeRecords` collection by symbol — `trades`, `qty`, `notional`, `realisedPnl`, `leverage` (`computeSymbolStats` in `algo.controller.js`, reads via the `TradeRecord` model) — persists it on the session doc, and pushes it via a partial `algo:session:update` emit. The engine remains the sole writer of `tradeRecords`; the server reads/aggregates only. The engine writes `record_trade()` **before** notifying Node on close so the aggregation sees the just-closed trade, and the `position:open` event now carries the per-symbol clamped `leverage`.
- **Live bot session cards** (`client/src/components/algo/SessionCard.jsx`): collapsed bar shows Started · Capital · Leverage · Trades (open/closed, live) · P&L (realised + live-unrealized, value + % of initial capital). Expanded view: Equity Curve, a compact Session Stats grid (open/closed trades, win rate, avg PnL, live PnL, realised PnL, and drawdown as current/max), Activity Log, and a redesigned Open Positions panel — per-symbol rows bucket-ordered Open → Traded → Remaining, showing side/leverage/live-PnL plus cumulative trades, qty, margin/notional, and realised PnL. Live PnL streams from the Binance ticker WS; cumulative columns come from `symbolStats`.

### Order History (Trade Recorder)
- Engine writes every completed round-trip trade to MongoDB `tradeRecords` collection via `engine/services/trade_recorder.py → record_trade()` (best-effort, never blocks the position-close path). Called by both `live_bot_manager` close paths (normal close + session stop).
- Server reads via `GET /api/v1/order-history` (Mongoose `TradeRecord` model). Supports filters: `symbol`, `source` (bot|manual), `side`, `executedBy`; paginated (default 50, max 200); sorted by exitTime DESC.
- Client: `client/src/pages/OrderHistory.jsx` — paginated trade log table with source/side badges. Hook: `client/src/hooks/useOrderHistory.js`.
- Data ownership: engine writes exclusively (`tradeRecords`); server reads only.

### Technical Indicators (engine/indicators/) — pluggable backend
- **Implemented:** `ema`, `sma`, `rsi`, `atr`, `donchian`, `macd`, `bollinger_bands`, `adx`, `stochastic`, `mfi`, `obv`, `pivot_high`, `pivot_low` (the last two are library-agnostic swing-pivot detectors — TradingView `ta.pivothigh`/`pivotlow` — usable on any candle column; the shared `_compute_pivots` primitive also detects pivots on arbitrary indicator series)
- All indicators: `sequential=False` (default, returns latest float / tuple of floats), `sequential=True` (full NaN-padded array / tuple of arrays)
- **Pluggable provider architecture** (DECISIONS.md #12): strategies call the convenience functions (`import engine.indicators as ta`); calls route through a swappable `IndicatorProvider`. **TA-Lib** is the default backend; **pandas-ta** is a pure-Python fallback (optional dependency, lazily imported). Switch the whole engine with `ENMA_INDICATOR_LIBRARY=talib|pandas_ta`; if the chosen backend fails to load, the engine auto-falls-back (`ENMA_INDICATOR_FALLBACK`, default on). No strategy changes needed to swap libraries.
- **SMA robustness** (`talib_adapter.py`): `sma()` now wraps the TA-Lib call in try/except; if `period > data_length` (or any other error), returns `np.full(shape, np.nan)` for sequential mode or `np.nan` for scalar mode — avoids crashes during warmup.
- Files: `base.py` (interface + convenience fns), `config.py` (backend selection), `adapters/talib_adapter.py`, `adapters/pandas_ta_adapter.py`

### Risk Model Improvements (Workstream #2)
- **`AtrBracketRiskModel`** (`core/models/risk.py`) gains three additive opt-in features (all default to off → golden-master safe):
  - **Trailing stop** (`trail_atr_mult`, default 0): in the maintain path, ratchets the stop toward price using `price ± trail_mult × ATR`; only ever tightens. Per-trade state (`_current_stop`, `_initialized`) reset on new entry/flip.
  - **Breakeven move** (`breakeven_r`, default 0): once price moves `breakeven_r × initial_risk` in favor, floors the stop at entry price. Initialises `_entry_price` from `_signal_price` captured at signal time (mirrors `ChandelierRiskModel`).
  - **ATR percentile filter** (`atr_percentile_min`, default 0): vetoes new entries when the current ATR is in the bottom N% of the session's ATR history (accumulated via `s.vars["atr"]` every candle, O(1)). Requires ≥ 20 samples before activating.
- **Cost gate injection default** changed from `0.0` → `0.05` in `backtest_runner.py` and `live_bot_manager.py`. The gate (`edge ≥ min_edge_mult × cost`) is now active by default; still overridable per-run via `risk_params["min_edge_mult"]`.
- **Portfolio exposure cap** (`max_portfolio_risk`, default 0.06): added to `DefaultPortfolioModel.construct()` — after sizing, vetoes the trade if `risk_per_unit × qty / equity > max_portfolio_risk`. Injected from `risk_params` in both runners. With default `risk_pct = 0.01`, the cap (6%) is never triggered → golden-master safe.
- All 5 golden master snapshots unchanged after workstream #2 (`ws2_final` == `baseline`, tol 1e-6). Boundary suite 20/20.

### Two-Phase Strategy Contract (`prepare()` + index-only `before()`)
- **`BaseStrategy.prepare(candles)`** (`core/strategy.py`): one-time vectorized indicator pre-computation. Default is a no-op (backward compatible). Migrated strategies move **all** TA-Lib/pandas calls here, storing results as `self._*` full-length arrays/scalars over the supplied `candles`.
- **`before()`** is then a pure index lookup at `self.index` — zero TA-Lib calls in the hot loop. This replaces the former O(N²) pattern (full indicator recompute on a growing `candles[:t+1]` slice every candle).
- **Backtest** (`services/backtest_runner.py`): the runner calls `strategy.prepare(candles_np)` once after param injection, before the sim loop. `strategy.index = t` (absolute index into the full array) aligns directly with the precomputed arrays.
- **Live** (`core/live_bot_manager.py`): `prepare()` is re-run on the rolling ≤500-candle window each closed candle (with `index = len-1`), then `before()` indexes — identical math to backtest, O(≤500)/candle (~once/hr), no float drift, no per-strategy incremental code.
- All 5 seeded strategies migrated (MicroMacroRSIDivergence, MultiDivergence, MicroScalper, BestSupertrend, AdaptiveTrend). No-lookahead preserved: divergence/pivot strategies bound the last-pivot search to the confirmation horizon `i - right`.

### UI / Navigation
- 6 nav pages + OrderHistory (at `/order-history`, not in navbar): Dashboard, Strategies, Backtest, Live Trading (Trade), Algo Trading, Settings
- Horizontal top navbar — no sidebar
- Active nav state: `text-emerald-400`, `bg-emerald-500/10`, `border-b-2 border-emerald-500`
- Dark theme throughout (`bg-gray-950` base)
- All financial P&L: `emerald-400` (profit) / `red-400` (loss)

---

## In Progress

None.

## Verified Baselines

### Narang Black-Box Refactor
- Verified in Docker on 2026-06-21.
- Golden snapshots refreshed for the current strict five-model pipeline (`baseline` and `modular_merger`).
- Verification commands:
  ```
  docker compose exec engine python -m scripts.golden_master run --label baseline
  docker compose exec engine python -m scripts.golden_master run --label modular_merger
  docker compose exec engine python -m scripts.golden_master compare --a baseline --b modular_merger
  docker compose exec engine python -m pytest tests/test_boundaries.py -q
  ```
- Results: golden comparison passed for all 5 seeded strategies; boundary regression suite passed 20/20.

### Strategy Performance Refactor (two-phase `prepare()`/`before()`)
- Verified in Docker on 2026-06-24. Branch `refactor/precompute-strategies` (merged to `dev`).
- Each of phases 1–6 gated on golden-master byte-equivalence vs `baseline` (tol 1e-6, all 5 strategies). Phase results recorded in `scripts/golden/phase1.json`…`phase6.json`.
- BestSupertrend (Phase 5) additionally verified for per-candle signal parity (0 diffs over the full golden range) — caught and fixed a latent pandas-2.x `datetime64[ms]` epoch-conversion bug in the HTF bucket mapping.
- Baseline metrics unchanged throughout: MicroScalper 9/-131.61 · AdaptiveTrend 7/+1543.91 · BestSupertrend 61/-117.56 · MicroMacroRSIDivergence 17/-273.30 · MultiDivergence 55/-1688.49. Boundary suite 20/20.

---

## Planned / Not Yet Implemented

| Feature | Notes |
|---------|-------|
| **Mainnet trading** | `fapi.binance.com` not implemented; all orders go to Testnet. Adding mainnet = swap base URL + mode selector in settings. |
| **Monte Carlo optimization** | `/optimize` engine endpoint not implemented. |
| **Multi-exchange support** | Binance only. |
| **Authentication** | Not implemented. The single-user model needs no login gate; add register/login + middleware only if multi-user support is ever introduced. |

---

## Known Technical Debt

- **Live bot PnL on exchange_sync exits**: when Binance closes a position via SL/TP and the engine detects it via reconciliation, the exit price is estimated from the local SL/TP prices. If neither SL nor TP was set, it falls back to current candle close. The user data stream (F-020) partially mitigates this by detecting fills in real-time. For exact fill prices an additional `GET /fapi/v1/userTrades` call would be needed (not yet implemented).
- **Live bot entry fee not tracked**: `session["pnl"]` only deducts the exit fee per trade. Entry fees paid to Binance are not subtracted locally, so session PnL overstates profits by one taker fee per round-trip. Acceptable approximation for now.

---

## Current Constraints

| Constraint | Detail |
|-----------|--------|
| Binance Testnet rate limits | Poll account (15s), positions (10s), open-orders (10s) — never lower these |
| Single-user | No `user_id` on any model, schema, or query |
| TA-Lib | Compiled inside Docker container — never install on host |
| No paper trading simulation | "Paper trading" = Binance Testnet; no internal order simulation |
| TimescaleDB isolation | Server never connects to TimescaleDB; all candle data comes via engine HTTP |
