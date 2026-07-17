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
- **Sync:** Client polls the backend (account: 30 s, positions: 3 s, open-orders: 10 s — `client/src/hooks/useTrade.js`) to reconcile account state, margin, and positions. Intervals are intentionally conservative to stay inside Binance Testnet rate limits.
**Rationale:** Decouples high-frequency market data from sensitive signed account mutations.

## 9. Binance Environment Model — Testnet vs Mainnet (no internal paper-trading simulation)
**Decision:** The platform has exactly two Binance environments:
- **Testnet** (`demo-fapi.binance.com`): Fake money. Used for all development, testing, and demo trading. ALL algo bot orders, Trade page orders, and account queries go here today.
- **Mainnet** (`fapi.binance.com` / signed): Real money. **Read-only balance display only** (2026-07-02) — mainnet *trading* is deliberately NOT implemented.

There is no Enma-internal paper trading simulation. The concept of "paper trading" in Enma means using Binance Testnet, not simulating orders locally.

**Mainnet read-only balance (2026-07-02):** The Dashboard displays the user's *mainnet* wallet balance
alongside the testnet balance. To support this without opening a real-money trading path:
- A second, separate key pair is stored per user (`Settings.encryptedMainnetApiKey`/`encryptedMainnetApiSecret`),
  created on Binance with **Read Only** permission and verified against `fapi.binance.com` before storage.
- `GET /api/v1/trade/balances` (`getBalances`, `server/src/controllers/trade.controller.js`) fans out one
  `GET /fapi/v2/account` per environment (testnet keys + `X-Binance-Mode: testnet`; mainnet keys +
  `X-Binance-Mode: mainnet`) and returns a trimmed per-env snapshot, tolerating a missing/failing side.
- **Trading is pinned to testnet.** `requireBinanceCredentials.js` now hard-codes
  `X-Binance-Mode: 'testnet'` (previously `settings.mode || 'testnet'`), and `saveSettingsKeys` rejects a
  `mode` field. So even a mis-permissioned mainnet key can never reach an order endpoint. The `Settings.mode`
  field is retained (vestigial) to avoid a migration.
- **Rationale:** users want to monitor real-account equity from the same dashboard, but enabling real-money
  order routing is a much larger, riskier surface. Read-only balance is the safe subset that delivers most of
  the value with none of the order-execution risk.

**Concretely:**
- The signed base URLs for order/account calls live in the `_BASE_URLS` dict in
  `engine/services/binance_testnet.py` — `testnet → https://demo-fapi.binance.com`,
  `mainnet → https://fapi.binance.com`. `engine/utils/symbols.py` previously defined a second,
  independent set of testnet URLs (`_LEVERAGE_BRACKET_URLS`, `_EXCHANGE_INFO_URLS`, `_TICKER_URLS`,
  `_BOOK_TICKER_URLS`) pointing at `https://testnet.binancefuture.com` instead — **fixed 2026-07-02**:
  all four now point at `https://demo-fapi.binance.com`, confirmed via
  [Binance Open Platform's General Info page](https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info)
  as the current officially-documented USDS-M Futures Testnet REST base.
  `testnet.binancefuture.com` is a legacy/community domain, not the currently documented one.
- `LiveSession.mode` is `"paper" | "live"` (default `"paper"`). All current sessions are paper (Testnet).
- `Settings` stores exchange configuration: mode, trading fees, simulation defaults, risk defaults, bot
  defaults, and chaos mode defaults. Binance API credentials are stored per-user in MongoDB
  (`Settings.encryptedApiKey`/`encryptedApiSecret`, AES-256 via `server/src/utils/encryption.js`) and
  decrypted per-request by `server/src/middleware/requireBinanceCredentials.js` — not `.env`.
- `BaseStrategy.is_papertrading` is always `False` in the live bot; `is_livetrading` is always `True`. These flags exist for strategy code self-inspection and remain part of the BaseStrategy contract.

**Rationale:** Removes a confusing intermediate layer (simulated positions that look real but aren't), eliminates a source of bugs (positions showing in Enma UI but not on Binance), and creates a clear upgrade path to Mainnet.

## 6. Authentication and Multi-Tenancy
**Decision (superseded 2026-06-22 — Auth Branch):** Originally single-user with no auth layer, to
maximize development speed for a local desktop tool. This was superseded once invite-only multi-user
access became a requirement: Google OAuth + JWT httpOnly cookie (`server/src/config/passport.js`,
`server/src/middleware/auth.middleware.js`'s `verifyJWT`/`requireAdmin`, mounted on all `/api/v1/*`
routes). `userId` now scopes every mutable Mongoose model (`BacktestResult`, `BacktestTrade`,
`BacktestLeverageScenario`, `LiveSession`, `Settings`, `TradeOrder`, `TradeExecution`,
`TradeTransaction`, `TradeRecord`); `Strategy` stays global by design.
**Rationale:** The original single-user simplification was correct for the desktop-tool phase; the
switch to multi-user was driven by needing invite-only shared access without giving every user the
same Binance credentials or trade history.

**Decision (superseded 2026-07-14 — Plan 1):** Invite-only was itself superseded by **open Google
login** — anyone with a Google account can sign in; there is no invite/whitelist gate on
authentication anymore. Per-feature gating replaces per-user invite: only Algo Trading's start
actions (`POST /algo/sessions`, `POST /algo/chaos`) require admin-granted access
(`requireAlgoAccess`, `User.algoAccess.status`), requested from Settings and granted/revoked from
the Admin panel. Backtest, manual Trade, and Binance key entry are open to all authenticated users.
**Rationale:** Invite-only added friction without a corresponding security need — the real
sensitive surface is starting live algo sessions (real orders, shared Testnet/Mainnet credentials
per user), not signing in. Gating that one action per-user is more precise than gating the whole
platform per-invite.

## 7. Frontend Architecture
**Decision:** React + Vite + Zustand + TanStack Query + shadcn/ui.
**Rationale:** Zustand handles simple global states (auth), TanStack Query handles caching and server state, shadcn gives complete control over components without library lock-in.

## 8. Strategy Definitions
**Decision:** Strategies are raw Python files stored on disk. MongoDB only holds the metadata.
**Rationale:** Enables native Python imports, debugging, and IDE integration without executing code from string blocks.

---

## Verification Appendix (moved from CURRENT_STATE.md 2026-07-02 — condensed there to a pointer)

Golden-master and regression verification runs for major refactors. Historical record, not current state.

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

## 18. AtrBracketRiskModel Additive Risk Features (Workstream #2) — moved from CURRENT_STATE.md 2026-07-02
**Decision:** Add three opt-in features to `AtrBracketRiskModel` (`core/models/risk.py`), all default-off so existing behavior and golden masters are unaffected:
- **Trailing stop** (`trail_atr_mult`, default 0): in the maintain path, ratchets the stop toward price using `price ± trail_mult × ATR`; only ever tightens. Per-trade state (`_current_stop`, `_initialized`) resets on new entry/flip.
- **Breakeven move** (`breakeven_r`, default 0): once price moves `breakeven_r × initial_risk` in favor, floors the stop at entry price. Initialises `_entry_price` from `_signal_price` captured at signal time (mirrors `ChandelierRiskModel`).
- **ATR percentile filter** (`atr_percentile_min`, default 0): vetoes new entries when the current ATR is in the bottom N% of the session's ATR history (accumulated via `s.vars["atr"]` every candle, O(1)); requires ≥20 samples before activating.

Alongside this: the cost-gate injection default changed from `0.0` → `0.05` in `backtest_runner.py`/`live_bot_manager.py` (the `edge ≥ min_edge_mult × cost` gate is now active by default, still overridable per-run), and a **portfolio exposure cap** (`max_portfolio_risk`, default 0.06) was added to `DefaultPortfolioModel.construct()` — vetoes a trade post-sizing if `risk_per_unit × qty / equity > max_portfolio_risk`.

**Rationale:** Opt-in, default-off design lets these ship without touching existing strategy behavior — with default `risk_pct = 0.01`, the 6% portfolio cap is never triggered, so it's a pure safety net, not a behavior change. Verified: all 5 golden master snapshots unchanged after this workstream (`ws2_final` == `baseline`, tol 1e-6); boundary suite 20/20.

## 19. Two-Phase Strategy Contract — `prepare()` + index-only `before()` — moved from CURRENT_STATE.md 2026-07-02
**Decision:** Split strategy execution into `BaseStrategy.prepare(candles)` (one-time vectorized indicator pre-computation, default no-op for backward compatibility — migrated strategies move all TA-Lib/pandas calls here, storing results as `self._*` full-length arrays/scalars) and `before()` (a pure index lookup at `self.index`, zero TA-Lib calls in the hot loop).
**Backtest** (`services/backtest_runner.py`) calls `strategy.prepare(candles_np)` once after param injection, before the sim loop; `strategy.index = t` aligns directly with the precomputed arrays.
**Live** (`core/live_bot_manager.py`) re-runs `prepare()` on the rolling ≤500-candle window each closed candle (`index = len-1`), then `before()` indexes — identical math to backtest, O(≤500)/candle (~once/hr), no float drift, no per-strategy incremental code.
All 5 seeded strategies migrated (MicroMacroRSIDivergence, MultiDivergence, MicroScalper, BestSupertrend, AdaptiveTrend). No-lookahead preserved: divergence/pivot strategies bound the last-pivot search to the confirmation horizon `i - right`.
**Rationale:** Replaces the former O(N²) pattern (full indicator recompute on a growing `candles[:t+1]` slice every candle) with O(N) precomputation + O(1) lookup — the performance motivation behind `REF-optimization-ideas.md`'s now-shipped "pre-compute indicators on full series" idea. Verification: each of the 6 migration phases gated on golden-master byte-equivalence vs `baseline` (tol 1e-6, all 5 strategies); see `DECISIONS.md`'s own Verification Appendix above for the full phase-by-phase record.

## 20. Manual Trading via WebSocket User Data Stream, Not REST Polling (2026-07-02)
**Decision:** The Trade page's account/positions/open-orders data now comes primarily from a
per-user Binance User Data Stream (`engine/services/manual_trade_stream.py`), not REST polling.
`engine/services/user_data_stream.py`'s `UserDataStreamManager` (originally built for live bots,
F-020) gained a second, unfiltered dispatch path — `register_stream_callback()` — that fires on
every `ORDER_TRADE_UPDATE` status and every `ACCOUNT_UPDATE`, separate from the existing
per-symbol FILLED-only `register_fill_callback()` path the live bot still uses (left untouched to
avoid any risk to live-trading fill detection). A new per-user registry starts/stops/idle-reaps
(5 min) one stream per active Trade-page session, publishing events to Redis
`trade-stream:{userId}`; `server/src/services/socketEmitter.js` relays them to the user's
Socket.IO room as `trade:stream-update`; `client/src/hooks/useTrade.js`'s `useTradeStream()`
patches the `open-orders` query cache directly by `orderId` (zero REST cost) and debounces a real
REST refetch for positions/account (`ACCOUNT_UPDATE` lacks `markPrice`/`liquidationPrice`, so
those two can't be fully reconstructed from the WS payload alone). REST polling intervals were
lengthened from 30s/3s/10s to 90s/30s/60s — now a safety net for WS drops, not the primary source.
**Rationale:** Binance's own documentation recommends this exact pattern over polling
("the full information... should be obtained via the related RESTful endpoints, and the locally
cached data can be updated via the event ACCOUNT_UPDATE") — driven by a real constraint, not just
best practice: `REQUEST_WEIGHT` (2400/min) is enforced **per source IP**, and since this server
proxies every user's signed calls through one outbound IP, that budget is shared across all
concurrently active users. The old polling config (dominated by `open-orders`' 480 weight/min from
an un-symbol-filtered call) meant ~4 concurrent Trade-page users exhausted the entire budget — see
`ARCHITECTURE.md` rule 5. Reusing `UserDataStreamManager` rather than building a second WS client
kept the change additive; the live bot's existing fill-detection path was not modified.
**Known gap:** whether Binance emits `ORDER_TRADE_UPDATE` for algo/conditional orders (placed via
`/fapi/v1/algoOrder`, used by this platform's OCO/TP-SL feature) before they trigger is unconfirmed
against a live account — Docker wasn't running during implementation to verify end-to-end. The cache
patch is written defensively (only touches entries matching a received `orderId`, never guesses), so
if algo orders don't emit the event, they simply stay on the 60s REST safety net instead of showing
incorrect data — but this should be verified with the stack running before relying on it further.

## 21. Configurable Bot Session Caps — `Settings.limits`, `chaosMaxStrategies` removed (2026-07-03)
**Decision:** Live session sizing is now governed by user-configurable `Settings` fields instead of
hardcoded/unbounded behavior. `Settings.limits.{testnet,mainnet}.{maxSymbolsPerBot,maxConcurrentBots}`
(defaults 15/10, max 30/20) and a testnet-only `Settings.chaosMaxTotalSymbols` (default 120, max 250)
are enforced in `server/src/controllers/algo.controller.js`'s `startSession()` and `startChaos()`.
`chaosMaxStrategies` (default 10, max 20) is **removed** — `limits.testnet.maxConcurrentBots` now does
that job for both manual bots and Chaos Mode as one unified cap, checked against
`LiveSession.countDocuments({ userId, status: { $in: ['starting','running','stopping'] } })`. A Chaos
run that requests more strategies than available slots now partially launches (truncated strategies
reported in `errors`, not a hard 400 rejection) — see API_CONTRACTS.md `POST /api/v1/algo/chaos`.
`server/src/utils/chaosAllocator.js`'s round-robin distribution enforces both `maxSymbolsPerBot`
(per-strategy) and `chaosMaxTotalSymbols` (run-wide) as running counters during the existing tier
loop, rather than pre-truncating the curated symbol pool (which would skew the high/mid/low tier mix
purely from array ordering — `top_symbols.js` lists high-volume symbols first). Manual symbol picks
exceeding either cap are a hard validation error (`CHAOS_SYMBOL_PER_BOT_CAP_EXCEEDED`/
`CHAOS_TOTAL_CAP_EXCEEDED`), never silently trimmed — they're a user-explicit guarantee. `limits.mainnet`
exists in the schema and Settings UI now as pure future-proofing; no enforcement logic reads it, since
no code path can start a mainnet session today (see Decision #9 — mainnet is read-only).
`engine/routers/algo.py`'s `StartSessionRequest.symbols` also got a defensive `max_length=250`
(Pydantic) — real enforcement is Node-side; this only protects the engine if Node is ever bypassed.
Alongside this change, `algo.controller.js`'s `_getBinanceHeaders()` (used by the internal live
order-placement callbacks) was hardcoded to `'testnet'`, matching every other Binance-header call site
— it previously read `settings?.mode || 'testnet'`, a latent inconsistency that was harmless only
because no route can currently set `Settings.mode` to `'mainnet'`.
**Rationale:** Diagnosed during a Chaos Mode incident where sessions routinely held 130-145 symbols
each across up to 10 concurrent strategies with no ceiling anywhere — this is what turned ordinary bugs
(WS reconnect storm, stale exchange-rules-cache TP rejections, a `stop_session()` close-loop timing out
on large sessions) into Binance showing 53 real open positions while the dashboard tracked 4. That
incident's root-cause bugs were fixed separately (serial→bounded-concurrency close loop, confirm-before-
clear reconciliation ordering, a periodic full-account reconciliation sweep, WS reconnect backoff+jitter,
periodic exchange-rules-cache refresh, `contractType` filtering for quarterly/delivery contracts — none
of those required a size cap to fix). This decision addresses sizing on top of those fixes: operators can
now tune blast radius from Settings without a redeploy, and a single unified concurrent-bot cap
(replacing the narrower `chaosMaxStrategies`) prevents unbounded growth in both launch paths at once.
**Known limitation (accepted, not fixed):** the concurrent-bot-slot count in `startChaos()` is computed
once via a single query, not re-checked per-iteration or atomically across simultaneous requests — two
concurrent chaos/bot-start calls could each pass a stale check and jointly exceed the cap briefly. No
distributed lock was added for this category (mirrors the existing best-effort tolerance elsewhere in
this controller); treat the cap as best-effort, not a hard real-time guarantee.

## 22. Self-Healing Blacklist for Testnet-Invalid Symbols (2026-07-03)
**Decision:** `demo-fapi.binance.com`'s `/fapi/v1/exchangeInfo` lists symbols (confirmed: 60 distinct
symbols observed over a 3-hour window, e.g. `RADUSDT`, `B3USDT`, `AI16ZUSDT`, `NEIROETHUSDT`, `OLUSDT`)
that pass `status=TRADING` and `contractType=PERPETUAL` but are rejected outright by the testnet
matching engine — a known testnet quirk where exchangeInfo mirrors more of mainnet's symbol list than
testnet actually supports. This was surfacing as entry `MARKET` orders failing with a generic 400 that
gave no actionable signal, and — because nothing tracked the failure — the same doomed order got
retried every candle close, forever. `engine/utils/symbols.py` now distinguishes this case precisely:
`get_max_leverage()`'s signed `/fapi/v1/leverageBracket` probe (already called once per symbol at
`_run_symbol_loop()` startup, before any WS connection or order attempt) catches `httpx.HTTPStatusError`
specifically, and only a **definitive HTTP 400** (Binance's "bad request" class — not a 429 rate limit,
not a 5xx, not a network timeout, all of which remain transient/retryable) adds `(exchange, symbol)` to
a new in-memory `_invalid_symbols` set via `is_symbol_invalid()`. `get_all_symbols()` (feeding both
`pairlist.py` and Chaos Mode's symbol pool via `GET /candles/symbols`) now excludes blacklisted symbols,
and `live_bot_manager.py`'s `_run_symbol_loop()` checks the blacklist immediately after the leverage
probe and aborts that symbol's entire loop before opening a WS connection or ever attempting an order.
**Rationale:** Self-healing without any external symbol-status database: a symbol is blacklisted the
first time a live session actually probes it (not pre-emptively), and every future pairlist/Chaos run on
the same engine process then skips it automatically. Distinguishing by HTTP status code (400 specifically)
rather than blacklisting on any failure avoids permanently excluding a symbol due to a transient network
blip or rate limit — those already degrade gracefully to the existing offline leverage fallback map
without being blacklisted. Scoped to `(exchange, symbol)` so a symbol invalid on testnet doesn't affect
a hypothetical future mainnet path.
**Known limitation (accepted, not fixed):** `_invalid_symbols` is in-memory only, reset on every engine
restart — each restart re-probes and re-discovers the same ~60 symbols once each (one wasted, harmless,
already-logged 400 per symbol, not a repeating storm). Not persisted to MongoDB/Redis; if this needs to
survive restarts a follow-up could write it to a small collection, but the current per-restart rediscovery
cost is one API call per previously-known-bad symbol, which is cheap enough not to warrant it yet.
