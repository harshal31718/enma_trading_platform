# ENMA — Current State

**Authority:** This is the single source of truth for what ENMA currently does.
Read this before starting any work. If this conflicts with chat history, this document wins.

Last updated: 2026-07-01 (Auth branch — Phases 1–5 complete)

---

## Implemented Features

### Auth & Access Control (Auth Branch — active)
- **Google OAuth 2.0** via Passport.js (`passport-google-oauth20`), sessionless. Flow: `/api/v1/auth/google` → Google → `/api/v1/auth/google/callback` → JWT cookie set → redirect to `/`.
- **JWT in `httpOnly` cookie** (`enma_jwt`, `sameSite: lax`, 7-day expiry). Verified by `verifyJWT` middleware globally applied at `app.use('/api/v1', verifyJWT)` (auth routes excluded).
- **Email whitelist** — `PlatformConfig` MongoDB singleton (`_id: 'platform'`) stores allowed emails. Users not on the list are redirected to `/login?error=not_invited`. Admin email (`admin.enmaquant@gmail.com`) is auto-promoted to `role: 'admin'` on first login.
- **User model**: `User.js` with `googleId`, `email`, `name`, `avatar`, `role` (`user`|`admin`), `isActive`.
- **Admin panel**: `GET/POST/DELETE /api/v1/admin/allowed-emails` — admin-only, guarded by `requireAdmin` middleware. Client: `/admin` route, visible only to admin users in the Navbar.
- **Per-user Settings**: `Settings` model scoped by `userId` (string). Each user's exchange settings, risk defaults, chaos settings, and encrypted Binance keys are stored per-user. `_getOrCreate(userId)` upserts on first access.
- **Socket.IO rooms**: All `io.emit()` replaced with `io.to('user:' + userId).emit()`. Clients join their room on auth via `verifyJWT` in the Socket.IO auth handler.
- **Client auth**: `useAuth()` hook (TanStack Query, `GET /api/v1/auth/me`, 5-min stale, 401 returns null silently). `ProtectedLayout` in `App.jsx` — spinner while loading, redirect to `/login` if not authenticated, then renders Navbar+Outlet. Navbar shows Google avatar, user name, Admin link (admin only), and logout button.
- **Axios/Socket**: Both have `withCredentials: true` to send the `httpOnly` cookie cross-origin.

### Settings & Credentials
- Binance API key storage: AES-256 encrypted per-user, stored in MongoDB `Settings` collection
- Key entry in Settings page (`POST /api/v1/trade/settings/keys`), status indicator shows if keys are saved
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
- **Phase 2 Metrics & Realism**: Backtesting uses a pluggable statistic registry (`StatisticRegistry` in `engine/services/metrics.py`) providing CAGR, SQN, expectancyRatio, drawdown duration (`maxDrawdownDurationCandles`), and exit-reason breakdown tables (`byExitReason`). Stored on MongoDB backtest results are additional analytics curves and datasets: Underwater/drawdown curve (`underwaterCurve`), Returns histogram (`returnsHistogram`), MFE/MAE scatter (`mfeMaeScatter`), and rolling Sharpe/volatility curves (`rollingMetricsCurve`). Fills model gap-through stops (fill at candle OPEN when range gaps stop-loss, `gap_through_stop_price()`) and candle-bounded exit fills (`bounded_exit_price()`) are implemented for realistic backtest execution. Metric definitions corrected by the standardise audit: **Calmar** = CAGR (annualized return) over max drawdown (not total return — I-08); **Sortino** measures downside deviation against a 0 target over all periods, freqtrade-equivalent (I-09); **ProfitFactor**/**PayoffRatio** return `inf` for a no-loss run instead of `0.00` (I-13); take-profit prices round **away** from entry like stops, on both backtest and live paths (I-11).
- **Multi-Symbol Backtesting — shared wallet (F-017)**: The backtest runner supports comma-separated symbols (e.g., `BTCUSDT,ETHUSDT`). Multi-symbol runs use a **shared-wallet portfolio model** (`_run_shared_portfolio()` in `backtest_runner.py`): all symbols advance together in timestamp order against ONE balance with shared isolated margin — every position competes for the same capital, mirroring multi-symbol live, rather than running each symbol independently on pre-split capital. Entry affordability checks **free capital** (`balance − Σ open-position margin`, via `strategy._external_reserved_margin`). Portfolio equity (cash + all open unrealized PnL) is recorded once per timestamp; trades are chronologically merged with sequential IDs; portfolio-wide metrics are computed over the combined curve/trade list. **Single-symbol runs use the original per-symbol loop, verified golden-master byte-identical.** (Audit I-06.)
- **Unified Execution Kernel (F-024)**: Unifies the execution driver loops for both backtest simulation (`backtest_runner.py`) and live websocket trading (`live_bot_manager.py`) into `ExecutionKernel` in `engine/core/kernel.py`. The kernel uses a Callback/Adapter pattern via `ExecutionAdapter` (implemented as `BacktestAdapter` and `LiveAdapter`) to execute entry, exit, and flip transitions. This ensures perfect backtest-live execution parity and prevents driver-level asymmetries.
- **Pluggable Execution Algorithms (A-016)**: Introduces support for TWAP, VWAP, and Iceberg execution algorithms in `engine/core/models/exec_algo.py`. The execution algorithms intercept the `OrderPlan` generated by the pipeline's `evaluate()` call and slice the parent order. The kernel routes the **first slice as the entry** and **every subsequent slice through the position-adjust (add) path**, so the algorithm fills the **full parent quantity** across candles instead of only its first slice (slices 2..N were previously dropped because the entry path only fills while flat). (Audit I-01.)

### Phase 5 — State Truth & Reconciliation
- **Unified Exchange Reconciliation (F-001/F-002/F-004)**: New `_reconcile_exchange_state()` in `live_bot_manager.py` queries Binance directly for position AND open orders every loop, unconditionally. Handles 3 cases: restores orphan positions, closes stale local state, and updates unrealised PnL from exchange mark price. Runs before any exit/entry decision — self-healing when engine wrongly believes it is flat. **Orphan-position restore (I-07)** rebuilds the position with exchange-truth `leverage` / `isolatedWallet` / `liquidationPrice` from positionRisk (not a bare `leverage=1` position) and re-arms `stop_loss`/`take_profit` + `algo_ids` from the open algo orders, so a restored position is protected and OUO peer-cancel (F-019) can fire for it.
- **Open Orders Reconciliation (F-002)**: `_reconcile_exchange_state()` fetches both standard `/fapi/v1/openOrders` and conditional `/fapi/v1/openAlgoOrders` (SL/TP) each loop. Filled/cancelled orders are detected between candle closes via the Binance user data stream.
- **Exchange-Reconciled Position Record (F-021)**: `positionDetails` on `LiveSession` is now sourced from exchange-truth reconciliation. `_push_stats()` sends mark_price, unrealized_pnl, and price_missing flag per symbol. `handleEngineStats` stores these in MongoDB. Client `SessionCard` uses exchange-reported `unrealized_pnl` first, falling back to local calculation with mark price, then last price.
- **User Data Stream (F-020)**: New `services/user_data_stream.py` — `UserDataStreamManager` singleton creates a Binance Futures listen key, connects to `wss://fstream.binancefuture.com/ws/{listenKey}`, processes `ORDER_TRADE_UPDATE` events in real time. Auto-reconnect with exponential backoff, 30-minute keep-alive. Registered per-symbol callbacks from `_run_symbol_loop` trigger immediate reconciliation on fill events.
- **Direct Binance Placement (F-003)**: Algo order placement now calls `send_signed_request()` directly from the engine for entry, exit, and stop-close — eliminating the engine→Node→engine→Binance hop chain. Affected methods: `execute_entry()`, `execute_exit()`, `_close_position_on_stop()`, `_reconcile_exchange_state()`.
- **Mark-Price PnL Fallback Chain (F-023/A-013)**: Live PnL uses exchange-reported `unRealizedProfit` from positionRisk as primary source. Mark price is parsed as optional (not coerced to `0`) with a fallback chain: `markPrice` → cached 24h last price → engine last close. The `price_missing` flag is set only when no source yields a usable price (audit I-05 — the flag was previously dead because `markPrice` was always coerced to a float; a legitimate `0.0` PnL is now preserved, not dropped). Propagated through `positionDetails` to the UI.

### Phase 6 — SL/TP & OCO Robustness
- **Emergency Market Exit on SL Placement Failure (F-018)**: In `LiveAdapter.execute_entry()`, if a stop-loss conditional order fails to place after a MARKET entry fills, the engine immediately sends a MARKET close order to Binance, records the trade with `exit_reason="emergency_exit"`, and returns `False`. This prevents the position from running naked — matching freqtrade's `emergency_exit()` pattern. Trade is fully accounted (PnL at entry price minus exit fees) and notified to Node as a `position:close` event.
- **OUO Partial-Fill Peer-Cancel (F-019)**: Algo order IDs for SL and TP legs are tracked in `session["open_positions"][symbol]["algo_ids"]` after placement. Two OUO safety nets prevent over-close when one leg partially fills: (1) in the user data stream `_on_fill` callback, when a tracked `tpsl_*` algo order reports `FILLED` or `PARTIALLY_FILLED`, the peer leg is immediately cancelled via `DELETE /fapi/v1/algoOrder`; (2) in `_reconcile_exchange_state()`, the tracked algo IDs are cross-checked against the exchange's open algo orders — if one leg is missing (triggered/filled), the peer is cancelled. This mirrors nautilus `ContingencyType.OUO` semantics for Binance conditional orders with `closePosition: "true"`.

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

### Phase 7 — Pair Management
- **Unified Symbol Source (F-009)**: The engine's `GET /candles/symbols` now returns a `all` field containing every TRADING symbol from the cached Binance exchangeInfo, enriched with volume-based tiers (`high`/`mid`/`low` computed from 24hr quoteVolume), base/quote asset, and status. `load_symbol_volume_tiers()` runs at engine startup to populate the tier + ticker cache (`_volume_tier_cache`, `_ticker_cache`). The server's `symbolService.js` fetches from the engine on startup (5-minute TTL cache) with `top_symbols.js` falling back to a static 80-symbol list when the engine is unreachable. `getChaosSymbols()` and `startChaos()` now use the dynamic tiered list instead of the static `TIERED_SYMBOLS`. The client's `SYMBOL_LIMITS` is trimmed to 4 core symbols (BTC/ETH/SOL/BNB) as a minimal offline fallback — live rules from the engine are the primary source.
- **Dynamic Pairlist Pipeline (A-004)**: New `engine/services/pairlist.py` provides a composable pairlist system with `VolumePairList` (generator, ranks by 24h `quoteVolume` descending — audit I-02), `SpreadFilter` (drops wide bid/ask spreads using the **book-ticker** cache, since the 24hr ticker carries no bid/ask for USDⓈ-M futures — audit I-03), `VolatilityFilter` (keeps pairs within a 24h high/low volatility band), `PrecisionFilter` (drops pairs where `tickSize / price` exceeds a threshold, making stop placement unreliable — audit I-04), and `AgeFilter` (drops pairs listed fewer than `min_days_listed` days using exchangeInfo `onboardDate` — audit I-12). A config-based factory `pairlist_from_config()` builds `PairlistPipeline` instances from session config. In `live_bot_manager.start_session()`, if `symbols` is empty and `risk_params.pairlist` is configured, the pipeline generates the symbol list dynamically. A preview endpoint at `POST /algo/pairlist/preview` (proxied via server at `POST /api/v1/algo/pairlist/preview`) lets users test pairlist configurations without starting a session.
- **Ticker / Book-Ticker / Listing caches**: `load_symbol_volume_tiers()` populates `_ticker_cache` (highPrice, lowPrice, volume, quoteVolume, priceChangePercent, and now `lastPrice` + `weightedAvgPrice`) from the 24hr ticker. A separate `load_book_tickers()` populates `_book_ticker_cache` (best bid/ask from `/ticker/bookTicker`) — both run at engine startup. exchangeInfo `onboardDate` is cached in symbol metadata. Consumed by the pairlist filters. Exposed via `get_ticker_data()`, `get_book_ticker()`, and `get_symbol_onboard_date()`.

### Phase 8 — Parameters & Optimization
- **F-015/F-016 — Reject (not silently clamp/drop) params**: Backtest and live param injection now raises `ValueError` with a clear message when a param is out of range or unknown (instead of silently clamping or dropping). The same validation applies to both dict-style and typed PARAMS.
- **A-005 — Typed Self-Validating Parameters**: New `engine/core/params.py` with `IntParameter`, `FloatParameter`, `DecimalParameter`, `CategoricalParameter`, and `BooleanParameter` classes — bounds validated at construction, type coercion, and `.to_dict()` for server API consumption. Backward-compatible shared helpers (`param_coerce`, `param_validate`, `param_default`, `param_to_dict`) work with both typed and legacy dict-style PARAMS.
- **A-006 — Parameter Optimization Run Mode**: New `engine/services/optimizer.py` — grid search over parameter combinations (int step/range, float linspace, categorical values, random subset support). 8 objective functions (sharpe, sortino, calmar, profit, profit_pct, drawdown, sqn, multi). Results persisted to MongoDB `optimizationResults` collection. New router at `engine/routers/optimize.py` — endpoints: `GET /optimize/objectives`, `POST /optimize/run`, `GET /optimize/{id}/status`, `GET /optimize/{id}/results`.

### Phase 9 — Strategy Mechanisms (DCA, Entry/Exit Tagging)
- **A-014 — Position Adjustment / DCA**: `Position` model (`engine/core/position.py`) gains two new methods — `add_qty()` (scale-in: recalculates average entry price, merges fees) and `reduce_qty()` (partial close: returns realized P&L without removing the position). `Strategy` (`engine/core/strategy.py`) gains an `adjust_trade_position()` hook (returns `(qty_delta, tag) | None`), modeled after freqtrade's DCA pattern. The unified `ExecutionKernel` evaluates the hook in `evaluate_and_route()` when an open position exists: if the strategy returns a non-zero qty delta, the kernel sets `strategy.qty_to_adjust` and routes it through the adapter. `BacktestAdapter.execute_entry()` handles `intent="add"` by calling `Position.add_qty()` instead of creating a new Position. New `execute_reduce()` on both adapters handles partial close via `Position.reduce_qty()`, recording a synthetic partial-exit trade. **Backward compatible**: strategies that don't override `adjust_trade_position()` return `None` — zero behavior change.
- **A-015 — Entry/Exit Tagging End-to-End**: `Signal` (`engine/core/models/base.py`) gains optional `entry_tag` and `exit_tag` fields — set by the strategy in `forecast()` (entry_tag) or in `adjust_trade_position()`/exit signal (exit_tag). `OrderPlan` gains `intent` ("enter"|"add"|"reduce"|"exit") and `entry_tag` for traceability through the pipeline. Tags propagate to `build_trade_record()` in `engine/services/trade_recorder.py` and are persisted on both `backtestTrades` and `tradeRecords` via `BacktestTrade.entryTag`/`exitTag` and `TradeRecord.entryTag`/`exitTag` (server models). Enables per-tag analytics (A-008 per-tag breakdown) — signals can now be labeled and analyzed independently.


### UI / Navigation
- 6 nav pages + OrderHistory (at `/order-history`, not in navbar): Dashboard, Strategies, Backtest, Live Trading (Trade), Algo Trading, Settings
- Horizontal top navbar — no sidebar
- Active nav state: `text-emerald-400`, `bg-emerald-500/10`, `border-b-2 border-emerald-500`
- Dark theme throughout (`bg-gray-950` base)
- All financial P&L: `emerald-400` (profit) / `red-400` (loss)

### UI Polish & Hardening (Phase 2)
- **Toast Notifications**: Centralized toast alert system powered by `react-hot-toast` configured with midnight-blue styling. Emits success/error toasts for Settings (Exchange, Chaos, API keys), Strategy creation/cloning, Backtest run queues/completions/failures, and live Algo bot session controls (Start/Stop/Delete, Clear stopped, Chaos mode).
- **ARIA & Accessibility Sweep**: Semantic markup and screen-reader accessibility sweep completed:
  - Icon-only NavLinks (e.g. Settings) and control buttons (Filters, Refresh, Select run) tagged with explicit `aria-label`.
  - Combobox and listbox search controls in SymbolSearchBar set with proper `role`, `aria-expanded`, `aria-autocomplete`, and `aria-selected` tracking active list items.
  - Algo SessionCard controls linked with `aria-busy` (for pending stops) and `aria-expanded` (for accordion chevrons).
  - Timeframe selector buttons explicitly configured with `aria-pressed`.
  - Param form inputs associated with labels using `id` and `htmlFor` bindings.
- **Background Polling Indicators**: Destructured `isFetching` from query hooks and mapped active background refreshes to small, non-obtrusive pulsating status dots next to bottom panel tabs (Positions, Orders, History) and the Algo Trading page header.
- **Dynamic Table Sorting**: Wired client-side column sorting via the `useTableSort` state hook and `<SortableHeader>` UI components in RecentActivityTable, StrategyLeaderboard, and CachedCandlesTable.
- **Richer Empty States**: Replaced all generic centered text placeholders with the styled, interactive `<EmptyState>` component across Trade tabs, Backtest runs history, Strategies, and the Admin whitelist email log.

- **UI Polish & Responsiveness (Phase 3)**:
  - **Code Quality & Refactoring**:
    - Migrated local state equity fetching in `SessionCard.jsx` to a TanStack Query `useQuery` hook with automatic enabled/disabled state on accordion toggle. Reactive close positions socket events update the query cache via `queryClient.setQueryData`.
    - Converted custom overlays (TP/SL, Leverage) in `Trade.jsx` to Radix-based `<Dialog>` components to guarantee focus trapping.
    - Surfaced console error catches into real-time user-facing toast alerts on the live Algo bot dashboards.
    - Enabled lazy loading (`React.lazy()`) and `<Suspense>` wrappers on heavy visual sub-components (`CorrelationHeatmap`, `AggregateMarginGauge`, `NetExposureBar`, `SimulationResults`, `BacktestCalendar`, `NewSessionWizard`, `NewBacktestWizard`, `ChaosWizard`) to decrease initial chunk loads.
  - **Design System Sweep**:
    - Created a shared `<Badge>` component in `client/src/components/ui/badge.jsx` with logical aliases (`long`/`short`, `buy`/`sell`, `running`/`stopped`, `bot`/`manual`) mapping to correct HSL color tokens.
    - Replaced raw container divs with `<Card>` panels inside `StrategyCard.jsx` and `AdminPanel.jsx`.
    - Standardized form submit and control buttons to standard `<Button>` components in `Settings.jsx`.
    - Updated raw skeletons (`AlgoTrading.jsx`, `NewSessionWizard.jsx`, `NewBacktestWizard.jsx`) from raw grays to the midnight-approved `bg-slate-800/50` / `bg-slate-800/20` class tokens.
  - **Mobile Responsiveness**:
    - Refactored `Trade.jsx` to use a responsive tab bar layout selecting between Chart, Order Book, Recent Trades, and Order Form on viewports below `1024px` while keeping the desktop side-by-side terminal intact.
    - Wrapped tables (`PositionsTable` and `OpenOrdersTable`) in `overflow-x-auto` layouts to prevent text clipping.
    - Added responsive columns (`grid-cols-2 sm:grid-cols-4 lg:grid-cols-7` and `grid-cols-1 sm:grid-cols-2`) to backtest metric grids and wizards.

---

## In Progress



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

### Standardise Implementation Audit (2026-06-25)
- A verification pass cross-checked the 40 standardise items (`workspace/standardise/`, since removed) against the code and the freqtrade/nautilus reference logic. It found 13 issues where items were marked done but were broken, partial, or unfaithful — all fixed and verified:
  - **I-01** exec algos (TWAP/VWAP/Iceberg) dropped slices 2..N → now fill the full parent via the add-path.
  - **I-02/03/04/12** pairlist filters were inert/wrong (alphabetical rank, bid/ask absent on futures 24hr ticker, `tick/100` no-op, AgeFilter placeholder) → volume rank, book-ticker bid/ask, `tick/price`, onboardDate age.
  - **I-05** `price_missing` flag was permanently false → real optional parse + fallback chain.
  - **I-06** multi-symbol backtest was N isolated split-capital runs → shared-wallet portfolio.
  - **I-07** orphan-position restore lost leverage/margin/brackets → exchange-truth restore.
  - **I-08/09/13** Calmar/Sortino/ProfitFactor metric-definition errors → corrected.
  - **I-10** dead `bounded_entry_price` + misleading docstring → cleaned.
  - **I-11** take-profit rounded toward entry → rounds away, both paths.
- Verification: engine unit suite **81/81** (4 new test files: `test_exec_algo_slicing`, `test_metrics_fixes`, `test_pairlist_fixes`, `test_reconcile_fixes`); golden master confirms **single-symbol backtests byte-identical** while metric changes are confined to the intended fields; a 2-symbol integration check (`scripts/_portfolio_check.py`) verifies the shared-wallet path end-to-end. Changes take effect on engine restart/rebuild (no bind mount).

---

## Planned / Not Yet Implemented

| Feature | Notes |
|---------|-------|
| **Mainnet trading** | `fapi.binance.com` not implemented; all orders go to Testnet. Adding mainnet = swap base URL + mode selector in settings. |
| **Multi-exchange support** | Binance only. |

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
