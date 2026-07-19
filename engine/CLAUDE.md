# Enma — Engine (Python) Rules

> Inherits all rules from root `CLAUDE.md`.
> Read root CLAUDE.md first, then this file.

---

## Stack (engine-specific)

- Python 3.11
- FastAPI (latest stable)
- Uvicorn (ASGI server)
- TA-Lib (technical indicators — primary backend)
- pandas-ta-classic (optional pure-Python indicator fallback; pip package is `pandas-ta-classic`, lazily imported, never required at import time)
- httpx (async HTTP client — Binance REST: `/klines`, `/exchangeInfo`)
- websockets (Binance kline WebSocket streams for live bot)
- pandas + numpy (data processing)
- redis-py (progress publishing)
- optuna (TPE Bayesian hyperparameter search — `services/optimizer.py`'s `run_bayesian_optimization`, Plan 10 Phase 3b; pure-Python, no native build)
- motor (async MongoDB driver — `AsyncIOMotorClient`; pymongo is a transitive dep, do not use it directly)
- asyncpg (async PostgreSQL/TimescaleDB driver — candle reads/writes)
- python-dotenv
- pydantic v2 (request/response validation)
- **Dev:** pytest + pytest-asyncio

---

## Folder structure

```
engine/
├── core/
│   ├── constants.py          ← FUTURES_SYMBOLS (top 50, raw Binance e.g. BTCUSDT), SPOT_SYMBOLS placeholder, SUPPORTED_TIMEFRAMES, SUPPORTED_EXCHANGES
│   ├── strategy.py           ← BaseStrategy class — full interface (required + optional methods)
│   ├── params.py             ← typed strategy-parameter classes (IntParameter/FloatParameter/etc.) for the PARAMS declaration pattern
│   ├── position.py           ← Position class (futures: leverage, isolated margin, liquidation price)
│   ├── margin.py             ← Binance isolated-margin math (MMR tiers, liquidation_price, initial_margin)
│   ├── pipeline.py           ← unified decision pipeline (evaluate(s) runs Alpha -> Risk -> Cost -> Portfolio -> Execution — see workspace/docs/core/MODELS.md)
│   ├── kernel.py             ← ExecutionKernel/ExecutionAdapter — unifies backtest/live execution (F-024)
│   ├── models/               ← pluggable quant models: base.py (interfaces), risk.py, cost.py, portfolio.py,
│   │                            execution.py (defaults + variants), exec_algo.py (TWAP/VWAP/Iceberg, A-016),
│   │                            protections.py (CooldownPeriod/StoplossGuard/ProtectionManager)
│   └── live_bot_manager.py   ← manages in-memory live bot sessions; called by routers/algo.py
├── strategies/            ← strategy files live here (Docker volume — persists on host)
├── indicators/            ← pluggable indicator layer (DECISIONS.md #12)
│   ├── __init__.py        ← public façade: re-exports convenience fns (import engine.indicators as ta)
│   ├── base.py            ← IndicatorProvider ABC + active-provider singleton + convenience fns
│   ├── config.py          ← env-driven backend selection (ENMA_INDICATOR_LIBRARY) + auto-fallback
│   └── adapters/
│       ├── talib_adapter.py     ← TalibIndicatorProvider (default backend)
│       └── pandas_ta_adapter.py ← PandasTaIndicatorProvider (optional fallback)
├── routers/
│   ├── backtest.py        ← POST /backtest/run, POST /backtest/cancel
│   ├── candles.py         ← GET /candles/symbols, GET /candles/cached
│   ├── dashboard.py       ← GET /dashboard/stats, GET /dashboard/performance-calendar
│   ├── strategies.py      ← GET /strategies, GET /strategies/:name/code, PUT /strategies/:name/code
│   ├── trade.py           ← POST /trade/verify, GET /trade/account, GET /trade/positions, GET /trade/open-orders, POST /trade/leverage, POST /trade/margin-type, POST /trade/order, POST /trade/close-position, DELETE /trade/order, GET /trade/order, GET /trade/klines, /order/oco_futures
│   ├── algo.py            ← POST /algo/sessions, POST /algo/sessions/:id/stop, GET /algo/sessions/:id/status, POST /algo/sessions/:id/trading-state, POST /algo/pairlist/preview
│   ├── optimize.py        ← GET /optimize/objectives, POST /optimize/run, GET /optimize/:id/status, GET /optimize/:id/results (grid search — see services/optimizer.py)
│   ├── risk.py             ← Risk Intelligence Dashboard endpoints (settings, live metrics, overrides)
│   ├── leverage_sensitivity.py ← leverage-scenario simulation endpoints (Risk Dashboard Zone 3) — still the synchronous path SimulationResults.jsx uses; Plan 10 Phase 2 retires it
│   └── simulate.py        ← POST /simulate/monte-carlo (Plan 10 Phase 1 — job-based Strategy Lab robustness runs, writes labResults)
├── config/
│   ├── mongo.py           ← motor AsyncIOMotorClient (results, live sessions)
│   └── timescale.py       ← asyncpg connection pool (candle hypertable)
├── services/
│   ├── candle_importer.py  ← fetch OHLCV from Binance REST (/klines) via httpx, write to TimescaleDB
│   ├── candle_manager.py   ← ensure_candles_available(): single entry point for candle data
│   ├── funding_importer.py ← fetch historical funding rates from Binance REST (/fundingRate) via httpx, write to TimescaleDB (Plan 9 Step 9.7)
│   ├── funding_manager.py  ← ensure_funding_available(): single entry point for funding-rate data (Plan 9 Step 9.7)
│   ├── progress.py         ← publish progress to Redis pub/sub channel progress:{jobId}
│   ├── backtest_runner.py  ← backtest simulation loop (candle replay, fee/margin/SL-TP logic, metric computation)
│   ├── binance_testnet.py  ← HMAC-signed Binance REST requests; _BASE_URLS dict for testnet/mainnet
│   ├── pairlist.py         ← pairlist pipeline: VolumePairList → SpreadFilter / VolatilityFilter / PrecisionFilter / AgeFilter; config-based factory
│   ├── trade_recorder.py   ← record_trade() + build_trade_record(); writes completed round-trip trades to MongoDB tradeRecords (best-effort, never blocks close path)
│   ├── strategy_seeder.py  ← seeds default strategies on startup (idempotent)
│   ├── optimizer.py        ← parameter optimization: `run_optimization` (grid, itertools.product) + `run_bayesian_optimization` (Optuna TPE, ask/tell async loop, Plan 10 Phase 3b) — same objective registry, same `run_backtest_simulation` per trial, same ranked-results shape (`_finalize_optimization` shared tail) for both search methods. `_build_param_grid`/`_decode_combo_index` sample+decode combo indices directly rather than materializing the full cartesian product (Plan 10 Phase 3e fix — a strategy with several wide-range params can have a total combo count in the hundreds of trillions; the old `list(itertools.product(...))` hung/OOM'd the whole engine container, found via live UI testing). `_build_combined_grid` (Plan 10 Phase 4b, opt-in `risk_leverage_grid` param on both search functions) cartesian-multiplies a separate `risk_pct`/`leverage` grid against the strategy grid — namespaced apart from `alpha_params` (never merged), each trial carries its own `riskLeverage` alongside `params`.
│   ├── monte_carlo.py      ← Monte Carlo trade-sequence resampling; `run_monte_carlo_simulation()` (legacy sync path, Risk Dashboard) + `run_lab_simulation()` (Plan 10 Phase 1 — config-driven job version, writes labResults, called from routers/simulate.py) + `compute_mc_stats()`/`returns_from_trades()` (Plan 10 Phase 4a — Mongo-free pure extraction of the bootstrap core + trade→returns conversion, reused by `walk_forward.py`'s per-candidate MC scoring; `run_lab_simulation` is now a thin DB read/write wrapper around `compute_mc_stats`, behavior unchanged)
│   ├── walk_forward.py     ← walk-forward optimization (Plan 10 Phase 3a/3b/3d/3e/4a/4b) — `run_lab_walk_forward()`: splits a date range into candle-count folds, optimizes each fold's train window via `optimizer.run_optimization` (grid, default) or `optimizer.run_bayesian_optimization` (`method: "bayesian"`, Phase 3b — per-fold deterministic-but-distinct seed), evaluates OOS via `backtest_runner.run_backtest_simulation`, reports per-fold IS-vs-OOS Sharpe degradation + every trial scored (Phase 3d) + trade-level Deflated Sharpe Ratio (Phase 3e, `services/stats.deflated_sharpe_ratio`) + trade-level stitched-OOS aggregate. **Phase 4a** (opt-in `config.mcScoring`): OOS-evaluates a fold's top-`mcTopK` min-trades-eligible trials (`_eligible_trials`, not raw rank — see the file's own header comment) instead of only the winner, MC-scores each (`monte_carlo.compute_mc_stats`) and ranks by p5 profit (`fold.mcScoring.robustPick`/`.rawPick`). **Phase 4b** (opt-in `config.riskLeverageGrid`): `_override_bt_common` swaps in a trial's own searched risk_pct/leverage for its OOS evaluation instead of the job's flat default — applies to both the fold winner and Phase 4a's extra candidates. Writes labResults, called from routers/simulate.py's `POST /simulate/optimize`.
│   ├── stats.py            ← standard-normal primitives (`norm_cdf` exact via `math.erf`, `norm_ppf` Acklam's rational approximation + Halley refinement, numerically verified — no scipy dependency) + `deflated_sharpe_ratio()`/`expected_max_sharpe()` (Bailey & López de Prado 2014, Plan 10 Phase 3e — deferred across 4 prior Plan 10 sessions for lack of pytest access to verify the inverse-CDF primitive)
│   ├── leverage_sensitivity_runner.py ← runs leverage-scenario sweeps, writes BacktestLeverageScenario docs
│   ├── curves.py           ← equity/drawdown/rolling-metric curve computation for backtest results
│   ├── fill_model.py       ← adverse-slippage fill simulation shared by backtest/live execution
│   ├── metrics.py          ← backtest performance metric calculations; `SkewnessStat`/`KurtosisStat` (Plan 10 Phase 3e) added — trade-level (round-trip PnL) sample skewness / RAW (non-excess, 3.0=normal) kurtosis, feeds `stats.deflated_sharpe_ratio`; golden-master-verified additive-only (no existing metric changed)
│   └── user_data_stream.py ← Binance User Data Stream (listenKey create/keepalive/close, WS connection)
├── utils/
│   ├── timeframes.py      ← timeframe string conversions
│   ├── symbols.py         ← identity converters (to_ccxt_symbol etc.), load_exchange_rules(), round_price(), clamp_and_round_qty(), leverage-bracket lookup, is_symbol_invalid() (testnet-invalid symbol blacklist, 2026-07-03 — DECISIONS.md #22)
│   ├── rate_limiter.py    ← Binance per-IP rate-limit guard
│   └── risk_math.py       ← shared risk/notional/liquidation-buffer math helpers
├── scripts/
│   ├── golden_master.py   ← byte-equivalence check for pipeline refactors (root CLAUDE.md Rule C)
│   ├── enma_cli.py        ← data conversion CLI (Plan 15): list-data, export-candles, import-candles, export-trades — run via `python -m scripts.enma_cli <cmd>` inside the container; local-data only, never calls Binance
│   └── _io_formats.py     ← CSV/JSON read+write + row<->DB-record transforms for enma_cli.py (stdlib csv/json only, no new deps)
├── tests/
│   ├── test_boundaries.py ← service-boundary contract tests
│   ├── test_cli_roundtrip.py ← enma_cli.py export/import round-trip (hermetic — fake asyncpg pool + fake Mongo collection)
│   ├── test_lab_simulation.py ← run_lab_simulation() config/mode/seed/persistence tests (Plan 10 Phase 1)
│   ├── test_walk_forward.py ← fold-split conservation, anchored-vs-rolling, degradation ratio, stitched-OOS aggregate, per-fold trials persistence, method="bayesian" fold dispatch, per-fold DSR wiring tests (Plan 10 Phase 3a/3b/3d/3e), plus MC-scored top-K selection / `_eligible_trials` min-trades-filter correctness / insufficient-OOS-trades guard (Phase 4a) and risk_leverage_grid end-to-end fold wiring (Phase 4b)
│   ├── test_bayesian_optimizer.py ← Optuna TPE param-suggestion mapping, seeded reproducibility, known-optimum convergence, min-trades filter, error-path tests (Plan 10 Phase 3b)
│   ├── test_risk_leverage_search.py ← `_build_combined_grid` combinatorics + guardrail sampling, per-combo risk/leverage override reaching `run_backtest_simulation`, zero-behavior-change when `risk_leverage_grid` is omitted (Plan 10 Phase 4b)
│   ├── test_stats.py       ← norm_cdf/norm_ppf numerical verification (round-trip + published reference quantiles) + deflated_sharpe_ratio property tests (Plan 10 Phase 3e)
│   ├── test_skew_kurtosis.py ← SkewnessStat/KurtosisStat hand-computed-value tests (Plan 10 Phase 3e)
│   └── test_param_grid.py  ← `_build_param_grid`/`_decode_combo_index` tests, incl. the astronomically-large-grid regression guard (Plan 10 Phase 3e fix)
├── main.py                ← FastAPI app entry point
├── requirements.txt
└── .env
```

---

## BaseStrategy interface

Every user strategy MUST extend `BaseStrategy`. This is the contract.
Do not change this interface without a major version decision in DECISIONS.md.

**Narang Black-Box architecture (current):** All new strategies must define `forecast()` and bind
specific model instances. The legacy `should_long/go_long/should_short/go_short/update_position`
hooks are deprecated no-ops — they still exist on `BaseStrategy` for backward compatibility but must
NOT be defined on any new strategy.

```python
from engine.core.strategy import BaseStrategy
from engine.core.models import AtrBracketRiskModel, RiskBudgetPortfolio
from engine.core.models import Signal
import engine.indicators as ta

class MyStrategy(BaseStrategy):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.risk_model      = AtrBracketRiskModel()   # required: bind a specific risk model
        self.portfolio_model = RiskBudgetPortfolio()   # required: bind a specific portfolio model

    # PRIMARY — Alpha Model contract (required for Narang Black-Box strategies)
    def forecast(self) -> Signal:
        # While holding: return Signal(direction=current_dir) to maintain,
        #   or Signal(direction=0) to close, or Signal(direction=-current_dir) to flip.
        # While flat: return Signal(direction=1 or -1) to enter.
        if self.is_open:
            # maintain current position (Risk Model handles trailing)
            direction = 1 if self.is_long else -1
            return Signal(direction=direction)
        # entry logic
        if my_long_condition:
            return Signal(direction=1, ref_price=self.price)
        if my_short_condition:
            return Signal(direction=-1, ref_price=self.price)
        return Signal(direction=0)

    # Optional — cache indicator arrays for the candle
    def before(self) -> None:
        pass

    # Optional — called after each candle
    def after(self) -> None:
        pass

    # Optional — called when position opens
    def on_open_position(self, order) -> None:
        pass

    # Optional — called when position closes
    def on_close_position(self, order) -> None:
        pass

    # DEPRECATED — legacy hooks (default no-ops; do not define on new strategies)
    # should_long(), should_short(), go_long(), go_short(), update_position()
```

**Alpha boundary rules (enforced by `engine/tests/test_boundaries.py`):**
- `forecast()` must NOT read `self.balance`, `self.equity`, `self.position`, `self.session_drawdown`, etc.
- `forecast()` must NOT write `self.buy`, `self.sell`, `self.stop_loss`, `self.take_profit`, `self._close_at_open`, `self._pending_flip`
- `forecast()` must NOT call `size_by_risk`, `size_by_notional`, `go_long`, `go_short`, `flip_position`, `liquidate`, `trail_stop`, `move_to_breakeven`, `update_position`

**Available properties inside any strategy (from BaseStrategy):**
- `self.candles` — numpy array of OHLCV for current timeframe
- `self.price` / `self.close` — current closing price
- `self.open`, `self.high`, `self.low`, `self.volume`
- `self.position` — current Position object (qty, entry_price, pnl, etc.)
- `self.balance` — current wallet balance
- `self.equity` — balance + unrealized P&L of any open position
- `self.leverage` — account leverage for this run
- `self.is_long`, `self.is_short`, `self.is_open`, `self.is_close`
- `self.buy`, `self.sell` — set entry order: `self.buy = qty, price`
- `self.stop_loss` — set stop loss: `self.stop_loss = qty, price`
- `self.take_profit` — set take profit: `self.take_profit = qty, price`
- `self.liquidate()` — close position at market price
- `self.index` — candle iteration counter
- `self.vars` — dict for custom variables
- `self.risk_model` — pluggable `RiskModel` instance (default `DefaultRiskModel`)
- `self.portfolio_model` — pluggable `PortfolioModel` instance (default `DefaultPortfolioModel`)
- `self.cost_model` — pluggable `CostModel` instance (default `DefaultCostModel`)
- `self.execution_model` — pluggable `ExecutionModel` instance (default `DefaultExecution`)
- `self.informative_timeframes` — opt-in list of higher timeframes (default `[]`, DECISIONS.md #26). `self.htf(tf)` — as-of aligned, lookahead-safe base-length OHLCV for a declared timeframe; call only inside `prepare()` after `super().prepare(candles)`.

**Risk-based sizing & stop/target helpers (preferred over manual qty math — see DECISIONS.md #10):**
- `self.size_by_risk(stop_price, risk_pct=None)` — qty such that hitting `stop_price` loses `risk_pct` of equity (rule #6: `(equity*riskPct)/|entry-stop|`). Defaults `risk_pct` to `self.risk_pct`. Capped by `max_qty()`.
- `self.size_by_notional(pct=None)` — legacy fixed-fraction notional sizing (qty = equity*pct/price).
- `self.max_qty()` — largest qty the account's leverage allows (full equity as margin).
- `self.atr_stop(direction, mult, period)` — ATR-based stop price. `self.rr_target(direction, stop_price, rr)` — risk:reward take-profit.
- `self.trail_stop(atr_mult, period)` / `self.move_to_breakeven(buffer_pct)` — call inside `update_position()`; only ever tighten the stop, never loosen.
- `self.flip_position(qty, stop_loss=None, take_profit=None)` — **atomic close-and-reverse** (DECISIONS.md #11). Call inside `update_position()` while a position is open; the engine closes the current leg and opens the opposite one as a single unit with the given SL/TP armed immediately. If the new leg can't be afforded or a live order fails, the flip degrades to close-only (flat). **Never** write `self.buy`/`self.sell` while a position is open — that legacy pattern corrupts the open position's exit plan and is superseded by this primitive.

> Position object now carries `position.leverage`, `position.margin` (initial margin locked), and `position.liquidation_price`. `position.pnl_pct` is **return on margin (ROE)** so leverage is reflected.

---

## Indicator usage

```python
import engine.indicators as ta

# All indicators take a candles numpy array as first param
sma = ta.sma(self.candles, period=20)
rsi = ta.rsi(self.candles, period=14)
upper, middle, lower = ta.bollinger_bands(self.candles, period=20)

# For multi-timeframe (Plan 13 / DECISIONS.md #26): declare informative_timeframes,
# then call self.htf(tf) inside prepare() (after super().prepare(candles)) — returns
# an as-of aligned, lookahead-safe base-length OHLCV array, indexable at self.index
# exactly like self.candles.
class MyStrategy(BaseStrategy):
    informative_timeframes = ["1h"]

    def prepare(self, candles):
        super().prepare(candles)
        htf = self.htf("1h")
        self.vars["ema_1h"] = ta.ema(htf, period=50, sequential=True)
```

Available: `ema`, `sma`, `rsi`, `atr`, `donchian`, `macd`, `bollinger_bands`, `adx`, `stochastic`, `mfi`, `obv`, `pivot_high`, `pivot_low`.
Every function takes `(candles, period=…, sequential=False)`; `sequential=True` returns the
full NaN-padded numpy series instead of the latest float (tuple of arrays for multi-line
indicators).

**Pluggable backend (DECISIONS.md #12).** Strategies never import TA-Lib (or pandas-ta)
directly — they call these convenience functions, which delegate to the active
`IndicatorProvider`. TA-Lib is the default; set `ENMA_INDICATOR_LIBRARY=pandas_ta` to switch
the whole engine to the pure-Python backend with no strategy changes. If the chosen backend
can't load, the engine auto-falls-back (toggle with `ENMA_INDICATOR_FALLBACK`).

---

## Backtest engine rules

- Candle replay is strictly sequential — no lookahead
- Orders execute at the OPEN of the next candle after the signal candle
- **Isolated-margin futures model (see DECISIONS.md #10):** on entry the engine locks `initial_margin = notional / leverage` and rejects the trade if margin + fee exceeds balance (a rejected entry also clears the pending stop-loss/take-profit plan). Each open candle the position is checked against its `liquidation_price` (Binance isolated formula, `core/margin.py`) **before** stop-loss/take-profit; a liquidation forfeits **exactly the isolated margin** (loss is capped at margin — no exit fee or slippage is added on top) and records `exitReason="liquidation"`, `pnlPct=-100`.
- Exit priority each candle: **liquidation → stop-loss → take-profit**. When SL and TP both sit inside one candle, SL is assumed first (conservative).
- **Atomic flips (DECISIONS.md #11):** a `flip_position()` signaled on candle *t* executes at the OPEN of candle *t+1*, before that candle's exit checks — close old leg (`exitReason="flip"`), open opposite leg, arm the flip's SL/TP. An unaffordable second leg degrades to close-only; a pending flip is discarded if its position closes any other way first.
- Stop-loss and take-profit are checked on every candle's high/low (not just close)
- **Fees & slippage (configurable via database):** `fee_rate` is the TAKER rate; every modeled fill is a market fill. `slippage_pct` (default 0.05%) is applied adversely to every market fill. Parameters are injected per-run from the server (which reads Exchange Settings from MongoDB). Module-level constants remain as documented fallbacks if parameters are omitted. Funding is off by default (`funding_enabled=false`) and applied at 8h UTC boundaries when enabled via Exchange Settings — a positive rate means **longs pay, shorts receive**; `totalFunding` is net funding paid (negative = received).
- Metrics include `leverage`, `liquidations`, and `totalFunding` alongside the existing fields. Each persisted trade also carries `leverage` and `liqPrice`.
- Progress published to Redis every 100 candles (check interval also used for local cancel checks)
- Engine is the **sole writer** to `backtestResults` and `backtestTrades` MongoDB collections — server never writes metrics, trades, or equityCurve
- Trades are bulk-inserted in batches of 500 (`TRADE_INSERT_BATCH` = 500) into `backtestTrades` to stay safely under MongoDB BSON size limits
- Equity curve is downsampled to at most 1,000 points (`EQUITY_CURVE_MAX_POINTS` = 1000) using a linspace/rounding filter before MongoDB insertion
- Optimization: Metric calculations (drawdown, Sharpe, Sortino, PnL statistics) are vectorized using NumPy arrays rather than Python loop iterations
- Optimization: Cancellation checks are monitored asynchronously using a concurrent task subscribing to the Redis pub/sub channel `backtest:cancel:{jobId}` and flipping a local boolean flag, eliminating Redis network round-trip overhead inside the hot loop
- Progress message format: `"Simulating {symbol} {timeframe} — {pct}% ({current}/{total} candles)"` — always human-readable strings, never interpolate Python objects
- `ensure_candles_available()` in `services/candle_manager.py` is the **single entry point** for all candle data — never bypass it, never call `import_candles()` directly from a router or the simulation loop

---

## FastAPI rules

- All request/response bodies use Pydantic v2 models
- All endpoints return `{"success": true, "data": {...}}` or raise HTTPException
- Use `BackgroundTasks` for long-running operations — never block the event loop
- API key authentication via `X-API-Key` header on all routes
- Never expose stack traces in error responses in production

---

## Dashboard and candle cache endpoints

### GET `/candles/cached`

Implemented in `routers/candles.py`. Queries the TimescaleDB candles hypertable via asyncpg and returns one row per unique (exchange, symbol, timeframe, instrument_type) combination.

**Required SQL query (run via asyncpg connection pool):**
```sql
SELECT
    exchange,
    symbol,
    timeframe,
    instrument_type,
    MIN(time) AS start_date,
    MAX(time) AS end_date,
    COUNT(*) AS total_candles
FROM candles
GROUP BY exchange, symbol, timeframe, instrument_type
ORDER BY symbol, timeframe;
```

- `symbol` column in TimescaleDB uses the raw Binance format (`BTCUSDT`). Return as-is — no conversion needed.
- Dates returned as ISO 8601 strings (`start_date.isoformat()`).
- If the candles table is empty, return `{"cached": []}` — not an error.

### GET `/dashboard/stats`

Implemented in `routers/dashboard.py`. Reads `backtestResults` from MongoDB via motor and computes aggregations entirely in Python (no MongoDB aggregation pipeline required at this scale).

**Computation logic:**
- Filter: only documents with `status == "completed"` are included.
- `totalRuns`: count of completed documents.
- `averageNetProfit`: mean of `metrics.netProfit` across all completed runs (formatted to 2 decimal places as a string).
- `bestStrategy`: `strategyName` of the completed run with the highest `metrics.netProfit`.
- `leaderboard`: group completed runs by `strategyName`, compute per group:
  - `runs` (count)
  - `averageWinRate` (mean of `metrics.winRate`, 2 decimal string)
  - `averageNetProfit` (mean of `metrics.netProfit`, 2 decimal string)
  - `averageSharpe` (mean of `metrics.sharpeRatio`, 2 decimal string)
  - Sort leaderboard by `averageNetProfit` descending before returning.
- If no completed runs exist, return `stats: { totalRuns: 0, bestStrategy: null, averageNetProfit: "0.00" }` and `leaderboard: []`.

---

## Database connections

The engine connects to two databases. Connection configs live in `config/mongo.py` and `config/timescale.py`.

| Database | Driver | Config file | Owns |
|---|---|---|---|
| MongoDB | motor (`AsyncIOMotorClient`) | `config/mongo.py` | `backtestResults`, `liveSessions`, `tradeRecords` (engine is sole writer; server reads via Mongoose) |
| TimescaleDB | asyncpg (connection pool) | `config/timescale.py` | `candles` hypertable — all OHLCV data; `funding_rates` hypertable — historical Binance Futures funding events (Plan 9 Step 9.7) |

**TimescaleDB candles hypertable schema:**

```sql
CREATE TABLE candles (
    time             TIMESTAMPTZ     NOT NULL,
    exchange         TEXT            NOT NULL,
    symbol           TEXT            NOT NULL,
    timeframe        TEXT            NOT NULL,
    instrument_type  TEXT            NOT NULL,  -- 'spot' or 'futures'
    expiry           TEXT,                       -- NULL for spot/perpetual
    open             DOUBLE PRECISION NOT NULL,
    high             DOUBLE PRECISION NOT NULL,
    low              DOUBLE PRECISION NOT NULL,
    close            DOUBLE PRECISION NOT NULL,
    volume           DOUBLE PRECISION NOT NULL,
    quote_volume     DOUBLE PRECISION NOT NULL
);
SELECT create_hypertable('candles', 'time');
CREATE INDEX ON candles (exchange, symbol, timeframe, time DESC);
```

No `user_id` column — candles are shared globally across users.

**TimescaleDB funding_rates hypertable schema (Plan 9 Step 9.7):**

```sql
CREATE TABLE funding_rates (
    time             TIMESTAMPTZ  NOT NULL,  -- Binance's own fundingTime (irregular per symbol)
    exchange         TEXT         NOT NULL,  -- always "Binance Futures" — funding is a perpetual-futures-only mechanic
    symbol           TEXT         NOT NULL,
    funding_rate     NUMERIC      NOT NULL,  -- signed: positive = longs pay shorts
    mark_price       NUMERIC      NULL       -- mark price the fee was calculated against; NULL if Binance omitted it
);
SELECT create_hypertable('funding_rates', 'time');
CREATE UNIQUE INDEX ON funding_rates (time, exchange, symbol);
```

No `user_id` column — funding history is shared globally across users, same as `candles`.

**Rules:**
- **Never write candle data to MongoDB.** TimescaleDB is the exclusive candle store.
- **Never use pymongo directly** — use motor (`AsyncIOMotorClient`) for all MongoDB access.
- **All candle reads/writes** go through asyncpg (connection pool initialized at FastAPI startup in `main.py` lifespan).
- MongoDB writes for backtest results happen inside `services/backtest_runner.py` via motor.

---

## Candle importer rules

- **Entry point:** always use `ensure_candles_available()` in `services/candle_manager.py` — never call `import_candles()` directly from routers or the simulation loop
- **Symbol format:** all symbols are raw Binance uppercase strings (e.g. `BTCUSDT`). No conversion needed — pass the symbol directly to Binance REST and WebSocket APIs.
- **HTTP client:** use `httpx.AsyncClient` for all Binance REST calls (see `workspace/docs/core/binance-api.md` for endpoints `/klines`, `/exchangeInfo`, etc.). Never use ccxt.
- **Batch size:** 1000 candles per `fetch_ohlcv` call (Binance maximum — do not change)
- **Batch delay:** read `BINANCE_FETCH_DELAY_MS` from env, default 200ms — sleep between every batch call
- **Duplicate handling:** `INSERT ... ON CONFLICT DO NOTHING` — re-fetching the same range is always safe and idempotent
- **Candle retention:** candles are stored permanently in TimescaleDB — never delete them; they are reused across all future backtests for the same symbol/timeframe
- **Progress publishing:** publish to Redis pub/sub channel `progress:{jobId}` after every batch; shape: `{"pct": int, "message": str, "candlesFetched": int, "totalEstimate": int}`
- **No import record:** do NOT write to MongoDB `candleImports` collection — that collection is removed; candle fetch history is not tracked
- **Symbol list:** `FUTURES_SYMBOLS` and `SPOT_SYMBOLS` live in `core/constants.py`; `GET /candles/symbols` returns both

### instrument_type values

| Exchange | instrument_type value |
|---|---|
| `"Binance Futures"` | `"futures"` |
| `"Binance Spot"` | `"spot"` |

**Do not use `"perpetual"`** — the correct value for Binance perpetual futures is `"futures"`. Using `"perpetual"` causes a cache miss: `ensure_candles_available()` queries with `exchange = $1` (the exchange name string), and the TimescaleDB schema uses `"futures"` as the canonical value. A mismatch means existing candles are never found and the importer re-fetches on every backtest run.

### expiry column

- The `candles` hypertable has an `expiry TEXT` nullable column.
- The INSERT in `candle_importer.py` explicitly includes `expiry` in the column list and always inserts `NULL` for spot and perpetual futures.
- The full INSERT covers all 12 columns: `(time, exchange, symbol, timeframe, instrument_type, expiry, open, high, low, close, volume, quote_volume)`.
- Exchange-dated futures (quarterly contracts with a defined settlement date) will populate `expiry` as a date string in a future phase. For now it is always `NULL`.
- Do not omit `expiry` from the INSERT — implicit column omission would silently break if the column ever gained a `NOT NULL` constraint.

---

## TA-Lib

TA-Lib is built from source inside the engine Docker container. It is **not** installed on the host machine and **not** in any host setup instructions.

- The engine Dockerfile handles the full TA-Lib C library compilation before `pip install TA-Lib`
- If running outside Docker for any reason, TA-Lib must still be built from source — do not suggest conda or pre-built wheels in docs
- Never add a TA-Lib host-installation workaround to this file or any doc

---

## Strategy rules

- `BaseStrategy` is the contract — never change its interface without a DECISIONS.md entry.
- Strategy files are the source of truth — MongoDB is a metadata cache only.
- Seeder (`services/strategy_seeder.py`) runs on every engine startup but only creates missing strategies (idempotent — 5 seeded strategies: MicroScalper, AdaptiveTrend, BestSupertrend, MicroMacroRSIDivergence, MultiDivergence).
- Never import strategy files at module level — always use dynamic import at runtime.
- Strategies directory: `engine/strategies/` (inside Docker container, mounted as a named volume).
- Server never reads strategy files directly — always via `GET engine:8000/strategies/:name/code`.
- **Five-Model Architecture**: Each strategy acts as the **Alpha Model** in the pipeline. It holds pluggable instances for the other 4 models: `self.risk_model`, `self.portfolio_model`, `self.cost_model`, and `self.execution_model`.
- **Decision Pipeline**: Decisions are evaluated via `evaluate(s, current_holding)` in `engine/core/pipeline.py`, which executes Alpha `forecast()` → Risk `assess()` → TCM `estimate()` → PCM `construct()` → Execution `route()` every candle unconditionally (no early return for open positions).
- **Custom Models**: Subclass from base models in `engine/core/models/base.py` and assign custom instances in the strategy's `__init__` constructor.
- **Alpha contract**: Override `forecast() -> Signal` to return a `Signal(direction: int, conviction: float, ref_price: float)`. Alpha must not read account state or write orders — those are Risk/PCM/Execution responsibilities.
- **Model variants available** (`engine/core/models/`): `AtrBracketRiskModel`, `ChandelierRiskModel`, `SignalExitRiskModel`; `RiskBudgetPortfolio`, `NotionalPortfolio`; `DefaultTransactionCostModel`, `LadderedTransactionCostModel` (opt-in fill-model ladder — volatility-scaled slippage + √-impact, Plan 9 Step 9.10); `DefaultExecution`.
- **Boundary enforcement**: `engine/tests/test_boundaries.py` checks all 5 seeded strategies at test time.

---

## What Claude Code must NOT do in engine/

- Implement routing logic, auth, or database management for user accounts
- Call Binance API from routers — only from `services/candle_importer.py`, `services/funding_importer.py`, and `services/binance_testnet.py`
- Modify the BaseStrategy interface without a DECISIONS.md entry
- Use synchronous blocking calls inside async FastAPI routes
- Add pip packages not in requirements.txt without updating root CLAUDE.md (see root CLAUDE.md for platform-wide rules)
