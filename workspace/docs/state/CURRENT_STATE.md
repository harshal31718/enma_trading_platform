# ENMA — Current State

**Authority:** This is the single source of truth for what ENMA currently does.
Read this before starting any work. If this conflicts with chat history, this document wins.

Last updated: 2026-06-21

---

## Implemented Features

### Settings & Credentials
- **No authentication layer.** This is a single-user, self-hosted platform — there are no register/login endpoints, no auth middleware, and `/api/v1/auth/*` is never mounted (see `DEPRECATED.md` → "Removed Server Modules"). The `bcryptjs`/`jsonwebtoken` deps in `server/package.json` are currently unused; `client/src/store/useAuthStore.js` is orphaned scaffolding (no login UI consumes it).
- Binance API key storage: AES-256 encrypted, stored in MongoDB `Settings` collection
- Key verification against Binance Testnet on save
- **Exchange Settings**: Centralized configuration for trading fees, backtest defaults, bot defaults, simulation parameters (slippage, funding), and **risk-model defaults** (risk % per trade, reward:risk ratio, max session drawdown, liquidation buffer). All values stored as variables — no hardcoded numbers. Accessible via GET/PUT `/api/v1/settings/exchange`. Forms pre-fill from saved defaults.

### Strategy Management
- List all strategies (metadata: name, description, filePath)
- Create a new strategy (scaffolds file on disk + MongoDB metadata)
- View strategy source code (read-only modal)
- Extract strategy params (dynamic from Python file inspection)
- 5 strategies seeded on startup — each ported to the Narang Black-Box architecture (defines `forecast()`, binds specific risk/portfolio model, does not own `go_long`/`go_short`/`update_position`):
  - `MicroScalper` — `AtrBracketRiskModel` + `RiskBudgetPortfolio`; volatility-gated momentum crossover; flips while holding
  - `AdaptiveTrend` — `ChandelierRiskModel` + `RiskBudgetPortfolio`; regime-aware trend follower with chandelier trailing exit
  - `BestSupertrend` — `SignalExitRiskModel` + `NotionalPortfolio`; multi-timeframe Supertrend + SMA crossovers; closes via `_close_at_open` (intentional behavioral change from prior `liquidate()`)
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
- Equity curve stored (downsampled to ≤1,000 points) with client-side Buy & Hold benchmark overlay
- Trades stored in `backtestTrades` collection (split to avoid BSON limits, batch-inserted in groups of 500), including per-trade run-up (MFE), drawdown (MAE), and bars held
- Paginated trade history in result view, showing Run-up, Drawdown, and Bars columns
- Cancel in-progress backtest (Redis cancel flag)
- Deep-link to any result via `?jobId=` query param
- Vectorized metric calculations using NumPy (drawdown, Sharpe, Sortino, Calmar, gross profit/loss, profit factor, expectancy, payoff ratio, streaks, and buy & hold benchmark)
- Detailed tabbed report UI: Overview (Headline cards + Equity/Drawdown/Benchmark chart + Config summary), Performance Summary (comparative All / Long / Short table), and List of Trades (log table with excursions)
- BacktestConfigForm pre-fills capital and leverage from Exchange Settings defaults

### Dashboard
- Total runs, best strategy, average win rate stats
- Strategy leaderboard (per-strategy averaged metrics, sorted by win rate)
- Recent activity table (last 5 completed backtests with deep-link to results)
- Cached candles table (TimescaleDB inventory: symbol, timeframe, exchange, type, date range, count)

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
- Live PnL tracking per session
- Open position tracking
- Session status updates emitted via Socket.IO (`algo:session:update`)
- Position open/close events emitted via Socket.IO
- Symbol lock enforcement (bot-locked vs manual-locked)
- **Fee rate read from settings**: Live bot reads `takerFee` from Exchange Settings and applies it to position exit calculations
- **UI-configurable risk model**: NewSessionWizard exposes the 4 risk fields (pre-filled from global defaults, overridable per session). The server resolves and forwards them as `risk_params` to the engine, which injects them onto each per-symbol strategy instance in `live_bot_manager._run_symbol_loop` (slippage left at default — live uses real fills). Persisted on the `liveSessions` doc
- **Unified Decision Pipeline**: Live sessions evaluate signals through `pipeline.evaluate()`, running the canonical Alpha → Risk → Portfolio → Cost → Execution quant pipeline, enabling live drawdown-breaker and cost gating.
- Stop a running session

### Technical Indicators (engine/indicators/) — pluggable backend
- **Implemented:** `ema`, `sma`, `rsi`, `atr`, `donchian`, `macd`, `bollinger_bands`, `adx`, `stochastic`, `mfi`, `obv`, `pivot_high`, `pivot_low` (the last two are library-agnostic swing-pivot detectors — TradingView `ta.pivothigh`/`pivotlow` — usable on any candle column; the shared `_compute_pivots` primitive also detects pivots on arbitrary indicator series)
- All indicators: `sequential=False` (default, returns latest float / tuple of floats), `sequential=True` (full NaN-padded array / tuple of arrays)
- **Pluggable provider architecture** (DECISIONS.md #12): strategies call the convenience functions (`import engine.indicators as ta`); calls route through a swappable `IndicatorProvider`. **TA-Lib** is the default backend; **pandas-ta** is a pure-Python fallback (optional dependency, lazily imported). Switch the whole engine with `ENMA_INDICATOR_LIBRARY=talib|pandas_ta`; if the chosen backend fails to load, the engine auto-falls-back (`ENMA_INDICATOR_FALLBACK`, default on). No strategy changes needed to swap libraries.
- Files: `base.py` (interface + convenience fns), `config.py` (backend selection), `adapters/talib_adapter.py`, `adapters/pandas_ta_adapter.py`

### UI / Navigation
- 6 pages: Dashboard, Strategies, Backtest, Live Trading (Trade), Algo Trading, Settings
- Horizontal top navbar — no sidebar
- Active nav state: `text-emerald-400`, `bg-emerald-500/10`, `border-b-2 border-emerald-500`
- Dark theme throughout (`bg-gray-950` base)
- All financial P&L: `emerald-400` (profit) / `red-400` (loss)

---

## In Progress

**Narang Black-Box refactor — golden master gate pending (2026-06-21).**
All implementation is complete. Must run in Docker before declaring done:
```
docker compose exec engine python -m scripts.golden_master run --label modular_merger
docker compose exec engine python -m scripts.golden_master compare --a baseline --b modular_merger
docker compose exec engine python -m pytest engine/tests/test_boundaries.py -q
```
BestSupertrend will show intentional drift (`liquidate()` → `_close_at_open`) — snapshot a new baseline for it and document in `DECISIONS.md`.

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

| Item | Detail |
|------|--------|
| Unused auth deps | `bcryptjs` + `jsonwebtoken` are in `server/package.json` but no server code uses them; `client/src/store/useAuthStore.js` is orphaned. Remove if multi-user is never planned. |

---

## Current Constraints

| Constraint | Detail |
|-----------|--------|
| Binance Testnet rate limits | Poll account (15s), positions (10s), open-orders (10s) — never lower these |
| Single-user | No `user_id` on any model, schema, or query |
| TA-Lib | Compiled inside Docker container — never install on host |
| No paper trading simulation | "Paper trading" = Binance Testnet; no internal order simulation |
| TimescaleDB isolation | Server never connects to TimescaleDB; all candle data comes via engine HTTP |
