# Enma — Major Architectural Decisions

> This document tracks the final, major architectural decisions for the platform.
> Minor bug fixes, refactors, and daily changelogs should not be added here to preserve context size for AI agents.

## 1. Technology Stack
**Decision:** MERN (MongoDB, Express, React, Node.js) + Python FastAPI (Engine) + TimescaleDB + Redis.
**Rationale:** Node/React for fast UI development, Python for quantitative libraries (TA-Lib, numpy/pandas) and native HMAC-signed REST via httpx, TimescaleDB for massive time-series candle data, Redis for queues and pub/sub.

## 2. Database Responsibilities (Three-DB Architecture)
**Decision:** Use three databases, each optimized for its domain:
- **MongoDB:** Metadata (strategies, backtestResults, liveSessions, settings).
- **TimescaleDB:** Pure OHLCV time-series candle data via hypertables.
- **Redis:** BullMQ job queues, live session cache, pub/sub progress streaming.
**Rationale:** Keeps the document store lean and offloads time-series read/writes to PostgreSQL (TimescaleDB).

## 3. Local Development Architecture
**Decision:** Fully containerized via Docker Compose (`client/`, `server/`, `engine/`, plus DBs).
**Rationale:** Isolates complex dependency chains (especially TA-Lib and Python binaries) to ensure identical setups across environments.

## 4. Backtest Engine Data Flow
**Decision:** The Python Engine is the sole writer for `backtestResults` and `backtestTrades` during simulations. The Node server only manages the job state and proxies requests.
**Rationale:** Eliminates race conditions and double-writes. Engine handles computationally heavy vectorized metrics (NumPy) and inserts directly to MongoDB.

## 5. Live Trading Integration
**Decision:** Manual signed REST calls via Express-to-Engine proxy, plus a shared Binance WebSocket connection in the client.
- **REST:** Node passes credentials via headers; Python signs and executes trades.
- **WebSocket:** Client connects to Binance directly for public tick data to bypass server bottleneck.
- **Sync:** Client polls the backend (account: 15 s, positions: 10 s, open-orders: 10 s) to reconcile account state, margin, and positions. Intervals are intentionally conservative to stay inside Binance Testnet rate limits.
**Rationale:** Decouples high-frequency market data from sensitive signed account mutations.

## 9. Binance Environment Model — Testnet vs Mainnet (no internal paper-trading simulation)
**Decision:** The platform has exactly two Binance environments:
- **Testnet** (`demo-fapi.binance.com`): Fake money. Used for all development, testing, and demo trading. ALL algo bot orders, Trade page orders, and account queries go here today.
- **Mainnet** (`fapi.binance.com` / signed): Real money. Not yet implemented. Will be a future setting switch.

There is no Enma-internal paper trading simulation. The concept of "paper trading" in Enma means using Binance Testnet, not simulating orders locally.

**Concretely:**
- The signed base URLs live only in the `_BASE_URLS` dict in `engine/services/binance_testnet.py` — `testnet → https://demo-fapi.binance.com`, `mainnet → https://fapi.binance.com`. No other file defines the signed base.
- `LiveSession.mode` is `"paper" | "live"` (default `"paper"`). All current sessions are paper (Testnet).
- `Settings` stores exchange configuration: mode, trading fees, simulation defaults, risk defaults, bot defaults, and chaos mode defaults. Binance API credentials live in server `.env` (not MongoDB) — the AES-256 encryption util (`server/src/utils/encryption.js`) exists but is not currently wired. No `paperTrading` flag.
- `BaseStrategy.is_papertrading` is always `False` in the live bot; `is_livetrading` is always `True`. These flags exist for strategy code self-inspection and remain part of the BaseStrategy contract.

**Rationale:** Removes a confusing intermediate layer (simulated positions that look real but aren't), eliminates a source of bugs (positions showing in Enma UI but not on Binance), and creates a clear upgrade path to Mainnet.

## 6. Authentication and Multi-Tenancy
**Decision:** Single-user model. No `user_id` scopes anywhere in the schema. No authentication layer is implemented (no routes, no middleware) — none is needed for a local single-user tool.
**Rationale:** Drastically simplifies schemas and development speed for a local desktop trading tool.

## 7. Frontend Architecture
**Decision:** React + Vite + Zustand + TanStack Query + shadcn/ui.
**Rationale:** Zustand handles simple global states (auth), TanStack Query handles caching and server state, shadcn gives complete control over components without library lock-in.

## 8. Strategy Definitions
**Decision:** Strategies are raw Python files stored on disk. MongoDB only holds the metadata.
**Rationale:** Enables native Python imports, debugging, and IDE integration without executing code from string blocks.

## 10. Futures Margin Model & Risk-Based Sizing (Backtest)
**Decision:** The backtest engine simulates a real Binance USDⓈ-M **isolated-margin** futures account, and risk/stop sizing is centralized in `BaseStrategy` (additive, backward-compatible interface change). All simulation parameters (fees, slippage, funding) are **configurable via database**, not hardcoded.

**What this introduces:**
- **Real leverage & margin.** On entry the engine locks `initial_margin = notional / leverage` from the wallet. Two runs at different leverage now produce different equity curves (previously `leverage` was accepted but unused).
- **Liquidation.** Each open candle the engine checks the position against its liquidation price (computed from Binance's isolated-margin formula with a tiered maintenance-margin-rate table in `engine/core/margin.py`) **before** stop-loss and take-profit. A liquidation forfeits the locked margin and records `exitReason="liquidation"`.
- **Maker/taker fees.** Fees are split: market fills (entry, SL/TP, force-close, liquidation) charge the taker rate; resting limit fills charge maker. Configurable via Exchange Settings (defaults: taker ≈0.05%, maker ≈0.02%).
- **Slippage.** Market fills are adjusted by a configurable slippage fraction (default ~0.05%) in the adverse direction. Configurable via Exchange Settings.
- **Funding (optional, default off).** When enabled, `notional × funding_rate` is charged every 8h a position is held. Both enabled-flag and rate configurable via Exchange Settings.
- **Centralized risk sizing in `BaseStrategy`** (additive helpers, nothing removed): `size_by_risk(stop_price, risk_pct)` enforces rule #6 `(equity × riskPct) / |entry − stop|`; plus `size_by_notional`, `max_qty`, `atr_stop`, `rr_target`, `trail_stop`, `move_to_breakeven`. The legacy `self.buy = qty, price` / `self.stop_loss` / `self.take_profit` setters are unchanged.
- **Configurable defaults:** Capital and leverage defaults for backtests and bot sessions are stored in Exchange Settings, pre-filling forms without overriding user input.

**Scope of this decision:** Backtest + live bot fee_rate injection. The live bot (`live_bot_manager.py`) reads `fee_rate` from session config (injected by the server from Exchange Settings); it continues to use native Binance bracket orders for true margin/liquidation. `core/margin.py`'s MMR table is a documented static approximation of Binance's published brackets and may later be replaced by a cached `/fapi/v1/leverageBracket` fetch.

**Rationale:** "Utilising margin" was previously impossible to evaluate — leverage had no effect and a position could never be liquidated, so a 20× strategy looked identical to a 1× one. Modeling isolated margin and liquidation makes leveraged backtests meaningful, and centralizing sizing finally enforces the platform's own documented risk rule (#6) instead of the notional-allocation shortcut every built-in strategy was using. Storing all simulation parameters in the database (not hardcoded) allows users to tune backtest realism without modifying code, and ensures the live bot's fee_rate matches the backtest's assumptions.

## 11. Atomic Position Flip (Close-and-Reverse) in BaseStrategy
**Decision:** Add a first-class flip primitive to the `BaseStrategy` contract (additive interface change):

```python
self.flip_position(qty, stop_loss=None, take_profit=None)   # only while a position is open
self.has_pending_flip                                        # read-only property, engine-facing
```

Calling `flip_position()` from `update_position()` records a pending flip (`_pending_flip`, engine-owned). The engine — not the strategy — then executes both legs as one unit:

- **Backtest** (`backtest_runner.py`): both legs fill at the next candle's **OPEN**, before that candle's liquidation/SL/TP checks. Leg 1 closes the old position (adverse slippage + taker fee, `exitReason="flip"`); leg 2 opens the opposite side at the same open (margin/affordability check, slippage, fee) with the flip's SL/TP armed immediately. The reversed position therefore enters its very first candle fully protected.
- **Live bot** (`live_bot_manager.py`): the flip runs inside the single per-symbol task and is awaited sequentially, so the two legs can never interleave with exit checks or another entry for the same symbol. Leg 1 is a market close via the Node internal route; leg 2 reuses `_execute_entry()`, which re-validates lot size/min-notional and attaches the SL/TP bracket orders in the same place-order call.
- **Failure semantics (both engines):** the pending flag is consumed *before* execution and is never retried. If leg 2 cannot be afforded (backtest) or any order fails (live), the flip **degrades to close-only** — the account is left flat, never doubled and never holding an unprotected reversed position. Any pending flip is discarded whenever its position closes by SL/TP/liquidation/stop ("a flip cannot survive its position").

**What it replaces:** the legacy pattern of writing an opposite-side `self.buy`/`self.sell` plus new SL/TP while a position was open (used by MicroScalper). That pattern (a) overwrote the open position's stop with a wrong-side price, closing it via a bogus stop fill, and (b) because the engine clears SL/TP on every close, the reversed entry later filled with **no stop-loss or take-profit at all** until the next signal. Writing entry orders while a position is open is now a documented anti-pattern; `flip_position()` is the only supported reversal mechanism.

**Rationale:** Mirrors the industry-standard close-and-reverse semantics: Pine Script's `strategy.entry()` reverses an open position atomically by sizing one order as `current position + new qty`, and classic stop-and-reverse (SAR) systems treat exit-and-reentry as a single trigger precisely to eliminate the unprotected gap between legs. Centralizing the two-leg sequence in the engine keeps strategy code declarative, makes the backtest and live paths behave identically, and makes the failure mode (flat, not naked) explicit.

## 12. Pluggable Indicator Backend (Provider/Adapter Layer)
**Decision:** `engine/indicators/` is a pluggable provider layer rather than a flat module of TA-Lib calls. An `IndicatorProvider` abstract interface (`base.py`) defines every indicator against the engine's native candle layout (`[ts, open, close, high, low, volume]` numpy array) and `sequential` semantics; concrete adapters implement it per library. The backing library is selected by configuration, not by editing strategies.

**What this introduces:**
- **Interface (`base.py`).** `IndicatorProvider` declares the engine's indicator set — `ema`, `sma`, `rsi`, `atr`, `donchian`, `macd`, `bollinger_bands`, plus `adx` and `stochastic` (the latter two added with this decision). An active-provider singleton plus module-level convenience functions (`ema`, `atr`, …) form the **stable public API**: strategies keep calling `import engine.indicators as ta; ta.ema(self.candles, period=…)` exactly as before.
- **Adapters.** `adapters/talib_adapter.py` (`TalibIndicatorProvider`) is the default and a 1:1 port of the original behaviour. `adapters/pandas_ta_adapter.py` (`PandasTaIndicatorProvider`) is a pure-Python fallback. Both backing libraries are imported **guarded/lazily**, so importing the package never requires either; a provider raises `ImportError` only on construction when its library is missing.
- **Configuration (`config.py`).** `ENMA_INDICATOR_LIBRARY` (`talib` | `pandas_ta`, default `talib`) chooses the backend; `ENMA_INDICATOR_FALLBACK` (default on) makes the engine degrade to the other backend instead of crashing when the chosen one can't load. The default provider is installed eagerly at package import so misconfiguration fails at startup, not mid-backtest.
- **Optional dependency.** `pandas-ta-classic` is added to `engine/requirements.txt`. Because its import is wrapped in `try/except Exception`, a pandas-ta-classic/numpy incompatibility disables the fallback rather than breaking the engine.

**Scope of this decision:** Indicator computation only. The candle format, `sequential` contract, and all existing `ta.<name>(...)` call sites are unchanged — this is an additive, non-breaking refactor. Numeric note: pandas-ta and TA-Lib agree to within rounding for most indicators but differ slightly in a few smoothing conventions (e.g. ATR/ADX seeding); the pandas-ta backend is a functional fallback, not a bit-for-bit replacement. MicroScalper still does one direct `import talib` (ATR-SMA) and therefore only runs on the TA-Lib backend.

**Rationale:** Decouples strategies from any single indicator vendor so the library can be swapped in one configuration line (or fail over automatically) without touching strategy code, and gives new indicators a single place to be defined and a uniform contract to satisfy across backends.

## 13. Five-Model Quant Architecture & Unified Decision Pipeline
**Decision:** Refactor scattered signal/execution logic into the five canonical quant models (Alpha, Risk, Transaction Cost, Portfolio Construction, Execution) as composable objects behind one decision pipeline shared by backtest and live engines (`engine/core/pipeline.py:evaluate()`).

**What this introduces:**
- **The Five Models:** Pluggable model interfaces are housed in `engine/core/models/` implementing the interfaces (ABCs) in `base.py`. Dataclasses (`Signal`, `RiskFrame`, `Cost`, `Target`, `OrderPlan`, `EntryFill`, `ExitFill`) are used to pass immutable data down the pipeline.
- **Unified Decision Flow:** The central `evaluate(s)` function runs: `forecast()` (Alpha) → `frame()` (Risk, circuit breakers) → `size()` (Portfolio sizing) → `estimate()` & `is_worth_it()` (Cost gates) → `plan()` (Execution plan).
- **Execution Engines Integration:**
  - `backtest_runner.py`'s decision step C invokes `evaluate(strategy)`.
  - `live_bot_manager.py`'s loop invokes `evaluate(strategy)` and forwards the returned `OrderPlan` to `_execute_entry()` / `_execute_flip()`.
- **Live Gates Activation:** The Risk drawdown circuit breaker and Cost gating are now active in live trading sessions (Binances Testnet).
- **Golden Master Baseline Refresh:** On 2026-06-21, the golden snapshots were refreshed after verifying the strict five-model pipeline in Docker. The previous baseline represented pre-strict-pipeline seeded-strategy behavior; the current baseline records the canonical Alpha -> Risk -> TCM -> PCM -> Execution path for all 5 seeded strategies, including next-bar open closes, risk/portfolio model sizing, affordability gates, and current metric fields (`bySide`, expectancy, run-up/drawdown, funding/fee fields). `baseline` and `modular_merger` now compare cleanly across all 5 seeded strategies, and `tests/test_boundaries.py` passes 20/20.

**Rationale:** Keeps the codebase modular, reduces duplicate execution flow/gating bugs, and ensures backtest and live systems execute matching risk/cost rules.

## 14. Per-Symbol Leverage Clamping (`clamp_leverage`)
**Decision:** Add a shared `get_max_leverage()` / `clamp_leverage()` resolver in `engine/utils/symbols.py` and wire it into every execution path so requested leverage is silently floored to `min(requested, symbol_max)`.

**What this introduces:**
- **`_MAX_LEVERAGE_OFFLINE_MAP`** — hardcoded `{symbol: max_lev}` dict for our top pairs (BTCUSDT→125, ETHUSDT→100, etc.), with a default of 20 for unknowns. Used exclusively by the backtest worker (no credentials in the worker, required for golden-master determinism).
- **`_MAX_LEVERAGE_CACHE`** — in-memory per `(exchange, symbol)` cache, populated on first use. Cache persists for the engine process lifetime.
- **`get_max_leverage(exchange, symbol, *, api_key, api_secret, mode)`** — returns the symbol's maximum leverage. Priority: (1) cache hit, (2) signed `GET /fapi/v1/leverageBracket` first bracket's `initialLeverage` when creds provided, (3) offline map.
- **`clamp_leverage(requested, ...)`** — `min(requested, get_max_leverage(...))`.

**Three wiring points (see feature.md §3A.2):**
- **Live bot** (`live_bot_manager._run_symbol_loop`): signs with `BINANCE_TESTNET_API_KEY/SECRET` env vars; clamps before `set-leverage` callback; logs `"{symbol}: leverage clamped N→M"` to the session event log when reduced; updates `strategy.leverage` so notional caps remain consistent.
- **Manual trade** (`routers/trade.POST /leverage`): uses request-scoped credentials from `X-Binance-*` headers; returns `effectiveLeverage` in the response body so the client can show the actual value.
- **Backtest** (`services/backtest_runner.py`): offline map only (no creds in the worker); silent (no log surfacing); clamped value flows into `strategy.leverage` for the simulation.

**Golden master impact:** The clamp was designed to be a no-op for golden config backtests — all seeded strategies' golden configs use leverage ≤ the offline map cap for their symbols. Verified 2026-06-21: `GOLDEN-MASTER OK — baseline == post_leverage_clamp within tol=1e-06 (5 strategies)`.

**Rationale:** Binance rejects `POST /fapi/v1/leverage` with error `-4028 "leverage too large"` when the requested value exceeds the symbol's bracket cap. Previously this caused live bot startup failures and manual trade 400 errors for any symbol with a cap below the user-configured leverage. Clamping in the engine silently uses the highest allowed value, eliminating the rejection without requiring per-symbol user configuration. The offline fallback for the backtest worker keeps backtests deterministic (reproducible without network calls), consistent with the existing `core/margin.py` philosophy of using documented static Binance approximations.

## 15. Per-Symbol Live Bot Stats Derived Server-Side from `tradeRecords`
**Decision:** Surface per-symbol cumulative stats (trades, qty, notional, realised PnL, leverage) in the live-bot UI by **aggregating the engine-written `tradeRecords` collection on the server**, rather than maintaining a separate per-symbol counter in the engine or deriving the numbers client-side from socket events.

**What this introduces:**
- **`computeSymbolStats(sessionId)`** (`server/src/controllers/algo.controller.js`) — a MongoDB aggregation grouping `tradeRecords` by `symbol` for the session. Runs on every `position:close` and once more on session `stopped` (to capture positions force-closed during the stop sequence, which emit no `position:close`).
- **`LiveSession.symbolStats`** — an `Object` field persisting the latest `{ [symbol]: { trades, qty, notional, realisedPnl, leverage } }` map, so it survives reloads and is returned by the normal session list/get endpoints.
- **Partial `algo:session:update` emit** — the aggregation is pushed carrying only `symbolStats`; the client's socket handler merges only the fields present (so a stats-only emit never clobbers `status`/`pnl`/`openPositions`).
- **Engine ordering change** — `record_trade()` now runs **before** `_notify_node()` on the normal close path so the aggregation query sees the just-closed trade. The `position:open` event gained a `leverage` field (per-symbol clamped value) for active-position display.

**Data ownership:** unchanged and reinforced — the **engine remains the sole writer** of `tradeRecords` (rule: engine owns trade data); the **server reads/aggregates only** (via a read-only `TradeRecord` Mongoose model) for presentation. No new persistence of derived trade data beyond the convenience `symbolStats` cache on the session doc.

**Rationale:** The session doc already stored only aggregate `totalTrades`/`pnl`; per-symbol breakdown had no home. Deriving it client-side from live socket events would reset on every reload and miss trades that happened before a card was opened. Aggregating the authoritative `tradeRecords` on close is cheap (once per trade, not per render), persistent, and keeps the single-writer boundary intact. Live unrealized PnL stays client-side (Binance ticker WS) since it must update faster than the engine's periodic push and needs no persistence.


## 16. Configurable Chaos Mode Wizard
**Decision:** Upgrade Chaos Mode from a fire-and-forget, hardcoded launch to a guided 4-step wizard. Add a dedicated "Chaos Setting (testnet)" section on the Settings page to persist and validate caps (`chaosMaxStrategies` default 10, `chaosMaxManualSymbols` default 5) and launch defaults (capital, leverage, timeframe).
Expose the volume-tiered list of curated symbols via `GET /api/v1/algo/chaos/symbols` to maintain a single source of truth and avoid duplication of symbol arrays in the client codebase.
**Rationale:** Allows single-user stress-test sessions to be fully configured without code edits. Enforces uniqueness across manual picks, skips locked symbols, and provides live client-side preview calculations of H/M/L volume-tiered symbol distribution before starting. Ensures the client and server agree on the curated symbol metadata dynamically.

## 17. Deferring Multi-Symbol Backtesting (F-017) to Phase 3 (F-024)
**Decision:** Defer step 2.9 (F-017: Multi-symbol backtest mode) to Phase 3 (F-024: execution loop unification), where it will be solved naturally through the unified driver loop instead of implementing a standalone multi-symbol engine in `backtest_runner.py` now.
**Rationale:** To avoid duplicating multi-symbol logic (candles loading, alignment, and execution loop orchestration) between backtest and live modes. Since the live loop already handles multi-symbol trading, unifying the loops under one driver automatically gives backtesting multi-symbol capability. Attempting to build a separate multi-symbol backtest runner now would run counter to the core objective of reducing the backtest↔live gap (RC-1).
