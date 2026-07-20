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

## 23. Session Risk Governor policy decisions (Plan 22 Part F, decided 2026-07-17)
**Decision:** four open questions from `22_risk-management-industry-standard.md` Part F, answered
by the user, all matching the plan's own proposed defaults:
- **Auto-flatten on `halted`:** add the capability (force-close all positions when the aggregate
  drawdown kill-switch trips), but **off by default** — opt-in per session/wizard. A halted
  session with auto-flatten off still blocks new entries; existing positions require a manual stop.
- **Capital over-commit:** hard-reject non-numeric/negative/zero capital always. Configured capital
  exceeding the real wallet balance is a **warn-and-confirm** on testnet (users deliberately
  stress-test with oversized paper capital) — becomes a hard reject the day mainnet is ever
  considered.
- **Daily-loss window anchor:** **UTC midnight** (freqtrade convention, matches Binance's own
  daily-stats boundary) — not session-start-relative, not a rolling 24h window.
- **Chaos governor defaults:** **same defaults as normal sessions** — Chaos is not exempted or
  given stricter limits; the wizard should surface the governor block prominently instead so users
  understand what they're launching into.
- **Still open (not asked, no action needed now):** VaR enforcement method — current Zone 1
  historical-simulation VaR ships as-is for v1; only revisit (variance scaling / EWMA) if breach
  behavior proves too twitchy in practice. The Q5 sub-question ("does the reservation ledger count
  a stopped-but-unconfirmed session's capital as still committed?") is an implementation detail for
  22.1, not a policy call — resolve it during that build.
**Rationale:** All four align with the plan's own pre-analyzed proposals (freqtrade precedent for
the daily-loss anchor; testnet-appropriate risk tolerance for the warn-vs-reject split; visibility
over restriction for Chaos). Unblocks Plan 22 Step 22.1 (capital integrity gate) implementation.

## 24. A-12 — live signal candles sourced from mainnet WS instead of testnet's own feed (decided 2026-07-17)
**Decision:** live trading's indicator/signal price series will be sourced from Binance mainnet's
public WebSocket (`wss://fstream.binance.com`, same pattern the client already uses for its own
public market-data connection) instead of testnet's `fstream.binancefuture.com` kline stream —
while order **execution** stays on testnet. This removes the discontinuity found in the Plan 21
audit (A-12): warmup/HTF candles were already mainnet-sourced (TimescaleDB importer + REST
fallback), but live candles came from testnet's own feed, so on illiquid testnet symbols the price
series could step discontinuously at the splice point and produce spurious signals.
**Rationale:** User chose the larger-effort fix over "accept and document" — trades signal-path
correctness for implementation cost, on the reasoning that a discontinuous price series is a
real correctness bug (spurious signals), not just a cosmetic testnet quirk, and is worth fixing
properly rather than carrying as documented debt. **Not yet implemented** — this decision record
unblocks the work; see Plan 21's A-12 finding (`21_live-algo-industry-standard-audit.md`) for the
implementation pointer (client's existing `binanceWS.js` pattern) once scheduled.

## 25. A-13 — skip engine-side wick-check exits while exchange brackets are confirmed armed (decided 2026-07-17)
**Decision:** once a live position's exchange-side SL/TP conditional orders are confirmed armed
(tracked `algo_ids` + confirmed resting via reconcile), the engine's own candle-close wick-check
exit (`kernel.check_exits`) will be skipped for that symbol — the exchange conditional is trusted
as the sole trigger. The engine-side check remains as an automatic fallback whenever brackets are
missing (Plan 21.4's A-7 naked-position detector is what makes "missing" a precisely-defined,
actively-monitored state now, which is what makes this safe to do).
**Rationale:** Removes the double-execution overlap the Plan 21 audit flagged (A-13) — both paths
could independently close the same position, producing double-execution semantics and occasional
spurious close attempts booked with `exit_reason="stop_loss"` at a different price than the
exchange's own MARK_PRICE-triggered fill. Safe specifically because A-7 (shipped 2026-07-17)
already guarantees a naked position gets re-armed or force-closed within
`_NAKED_POSITION_MAX_REARM_ATTEMPTS` — so "skip the engine check when brackets are armed" no
longer means "silently unprotected if reconcile's armed-check itself is wrong," the way it would
have before A-7 existed. **Not yet implemented** — see Plan 21's A-13 finding for the
implementation pointer once scheduled.

## 26. Informative / multi-timeframe contract — `informative_timeframes` + `self.htf()` (Plan 13, shipped 2026-07-17)
**Decision:** `BaseStrategy` gains an opt-in `informative_timeframes: list[str] = []` class
attribute and a `self.htf(timeframe)` instance method. A strategy declares the higher timeframes
it needs, fetches raw candles for them via the same `ensure_candles_available()` single entry
point as base candles (backtest: `services/backtest_runner.py`, live:
`core/live_bot_manager.py`'s `_fetch_htf_candles`, both populating `strategy._htf_raw[tf]` before
`prepare()` runs), then calls `self.htf(tf)` inside `prepare()` (after `super().prepare(candles)`)
to get a base-length, as-of aligned OHLCV array indexable at `self.index` exactly like
`self.candles`. This extends the two-phase `prepare()`/`before()` contract (decision #19) rather
than replacing it — `before()`/`forecast()` still only ever index precomputed arrays, never call
`htf()` themselves.
**Alignment rule (ported from freqtrade's `merge_informative_pair` ffill+shift):** for each base
candle at open-time `t`, the returned row is the most recent HTF candle whose CLOSE time
(`open + timeframe_duration`, via `utils/timeframes.to_ms()`) is `<= t`. A base candle never sees
an HTF candle that hasn't fully closed yet — the comparison is per-timestamp, so it's causal by
construction regardless of whether `_htf_raw` holds the whole backtest date range up front (the
same array is safe to reuse across `_reprep_every_candle`'s truncated re-prepare calls, Plan 9
Step 9.5's lookahead sentinel, without leaking future HTF bars).
**Deliberately separate from BestSupertrend's existing `tf`/`pd`/`_htf_candles` mechanism**
(Plan 24's S-2/S-3 fixes) — that's a strategy-specific duck-typed pattern predating this contract,
left untouched rather than migrated, since migrating it isn't required for correctness and isn't
this plan's scope.
**Rationale:** the engine's `CLAUDE.md` had documented a `self.get_candles(exchange, symbol, '1D')`
helper that was never implemented (aspirational-only, per Plan 13's own audit) — this ships the
real mechanism, scoped to what backtest/live parity actually requires (a lookahead-safe as-of
join), not a general-purpose arbitrary-candle-fetch API. Default `[]` means zero behavior change
for any strategy that doesn't opt in — golden master confirmed byte-identical (5/5 seeded
strategies, none declare `informative_timeframes`). New `engine/tests/test_informative_alignment.py`
(6 cases) covers alignment correctness and no-lookahead directly; **S5 (lookahead sentinel) must
still be run against any real strategy that adopts `htf()`**, per this plan's own verification gate
— the unit tests here prove the primitive is causal, not that every future consumer strategy uses
it correctly.

## 27. Strategy Lab job architecture — `labResults` collection + `simulation` queue, deterministic seed keyed by source+config not job id (Plan 10 Phase 1, shipped 2026-07-19)
**Decision:** Job-based Monte Carlo robustness runs mirror the existing backtest job pattern
exactly rather than inventing a new one: a `labResults` Mongo collection (server creates the
`queued` doc + updates `status`/`error` only; engine is sole writer of `results` — same split as
`backtestResults`), a new BullMQ `simulation` queue/worker structurally identical to
`backtest`/`backtest.worker.js`, and an engine router (`routers/simulate.py`) that follows
`routers/backtest.py`'s own asymmetry (success writes happen inside the service function, the
router only writes on the failure path).
**Seed derivation:** the deterministic seed defaults to a hash of `sourceJobId:configHash`, not
the job's own `simId`. This means any resubmission of an identical robustness-run config against
the same source backtest reproduces a byte-identical `equityBands`/`ruinProbability` doc
regardless of which `labId` it lands under — the reproducibility guarantee is a property of
*what was asked for*, not *which job asked*. An explicit `config.seed` always overrides.
**Rationale:** reusing the proven backtest job/queue/ownership pattern avoids a second design for
the same problem (queueing, progress relay, ownership checks) and keeps `labResults` legible to
anyone who already understands `backtestResults`. The configHash-not-simId seed choice was made
because the plan's own §3.2 explicitly calls out "deterministic `seed` stored so any run is
exactly reproducible" as a design rule — tying it to simId would make reproducibility depend on an
implementation detail (which random UUID a request happened to generate) instead of the actual
input.
**Deferred, not decided against:** a cancel endpoint (`DELETE /lab/simulations/:id`) — the plan's
§3.1 lists one, but MC runs complete in ~1s, so there's nothing meaningful to cancel yet; build it
when Phase 3's genuinely multi-minute optimizer jobs need it. Progress-publish plumbing
(`progress:{simId}` channel, `socketEmitter.js`'s `simulation` case) exists end-to-end but the
engine never calls `publish_progress` for a sub-second job — same reasoning.
**Scope:** only the `block` (default) and `iid` bootstrap modes are implemented; skip-trades/
cost-stress/start-date-perturbation (plan §2.1 modes 3–5) are real remaining scope, not rejected —
add them when Phase 2's UI needs a mode picker for them.

## 28. Typed strategy↔engine contract — target state authorized, phased implementation (Plan 6 Step 6.3, ENG-6, decided 2026-07-20)

**Decision:** `ExecutionKernel`/`ExecutionAdapter` should eventually consume the pipeline's typed
`OrderPlan` (`core/models/base.py`) exclusively for order-intent data, with `strategy.buy`/`sell`/
`stop_loss`/`take_profit`/`_pending_flip`/`_close_at_open`/`qty_to_adjust` demoted to
`ExecutionModel.route()`'s internal write-only scratch state (and whatever strategy-authored
`update_position()`-style hooks still need to read, e.g. `trail_stop()`/`move_to_breakeven()`
reading `self.stop_loss` to compute a tightened value). This is authorized by the user as the
target design, NOT yet implemented — see "Why phased, not shipped this session" below.

**What already satisfies the plan's original acceptance text ("an explicit OrderIntent/Signal
object the strategy returns"):** it already exists. `core/models/base.py` defines
`Signal → RiskConstraints → CostEstimate → TargetPortfolio → OrderPlan`, all typed `@dataclass`,
threaded through `pipeline.py`'s `evaluate()`. A typo'd field on any of these is already a type
error, not a silent no-op.

**The real remaining gap, found by reading `core/models/execution.py`'s `route()`:** `route()`
only returns a populated `OrderPlan` for Path 3 (flat→enter). Paths 2 (close), 4 (flip), and 5
(maintain) write straight to the mutable strategy attributes and return `None`. `kernel.py`'s
`evaluate_and_route()`/`execute_pending()` then read a MIX of `plan.*` (for entries) and
`strategy.*` mutable attributes (for everything else) to drive the exact same event — that mixed
read pattern, not a missing type, is the real "temporal coupling ... spread across
kernel/adapter/manager" the plan names.

**Why this is phased rather than shipped in the same session as this decision:**
1. **A newly-confirmed coupling makes the full fix larger than originally scoped.**
   `core/live_bot_manager.py`'s `LiveAdapter.execute_entry` reads `strategy.stop_loss`/
   `strategy.take_profit` directly as its ONLY channel for SL/TP data on the live path — it is not
   handed an `OrderPlan`. Making the kernel stop writing/reading these mutable attributes for
   entries means `LiveAdapter`'s order-placement methods (and `OrderRouter`, Plan 6 Step 6.1) would
   also need to accept SL/TP as explicit parameters instead of reading them off `strategy`. That is
   a change to the live order-placement path with **zero golden-master coverage** (live-only, no
   backtest import overlap, per Plan 5.3's own note) — the same risk class every live-file change
   this session has had to navigate deliberately narrowly.
2. **`evaluate_and_route()`'s exec_algo integration (A-016) would need re-verification if `route()`
   starts returning non-`None` for close/flip/maintain paths.** Today, `self.exec_algo.
   process_order_plan(plan)` only ever receives a plan when Path 3 fired — `exec_algo` was built
   and tested only for slicing an ENTRY. `kernel.py`'s two `if plan is not None:` gates
   (the exec_algo re-routing gate and the live-entry gate) both currently use "plan is non-`None`"
   as an implicit "this is an entry" signal. Making `route()` return a typed, non-`None` `OrderPlan`
   for every path — the natural way to close the typed-contract gap — requires updating both gates
   to check `plan.intent == "enter"` explicitly, AND auditing that `exec_algo.process_order_plan`/
   `.step()` never receive a close/flip/maintain-intent plan by accident. This is a small, bounded
   two-file change in isolation, but it sits directly upstream of every live and backtest order
   the pipeline places — exactly the kind of >3-file pipeline change Rule C exists for, and
   deserves its own dedicated implementation pass with golden-master verification at each
   incremental step, not a same-session bundle with the design decision itself.
3. **Independent, smaller finding — NOT the same bug as the above, do not conflate:**
   `kernel.py`'s `evaluate_and_route()` exec_algo branch (`core/kernel.py`, the block right after
   `plan = self.exec_algo.process_order_plan(plan)` / `.step(...)`) writes
   `strategy.stop_loss`/`strategy.take_profit` directly from the (possibly-sliced) `OrderPlan`,
   which is itself a bypass of `route()`'s own "sole writer" docstring contract. Investigated
   whether this is a simple, independently-fixable violation (as a prior pass in this same session
   recommended filing to the fixes queue) — it is NOT simple: `strategy.stop_loss`/
   `strategy.take_profit` are the SAME live channel `LiveAdapter.execute_entry` reads from (see
   point 1), so kernel writing them here is not incidental — it's currently load-bearing for
   getting a sliced order's SL/TP to the live order-placement path at all. "Fixing" it by having
   the kernel stop writing these would silently break live SL/TP placement for any
   exec_algo-sliced entry unless done together with the LiveAdapter parameterization in point 1.
   Filed to `0_fixes-queue.md` as a scoped, documented item — explicitly NOT a quick fix, tracked
   alongside the main phased work rather than attempted in isolation.

**Rationale for authorizing the target design now, without implementing it now:** the user
explicitly approved the direction ("kernel reads exclusively off the typed OrderPlan, mutable
strategy.buy/stop_loss/etc. become internal implementation detail") via an explicit sign-off this
session. Recording that decision here means the next implementation session executes against an
already-settled design question instead of re-litigating it — the only remaining work is the
phased, carefully-verified mechanical migration (route() contract completeness → kernel.py's two
gate sites → `LiveAdapter`/`OrderRouter` SL/TP parameterization → the wider mutable-attribute
read-site cleanup across `~48` files), not a design decision.

**What does NOT change for strategy authors, regardless of how this phases in:** `self.buy`,
`self.stop_loss`, `self.take_profit`, `self.flip_position()`, `self.liquidate()` and every other
documented `BaseStrategy` writer/reader in `engine/CLAUDE.md`'s "Available properties" section keep
their exact current read/write semantics from a strategy author's point of view — `route()` (the
"sole writer") still ends up setting them for `update_position()`-style hooks
(`trail_stop()`/`move_to_breakeven()`) to read. What changes is only which ENGINE-internal
component (`kernel.py` vs. `route()`'s own return value) is the source of truth the kernel itself
consults — an internal wiring change, not a `BaseStrategy` API break. No `DECISIONS.md`-gated
interface break has shipped as part of this entry; a future entry should record it explicitly if
the phased implementation ever needs to change what a strategy author reads/writes, not just who
inside the engine consumes it.

**Addendum (2026-07-20, after phases (a) and (b) shipped) — phase (c)'s premise needs correcting.**
Phases (a) and (b) shipped as planned: `route()` returns a complete `OrderPlan` for every path,
`kernel.py`'s two gates check `plan.intent == "enter"` explicitly, and `LiveAdapter.execute_entry`
gained explicit `stop_loss`/`take_profit` params sourced from `OrderPlan` — `OrderRouter` needed
no change (it never read the strategy attributes itself). Investigating phase (c) — "now F10's
kernel-write becomes removable" — found that premise incomplete: `check_exits()` (`core/kernel.py`)
reads `strategy.stop_loss`/`strategy.take_profit` directly too, as the trigger levels checked on
**every candle after the entry**, for both backtest and live. `OrderPlan` is never persisted
across candles, so there is no typed source `check_exits()` could fall back on if the kernel
stopped writing these attributes. Phase (b) closed the gap for the *same-candle* `execute_entry`
read, but did nothing for `check_exits()`'s cross-candle read — a materially different consumer
this decision's original writeup did not separately account for. **F10/phase (c) is therefore not
independently closeable — it is entangled with the wider mutable-attribute-read cleanup (phase (d),
the ~48-file surface) rather than a standalone step**, since a real fix means giving
`check_exits()` its own persisted, typed source of truth too, not just `LiveAdapter`. No code
changed for this addendum. Surfaced to the user, who chose to stop and document rather than push
into phase (d)'s larger scope this session. See `0_fixes-queue.md`'s F10 entry and the plan file's
Step 6.3 section for the full writeup.

**Second addendum (2026-07-20, same day) — phase (d)'s `active_bracket` design authorized; d1
shipped.** User authorized proceeding with phase (d) after reviewing its scoping (the four
read-site clusters and the recommended `active_bracket` persisted-field direction — see the first
addendum above and the plan file's Step 6.3 section). d1 (of the proposed d1-d5 sub-phasing):
`BaseStrategy` (`core/strategy.py`) gains `self.active_bracket = None` — a new field, not
documented as strategy-facing (unlike `self.stop_loss`/`self.take_profit`, which strategy hooks
like `trail_stop()`/`move_to_breakeven()` read/write directly and remain untouched). `route()`
(`core/models/execution.py`) mirrors the same `OrderPlan` it already returns onto
`s.active_bracket` for every path, including `None` for Path 1 — purely additive, no read sites
touched. `kernel.py`'s exec_algo branch also mirrors the ACTUAL (possibly-sliced) plan onto
`active_bracket`, consistent with how it already overwrites `strategy.stop_loss`/`take_profit`
with the slice's values. **Nothing reads `active_bracket` yet** — that's d2 (cluster #1:
`check_exits()` + rounding) through d4 (cluster #3), each its own golden-master/test-verified
pass, per the sub-phasing in the scoping addendum above. d5 (whether `self.stop_loss`/
`self.take_profit` can ever be retired as strategy-facing API) remains unauthorized and would need
its own separate `DECISIONS.md` entry, since it reaches `BaseStrategy`'s documented public surface.

**Third addendum (2026-07-20, same day) — d2 and d3 SHIPPED, both verified via real Docker
rebuilds.** (Catching up documentation here — d2 shipped alongside d1 in the same pass the second
addendum above covers, but wasn't separately logged in this file at the time; see the plan file's
Step 6.3 section for the fuller writeup of both.) **d2**: migrated cluster #1 (`kernel.py`'s
`check_exits()` is_long/is_short SL/TP trigger reads — the actual exit-trigger logic, live +
backtest both) and cluster #4 (the tail-of-candle rounding block) to read/write
`strategy.active_bracket` instead of the mutable `stop_loss`/`take_profit` tuples. The highest-risk
migration in the set. Verification's first run surfaced 19 test failures — 4 files use
`_FakeStrategy` test doubles that bypass `route()` entirely and never got `active_bracket`
populated; fixed as fixture updates, not kernel changes. Re-verified clean: pytest 647/647,
golden-master `MultiDivergence` byte-identical (`trades=55 netProfit=-1784.02 winRate=0.36
cagr=-71.32 sqn=-2.08`). **d3**: migrated cluster #2 — all 5 `strategy.stop_loss`/`take_profit`
read sites in `core/reconciler.py` to `strategy.active_bracket`. Live-only, zero golden-master
coverage for this cluster specifically (same caution class as phases (b)/(c)), so pytest was the
real check. Same fixture-gap pattern as d2, caught proactively this time before handing off for
verification — 8 fixtures across the reconciler/risk-governor test files needed `active_bracket`
added. Verified: pytest 647/647, golden-master `MultiDivergence` byte-identical again (expected —
this cluster is live-only, backtest code untouched). **d4 SHIPPED and verified 2026-07-20 (same
day)**: migrated cluster #3's two read sites — `LiveAdapter.execute_exit`
(`core/live_bot_manager.py`, reads SL/TP purely to attach to the trade record) and
`BacktestAdapter.execute_entry`'s sizing-percent read (`services/backtest_runner.py`, used to
clamp/round qty against the stop distance) — from `strategy.stop_loss`/`take_profit` to
`strategy.active_bracket`. This is the first d-phase to touch actual backtest code (not
live-only), so golden-master coverage is real, not incidental. Safety argument for the backtest
side mirrors phase (b)'s: `BacktestAdapter.execute_entry` is called from `execute_pending()`,
which runs BEFORE `evaluate_and_route()` on a given candle, so `active_bracket` still holds
exactly what the prior candle's `route()` (or, for an open-position DCA add, the pipeline's own
adjust step) wrote it to — provably the same value `strategy.stop_loss` held at that read point,
not just empirically. 3 more `_FakeStrategy` test doubles needed `active_bracket = None` added
(`test_execute_flip_idempotency.py`, `test_live_fill_booking.py`, `test_live_money_accumulation.py`
— 7 failing tests total, same root cause as d2/d3's fixture gap). Verified: pytest 647/647, golden-master `MultiDivergence`
byte-identical to every prior checkpoint (`trades=55 netProfit=-1784.02 winRate=0.36 cagr=-71.32
sqn=-2.08`). **Remaining: d5 (retiring `stop_loss`/`take_profit` as strategy-facing API — still
needs its own separate `DECISIONS.md` entry, may never happen). d1-d4 of the proposed sub-phasing
are now all shipped — every read site the phase (d) scoping addendum identified reads from
`active_bracket`.**
