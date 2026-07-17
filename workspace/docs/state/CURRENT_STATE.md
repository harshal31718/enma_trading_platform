# ENMA — Current State

**Authority:** This is the single source of truth for what ENMA currently does.
Read this before starting any work. If this conflicts with chat history, this document wins.

Last updated: 2026-07-16 (Known Technical Debt: confirmed the algo/conditional-order
`ORDER_TRADE_UPDATE` gap live and logged two new open bugs from a live Chaos run — see below.
Earlier relocation: content moved into feature SPEC docs and DECISIONS.md; see
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
default-off); a portfolio exposure cap (`max_portfolio_risk=0.06`) is active by default.
**Correction 2026-07-16:** the cost gate (`min_edge_mult=0.05`) previously described here as
"active by default" has in fact **never fired** — the value is injected onto `cost_model` but the
gate reads `portfolio_model.min_edge_mult` (default 0.0). The gate is dead code today, and its
edge-vs-cost formula is also dimensionally inconsistent. See
`workspace/plan/21_live-algo-industry-standard-audit.md` findings M-1/M-2 (fix routed to Plan 9
step 9.11, golden-master-gated). Strategies precompute indicators once in
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

- **Live bot PnL on exchange_sync exits — partially fixed 2026-07-17 (Plan 21.1, A-1)**: when Binance closes a position via SL/TP and the engine detects it via reconciliation, `_query_real_exit_from_user_trades()` calls `GET /fapi/v1/userTrades` to reconstruct the real exit price/PnL from Binance's own trade history. This call previously omitted its required `api_key`/`api_secret` arguments — a `TypeError` on every invocation, swallowed by the surrounding `except Exception`, always returning `None` — so every `exchange_sync` close silently fell back to the candle/SL-TP estimate. **The credentials are now passed** (see `21_live-algo-industry-standard-audit.md` A-1); regression tests added in `engine/tests/test_query_real_exit_from_user_trades.py`. Not yet confirmed against a real live session's Binance trade history — do that before closing 21.1 fully.
- **Live bot entry fee not tracked**: `session["pnl"]` only deducts the exit fee per trade. Entry fees paid to Binance are not subtracted locally, so session PnL overstates profits by one taker fee per round-trip. Acceptable approximation for now.
- **Resolved 2026-07-02 (see DECISIONS.md #20)**: the Trade page's `open-orders`/`positions`/`account` REST polling (previously 30s/3s/10s, dominated by an un-symbol-filtered `open-orders` call costing 480 weight/min on a budget shared across all users via the server's single outbound IP) is now backed by a per-user Binance User Data Stream (`engine/services/manual_trade_stream.py`) with REST reduced to a 90s/30s/60s safety net.
- **CONFIRMED 2026-07-16 (fixes-queue F7, live Chaos run against Binance Testnet) — algo/conditional
  order fills are NOT reliably caught by the real-time WS path.** BSBUSDT and ESPORTSUSDT both
  closed via their conditional SL/TP within single-digit seconds of opening (per Binance's own
  Order History), but Enma's session UI kept showing both as open for ~50-55 more seconds until
  the next 1m candle-close drove the per-loop REST reconciliation poll, which is what actually
  caught and closed them — not the user-data-stream fill callback (F-020). **This means every
  live/chaos session currently carries up to ~60s where the UI and the strategy's own in-memory
  position state say a symbol is open when Binance has already closed it.** **Root cause isolated
  and code-fixed 2026-07-17 (Plan 21.1, A-2):** `_on_fill`'s client-id lookup read a non-existent
  `clientOrderId` key and fell back to the numeric `orderId` (an int), so `.startswith("tpsl_")`
  raised `AttributeError` on every genuinely-delivered FILLED/PARTIALLY_FILLED frame — caught by
  the outer per-callback try/except, which meant `_reconcile_exchange_state()` at the end of
  `_on_fill` never ran. The event-driven fill path was dead code even when Binance emitted the
  event; every close silently waited for the next candle-close REST poll instead. Fixed by reading
  the real `"c"` field (str-coerced) via the new `_extract_fill_client_id()` helper, and by
  wrapping the OUO peer-cancel block in its own try/except so the reconcile call can no longer be
  skipped by a failure earlier in the callback. **A second, independent backstop shipped the same
  day (Plan 21.2, A-8):** a per-symbol `_on_account_update` callback now reconciles immediately on
  any OPEN<->FLAT disagreement between Binance's `ACCOUNT_UPDATE` position delta and the local
  view — this path is event-type-agnostic (Binance emits `ACCOUNT_UPDATE` for every position
  change, including algo-order fills, regardless of `ORDER_TRADE_UPDATE` semantics), so it closes
  the staleness window even if A-2's `ORDER_TRADE_UPDATE` fix turns out to have gaps. **Not yet
  re-verified against a live Chaos run** — the original ~60s staleness symptom needs to be
  reproduced again with both fixes in place before F7 is closed. Detail + full timeline:
  `workspace/docs/features/algo-trading/SPEC.md`'s "Open issues found in a live Chaos run" section,
  `21_live-algo-industry-standard-audit.md` (A-2, A-8), and `workspace/plan/handoff.md`.
- **OPEN 2026-07-16 — TP placement failing outright on some symbols (`400 Bad Request`)**, found in
  the same live Chaos run (`BCHUSDT`, then `ETHUSDT`). Possibly a recurrence of the 2026-07-03
  stale-tick-size-cache bug (see `algo-trading/SPEC.md`'s "Resilience & Stats") for symbols outside
  the original tier-cache warm set, or a distinct cause — genuinely unknown because the failure was
  only ever logged as httpx's generic `"400 Bad Request"` message, discarding Binance's actual
  `{code, msg}` body. **Logging fixed same day** (`_binance_error_detail()` in
  `live_bot_manager.py`, wired into entry/SL/TP failure logs) so the next reproduction will show
  the real cause. Root cause itself still open, but **as of Plan 21.4 (A-7, 2026-07-17) this class
  self-heals**: a TP-400 leaves a position with only its SL live, which is fine (TP is
  lower-stakes); a symmetric SL-400/failure that leaves a position genuinely naked is now detected
  by `_reconcile_exchange_state`'s naked-position re-arm and either re-placed or, after 3
  consecutive re-arm failures, force-closed — see A-7 below.
- **Fixed 2026-07-17 (Plan 21.3/21.4, A-4/A-5/A-6/A-7/M-4/M-5)** — bracket/SL integrity gaps found
  by the `21_live-algo-industry-standard-audit.md` audit, all code-side shipped, pending container
  `pytest` run + live re-verification: (1) resting SL/TP algo orders are now cancelled on every
  close path (`execute_exit`, `_close_position_on_stop`, the emergency-exit path, and reconcile
  Case 2) via `_cancel_symbol_algo_orders()` — previously only the OUO peer-cancel covered the
  in-band close case, leaving orphaned conditional orders on the other three paths (A-4/A-5); (2)
  the F-018 emergency-exit path (entry filled, SL placement failed) now retries the market close up
  to 3x with backoff and books the real fill price instead of fabricating `exit_price = fill_price`,
  and records nothing on total failure rather than falsely marking a still-open, still-naked
  position as closed (A-6); (3) reconcile now detects a position with no live exchange stop and
  re-arms it, force-closing after 3 consecutive failures instead of running naked indefinitely
  (A-7); (4) a tightened trailing/breakeven stop (`DefaultExecution.route()` Path 5) is now pushed
  to the exchange via cancel+replace instead of staying local-only for the position's entire life
  (M-4); (5) an entry whose SL lands on the wrong side of the fill price is now rejected outright
  instead of silently entering naked on that leg (M-5).
- **Partially fixed 2026-07-17 (Plan 21.5, A-9 + A-15)** — `send_signed_request`
  (`engine/services/binance_testnet.py`) had no awareness of Binance's shared 2400-weight/min
  budget and no 429/418 handling. Now tracks `X-MBX-USED-WEIGHT-1M` per base_url and defers
  non-order-critical calls once at/above a 1800 (75%) soft limit while the reading is fresh; on an
  actual 429/418 it honors `Retry-After` and pauses non-order-critical calls until it expires.
  `/fapi/v1/order`/`/fapi/v1/algoOrder` are exempt from both guards. **Not shipped:** batching
  `positionRisk`/`openAlgoOrders` into one call per session per candle wave instead of
  N-per-symbol — needs a larger concurrency restructure of `_run_symbol_loop`, deferred. **Found
  and fixed while shipping this (A-15, High):** `_reconcile_exchange_state`'s Case 2 was
  fabricating a real position close whenever the `positionRisk` query merely *failed* (network
  blip, timeout, missing credentials, or now a deliberate A-9 backpressure defer) — it read the
  failure's `0.0` default the same as a confirmed-flat exchange. A `position_query_ok` flag now
  gates Case 2 so an unconfirmed query leaves local state untouched, retrying next candle, instead
  of falsely closing a position that may still be open. Tests:
  `engine/tests/test_binance_backpressure.py` (18 cases — actually run with real pytest this
  session against a fake httpx client, not just syntax-checked, since this module has no
  TA-Lib/numpy dependency chain).
- **OPEN 2026-07-16 — a position (`FXSUSDT SHORT`) stayed shown as open after a full session stop**,
  same live run. Not yet investigated. Candidates: the entry may never have actually filled on
  Binance (phantom local-only position), or `stop_session()`'s close loop skipped this symbol.

---

## Current Constraints

| Constraint | Detail |
|-----------|--------|
| Binance Testnet rate limits | Weight-based (2400/min), shared across ALL users via the server's single outbound IP. Trade page mitigates this via a WebSocket User Data Stream (F-020 pattern reused), not high-frequency REST polling — see `ARCHITECTURE.md` rule 5. |
| Multi-user, open login + algo gate | Google OAuth + JWT cookie; login open to all. `userId` scopes all mutable models (see Auth section above). Strategies stay global — no `userId` on `Strategy`. Algo Trading start actions gated per-user via `requireAlgoAccess`. |
| TA-Lib | Compiled inside Docker container — never install on host |
| No paper trading simulation | "Paper trading" = Binance Testnet; no internal order simulation |
| TimescaleDB isolation | Server never connects to TimescaleDB; all candle data comes via engine HTTP |
