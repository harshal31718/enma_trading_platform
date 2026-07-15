# ENMA — Current State

**Authority:** This is the single source of truth for what ENMA currently does.
Read this before starting any work. If this conflicts with chat history, this document wins.

Last updated: 2026-07-02 (content relocated into feature SPEC docs and DECISIONS.md; see
`workspace/plan/current_state_relocation.md` for the relocation plan and
`workspace/docs/features/*/SPEC.md` for the moved detail)

---

## Implemented Features

### Auth & Access Control (Auth Branch — active)
- **Google OAuth 2.0** via Passport.js (`passport-google-oauth20`), sessionless. Flow: `/api/v1/auth/google` → Google → `/api/v1/auth/google/callback` → JWT cookie set → redirect to `/`.
- **JWT in `httpOnly` cookie** (`enma_jwt`, `sameSite: lax`, 7-day expiry). Verified by `verifyJWT` middleware globally applied at `app.use('/api/v1', verifyJWT)` (auth routes excluded).
- **Open login** — anyone with a Google account can sign in. There is **no email whitelist** (removed 2026-07-07; the former `PlatformConfig` singleton + `/admin/allowed-emails` CRUD are deleted). Admin email (`ADMIN_EMAIL`) is auto-promoted to `role: 'admin'` on first login.
- **Per-user Algo Trading gate** — `User.algoAccess.status` (`none`|`requested`|`granted`, default `none`; absent field reads as `none`). The `requireAlgoAccess` middleware gates only the start actions (`POST /algo/sessions`, `POST /algo/chaos`); admins bypass via role. Everything else (Backtest, manual Trade, Binance key entry, viewing the Algo page + wizards, listing/stopping sessions) is open to any authenticated user. `verifyJWT` reloads the user each request, so grants/revokes take effect immediately without re-login.
- **User model**: `User.js` with `googleId`, `email`, `name`, `avatar`, `role` (`user`|`admin`), `isActive`, `lastLoginAt`, and `algoAccess` (`status`, `requestedAt`, `decidedAt`, `decidedBy`).
- **Request flow**: users request access from the **Settings → Algo Trading Access** card (`POST /api/v1/algo/access-request`, idempotent `none`→`requested`). The AlgoTrading page shows a status banner (request CTA when `none`, pending notice when `requested`) and disables the New Bot / Chaos Mode buttons until granted.
- **Admin panel**: single sortable **user table** (`GET /api/v1/admin/users`, `PATCH /api/v1/admin/users/:id/algo-access` with `{ status: 'granted'|'none' }`) — admin-only via `requireAdmin`. Shows all users with name/email/role/status/joined, a category filter (All/Allowed/Requested/No access), and Grant/Revoke actions (admin rows are not editable). Client: `/admin` route, visible only to admin users in the Navbar.
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
List, create, clone, and view (read-only) strategies; 5 strategies seeded on startup, each bound
to a specific Risk/Portfolio model pair. **In-app code editing was removed 2026-07-15** (Plan 3
Step 3.2, SEC-2 — closed the any-user strategy-code RCE path outright). **Detail moved 2026-07-02
to** `workspace/docs/features/strategy-management/SPEC.md` (Built-in Strategies table, updated
2026-07-15 for the edit-path removal) — this bullet is a pointer, not a description.

### Backtesting
Full strategy simulation against historical OHLCV, unified five-model pipeline (shared with live
trading), isolated-margin futures realism, multi-symbol shared-wallet mode, TWAP/VWAP/Iceberg
execution slicing, and a tabbed report UI with Performance Calendar and Buy & Hold benchmark overlay.
**Detail moved 2026-07-02 to** `workspace/docs/features/backtest-pipeline/SPEC.md` (Data Flow,
Execution & Risk Mechanics, Report UI sections) — this bullet is a pointer, not a description.

### Dashboard
- **Live price strip** (`TickerStrip`): BTC/ETH majors + open-position symbols (capped 8), from the browser-direct Binance public WS (no server load)
- **Account overview** (`AccountOverview`): testnet + **mainnet** wallet/available balances side by side, testnet unrealized PnL, margin balance + open-position count. Mainnet is **read-only** (`GET /api/v1/trade/balances`, F-021 2026-07-02); trading stays testnet-pinned
- Condensed backtest KPI strip (`BacktestKpiStrip`): total runs, best strategy, avg win rate, profit factor, Sharpe, Sortino, max drawdown, expectancy
- Strategy leaderboard (per-strategy averaged metrics, sorted by net profit)
- Recent Live Runs + Recent Backtests panels (last 5 each, deep-link to results)
- Cached candles table (TimescaleDB inventory) — demoted into a collapsible section (default closed)
- **See** `workspace/docs/features/dashboard/SPEC.md` for the full redesign spec.

### Risk Intelligence Dashboard
Centralized `/risk-dashboard` page: Zone 1 real-time portfolio VaR/CVaR + correlation heatmap, Zone 2
hierarchical risk-limit overrides (global → strategy → symbol) that cascade into live/chaos/backtest
launches, Zone 3 leverage-scenario + Monte Carlo historical simulation. **New SPEC written 2026-07-02
at** `workspace/docs/features/risk-dashboard/SPEC.md` — this bullet is a pointer, not a description.

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
- **Real-time account/order state via WebSocket** (`useTradeStream()`, 2026-07-02): a per-user Binance User Data Stream pushes order/account changes instead of relying on high-frequency REST polling — see `workspace/docs/features/live-trading/SPEC.md` and `DECISIONS.md` #20.

### Algo Trading (Bot Sessions)
Live multi-symbol bot sessions against Binance Testnet, candle-driven execution through the same
five-model pipeline as backtest, self-healing exchange-state reconciliation, OUO SL/TP safety nets,
a dynamic pairlist pipeline, per-symbol leverage clamping, and Chaos Mode multi-strategy stress runs.
**Detail moved 2026-07-02 to** `workspace/docs/features/algo-trading/SPEC.md` (Data Flow, Exchange
State Reconciliation, SL/TP & OCO Safety, Dynamic Pairlist & Symbol Management, Chaos Mode,
Resilience & Stats sections) — this bullet is a pointer, not a description.

**2026-07-15 additions (Plan 5 + Plan 12 + Plan 20 — not yet folded into the SPEC doc above):**
- **Execution event log**: append-only `executionEvents` Mongo collection
  (`engine/services/event_log.py`), engine-written at every position-mutating point (entry, DCA
  add, exit, close-failed, reconcile-adjustment), seq-ordered per `(session, symbol)`. Node's
  `handleEngineStats` rejects a stale/out-of-order seq for the same symbol. Additive — the live
  session's in-memory state and `LiveSession` document remain the actual read path; the log is
  not yet the source of truth (that's Plan 5 Step 5.6, unstarted). See
  `workspace/plan/5_live-trading-state-integrity.md`.
- **Real fills, not fabricated closes**: every close/entry-booking site now reads the actual
  Binance fill (`avgPrice`) instead of a pre-trade price estimate; a failed close order leaves
  the position open instead of fabricating a close. Entry orders gained idempotency (client
  order ID + re-query-before-retry on a raised exception).
- **Per-symbol locking**: an `asyncio.Lock` per `(session, symbol)` serializes the candle-loop
  and user-data-stream fill callback, closing a double-close/double-count race.
- **Session-level max open positions**: optional `maxOpenPositions` on session start caps
  concurrent open symbols in live/chaos sessions (freqtrade `max_open_trades` equivalent); unset
  = unlimited (default, unchanged behavior).
- **DCA scale-out precision**: partial-reduce quantities are now floored to the symbol's Binance
  `stepSize` before submission (previously unclamped — a live rejection risk once any strategy
  implements `adjust_trade_position()`, none do yet).

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

### Risk Model & Strategy Execution Refinements
`AtrBracketRiskModel` supports optional trailing stop / breakeven move / ATR-percentile veto (all
default-off); a default cost gate (`min_edge_mult=0.05`) and portfolio exposure cap
(`max_portfolio_risk=0.06`) are active by default. Strategies precompute indicators once in
`prepare()` (both backtest and the rolling live window), leaving `before()` as a pure index lookup —
replaces the former O(N²) per-candle recompute. **Rationale + verification detail moved 2026-07-02 to**
`workspace/docs/core/DECISIONS.md` #18–19 — this bullet is a pointer, not a description.

### Parameters, Optimization & Strategy Mechanisms
Typed self-validating strategy parameters (reject, don't clamp, out-of-range overrides), a grid-search
parameter optimizer, and shared backtest/live position-adjustment (DCA) + entry/exit tagging through
the unified `ExecutionKernel`. **Detail moved 2026-07-02 to**
`workspace/docs/features/backtest-pipeline/SPEC.md` (Execution & Risk Mechanics, Optimization
sections) — this bullet is a pointer, not a description.

### UI / Navigation
- 6 nav pages + OrderHistory (at `/order-history`, not in navbar): Dashboard, Strategies, Backtest, Live Trading (Trade), Algo Trading, Settings
- Horizontal top navbar — no sidebar
- Active nav state: `text-emerald-400`, `bg-emerald-500/10`, `border-b-2 border-emerald-500`
- Dark theme throughout (`bg-gray-950` base)
- All financial P&L: `emerald-400` (profit) / `red-400` (loss)

### UI Polish & Hardening (Phase 2, 2026-06-2x)
Toast notifications (`react-hot-toast`) across Settings/Strategy/Backtest/Algo actions; ARIA/a11y
sweep (labels, roles, `aria-pressed`/`aria-busy`/`aria-expanded`); background-polling status dots;
client-side table sorting (`useTableSort` + `<SortableHeader>`); `<EmptyState>` replacing placeholder
text across Trade/Backtest/Strategies/Admin. Condensed 2026-07-02 — component-level detail lives in
git history, not here.

### UI Polish & Responsiveness (Phase 3, 2026-06-2x)
`SessionCard.jsx` equity fetch moved to TanStack Query; TP/SL and Leverage overlays converted to
Radix `<Dialog>`; lazy-loaded heavy sub-components; shared `<Badge>`/`<Card>`/`<Button>` design-system
sweep across `StrategyCard.jsx`/`AdminPanel.jsx`/`Settings.jsx`; responsive tab-bar layout on
`Trade.jsx` below `1024px`; responsive grid columns on backtest/wizard forms. Condensed 2026-07-02 —
component-level detail lives in git history, not here.

---

## Verified Baselines

Golden-master and regression verification runs for major refactors — condensed 2026-07-02, full
detail (commands, per-phase byte-equivalence, issue-by-issue fix list) moved to
`workspace/docs/core/DECISIONS.md` → "Verification Appendix" as historical record.

- **Narang Black-Box Refactor** (2026-06-21): golden comparison passed for all 5 seeded strategies; boundary suite 20/20.
- **Strategy Performance Refactor** (`prepare()`/`before()` split, 2026-06-24): all 6 phases gated on golden-master byte-equivalence; boundary suite 20/20; one latent pandas-2.x epoch-conversion bug found and fixed (BestSupertrend HTF bucket mapping).
- **Standardise Implementation Audit** (2026-06-25): 13 issues found and fixed across exec-algo slicing, pairlist filters, metric definitions, and reconciliation; engine unit suite 81/81; single-symbol backtests confirmed byte-identical post-fix.

---

## Planned / Not Yet Implemented

| Feature | Notes |
|---------|-------|
| **Mainnet trading** | Deliberately not implemented. Mainnet is **read-only balance display** only (Dashboard `AccountOverview`, 2026-07-02); `X-Binance-Mode` is pinned to testnet on all trade routes. Enabling real-money order routing is out of scope. See DECISIONS.md §9. |
| **Multi-exchange support** | Binance only. |

---

## Known Technical Debt

- **Live bot PnL on exchange_sync exits**: when Binance closes a position via SL/TP and the engine detects it via reconciliation, the exit price is estimated from the local SL/TP prices. If neither SL nor TP was set, it falls back to current candle close. The user data stream (F-020) partially mitigates this by detecting fills in real-time. For exact fill prices an additional `GET /fapi/v1/userTrades` call would be needed (not yet implemented).
- **Live bot entry fee not tracked**: `session["pnl"]` only deducts the exit fee per trade. Entry fees paid to Binance are not subtracted locally, so session PnL overstates profits by one taker fee per round-trip. Acceptable approximation for now.
- **Resolved 2026-07-02 (see DECISIONS.md #20)**: the Trade page's `open-orders`/`positions`/`account` REST polling (previously 30s/3s/10s, dominated by an un-symbol-filtered `open-orders` call costing 480 weight/min on a budget shared across all users via the server's single outbound IP) is now backed by a per-user Binance User Data Stream (`engine/services/manual_trade_stream.py`) with REST reduced to a 90s/30s/60s safety net. **Remaining gap**: whether Binance emits `ORDER_TRADE_UPDATE` for algo/conditional orders (`/fapi/v1/algoOrder`, this platform's TP/SL mechanism) before they trigger is unconfirmed against a live account — Docker wasn't running during implementation. Worth a real end-to-end check next time the stack is up; if unconfirmed orders don't emit the event, they fall back to the 60s REST poll rather than showing wrong data (the cache patch never guesses), so this is a staleness-window risk, not a correctness one.

---

## Current Constraints

| Constraint | Detail |
|-----------|--------|
| Binance Testnet rate limits | Weight-based (2400/min), shared across ALL users via the server's single outbound IP. Trade page mitigates this via a WebSocket User Data Stream (F-020 pattern reused), not high-frequency REST polling — see `ARCHITECTURE.md` rule 5. |
| Multi-user, open login + algo gate | Google OAuth + JWT cookie; login open to all. `userId` scopes all mutable models (see Auth section above). Strategies stay global — no `userId` on `Strategy`. Algo Trading start actions gated per-user via `requireAlgoAccess`. |
| TA-Lib | Compiled inside Docker container — never install on host |
| No paper trading simulation | "Paper trading" = Binance Testnet; no internal order simulation |
| TimescaleDB isolation | Server never connects to TimescaleDB; all candle data comes via engine HTTP |
