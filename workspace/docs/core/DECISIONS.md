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
- **Testnet** (`testnet.binancefuture.com`): Fake money. Used for all development, testing, and demo trading. ALL algo bot orders, Trade page orders, and account queries go here today.
- **Mainnet** (`fapi.binance.com` / signed): Real money. Not yet implemented. Will be a future setting switch.

There is no Enma-internal paper trading simulation. The concept of "paper trading" in Enma means using Binance Testnet, not simulating orders locally.

**Concretely:**
- `BINANCE_TESTNET_BASE = "https://testnet.binancefuture.com"` is the single source of truth, defined only in `engine/services/binance_testnet.py`.
- `LiveSession.mode` is `"paper" | "live"` (default `"paper"`). All current sessions are paper (Testnet).
- `Settings` stores only `binanceApiKey` and `binanceApiSecret` — no `paperTrading` flag.
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
- **Live Gates Activation:** The Risk drawdown circuit breaker and Cost gating are now active in live trading sessions ( Binances Testnet).

**Rationale:** Keeps the codebase modular, reduces duplicate execution flow/gating bugs, and ensures backtest and live systems execute matching risk/cost rules.

