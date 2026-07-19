# Enma — Client (React) Rules

> Inherits all rules from root `CLAUDE.md`.
> Read root CLAUDE.md first, then this file.

---

## Stack (client-specific)

- React 18 with hooks only — no class components
- Vite 5 for build tooling
- TailwindCSS 3 for all styling — no CSS modules, no styled-components
- Recharts 2 for all backtest charts (equity curve)
- lightweight-charts 5 for the Trade page candle chart (imperative API — update via `seriesRef.current.update`)
- Zustand 4 for global UI state
- TanStack Query 5 for all server state
- Socket.IO client 4 for realtime
- React Router 6 for routing
- Axios for HTTP requests (configured instance in `src/lib/axios.js`)
- Radix UI primitives (`@radix-ui/react-dialog`, `-alert-dialog` (used by `components/ui/confirm-dialog.jsx`), `-dropdown-menu`, `-label`, `-select`, `-tabs`, `-tooltip`) — unstyled accessible components
- `lucide-react` for icons
- `react-hot-toast` for application-wide notifications
- `clsx` + `tailwind-merge` + `class-variance-authority` — utility-class helpers (used in `src/lib/utils.js`)
- **Dev:** `vitest`, `@testing-library/react`, `msw` (API mocking), `puppeteer` (E2E)

---

## Folder structure

```
client/
├── public/
├── src/
│   ├── components/      ← shared reusable components
│   │   ├── ui/          ← generic UI (Button, Input, Dialog, Card, Badge, PageHeader, skeleton,
│   │   │                   table, tabs, select, pagination, confirm-dialog, empty-state, Avatar)
│   │   │                   Avatar.jsx — shared avatar w/ initials fallback; always sets
│   │   │                   referrerPolicy="no-referrer" on the <img> (Google profile photos
│   │   │                   403/429 without it) and falls back to initials on onError, not just
│   │   │                   when src is empty. Used by Navbar and Settings' Profile card.
│   │   │                   Note: DataTable.jsx, StatusBadge.jsx, and the original StatCard.jsx
│   │   │                   have been deleted — they were never imported. There is no Modal.jsx;
│   │   │                   dialog.jsx (Radix-based Dialog/DialogTrigger/etc.) is the real name.
│   │   │                   empty-state.jsx was deleted then reintroduced 2026-07-01 — it's live,
│   │   │                   used by AdminPanel/BacktestHistory/OrderHistory/Strategies/Trade.
│   │   ├── ErrorBoundary.jsx ← top-level React error boundary
│   │   ├── charts/      ← Recharts wrappers: EquityCurve.jsx, EquitySparkline.jsx,
│   │   │                   DrawdownSparkline.jsx (DrawdownChart/CandleChart do not exist)
│   │   ├── layout/      ← Navbar.jsx, PageWrapper.jsx (no Sidebar)
│   │   ├── lab/         ← Strategy Lab (Plan 10) components
│   │   │   ├── ConfigDrawer.jsx, RunWizard.jsx, WalkForwardWizard.jsx, ParamGridForm.jsx
│   │   │   ├── HistoryRail.jsx, OptimizationHistoryRail.jsx
│   │   │   ├── RuinCard.jsx, ExceedanceCurve.jsx, PercentileSpread.jsx, FanChart.jsx (MC tab)
│   │   │   └── DegradationVerdict.jsx, StitchedOOSCard.jsx, FoldResultsTable.jsx, VerdictStrip.jsx (Optimizer tab)
│   │   ├── risk/        ← Risk Intelligence Dashboard visualizations
│   │   │   ├── AggregateMarginGauge.jsx ← locked margin / free balance / leverage gauge (Zone 1)
│   │   │   ├── CorrelationHeatmap.jsx   ← rolling 30-day close-return correlation heatmap (Zone 1)
│   │   │   ├── NetExposureBar.jsx       ← stacked long/short notional exposure bar (Zone 1)
│   │   │   └── SimulationResults.jsx    ← Monte Carlo / leverage-scenario results (Zone 3)
│   │   ├── algo/        ← AlgoTrading feature components
│   │   │   ├── NewSessionWizard.jsx  ← multi-step wizard for starting a bot session
│   │   │   ├── SessionCard.jsx       ← single live session display card
│   │   │   ├── ChaosWizard.jsx       ← 4-step Chaos Mode wizard dialog
│   │   │   ├── SymbolPicker.jsx      ← symbol multi-select for bot session
│   │   │   └── ParamsForm.jsx        ← strategy param inputs for bot session
│   ├── RiskParamsFields.jsx       ← shared risk-model parameter fields (pre-filled from settings, used by backtest & algo wizards)
│   │   └── SymbolSearchBar.jsx       ← global symbol search (uses all-ticker WS when open)
│   ├── features/        ← feature-specific components
│   │   ├── backtest/
│   │   │   ├── BacktestCalendar.jsx   ← performance calendar heatmap (Day/Week/Month/Quarter)
│   │   │   ├── BacktestHistory.jsx     ← history sidebar list with emerald highlight
│   │   │   ├── BacktestMetricCard.jsx  ← single reusable KPI stat card (replaces 6 inline copies)
│   │   │   └── NewBacktestWizard.jsx   ← multi-step dialog wizard for launching a backtest (strategy → params → market → settings → review)
│   │   ├── dashboard/
│   │   │   ├── StatCard.jsx            ← single numeric metric card (canonical — only this one exists)
│   │   │   ├── CachedCandlesTable.jsx  ← TimescaleDB candle cache summary table
│   │   │   ├── RecentActivityTable.jsx ← last 5 backtest runs with View deep-links
│   │   │   ├── StrategyLeaderboard.jsx ← per-strategy averaged metrics
│   │   │   └── DashboardCalendar.jsx   ← performance-calendar heatmap, wired into Dashboard.jsx (fixes-queue F5, 2026-07-16) with a 30D/90D/All toggle
│   │   └── strategies/
│   │       ├── CodeViewer.jsx          ← read-only pre block rendered in a Dialog
│   │       ├── StrategyCard.jsx        ← card: name, description, type badge, View button
│   │       └── StrategyCreateDialog.jsx ← create/clone strategy dialog
│   ├── hooks/           ← custom hooks
│   │   ├── useSocket.js           ← subscribe/unsubscribe to Socket.IO events with cleanup
│   │   ├── useCandles.js          ← TanStack Query hooks: useSymbols() only
│   │   ├── useDashboard.js        ← TanStack Query hooks: useDashboardStats(), useCachedCandles()
│   │   ├── useBacktest.js         ← TanStack Query hooks: useRunBacktest(), useBacktestsList(), useBacktestResult(id), useBacktestTrades(id, page, limit), useAllBacktestTrades(id), useBacktestBenchmark(id), useCancelBacktest()
│   │   ├── useStrategies.js       ← TanStack Query hooks: useStrategies(), useStrategyCode(id)
│   │   ├── useTrade.js            ← TanStack Query hooks: useTradeAccount(), useAccountBalances() (testnet+mainnet, GET /trade/balances), useTradePositions(), useTradeOpenOrders(), useTradeStream(), useTradeSymbolConfig(symbol), useChangeLeverage(), useChangeMarginType(), usePlaceOrder(), usePlaceOrderWithTpSl(), useCancelOrder(), useClosePosition(), useCancelAllOrders()
│   │   ├── useAlgoSessions.js     ← TanStack Query hooks for /api/v1/algo/* endpoints (includes useStartChaos)
│   │   ├── useExchangeSettings.js ← TanStack Query hooks for /api/v1/settings/exchange
│   │   ├── useOcoMonitor.js       ← monitors OCO order fill/cancel state via polling
│   │   ├── useTableSort.js        ← generic column-sort state hook for table components
│   │   ├── useOrderHistory.js     ← useOrderHistory({ page, limit, filters }) → GET /api/v1/order-history
│   │   ├── useAuth.js             ← TanStack Query: useAuth() (GET /api/v1/auth/me, 5-min stale, 401→null; exposes hasAlgoAccess), useLogout()
│   │   ├── useAlgoAccess.js       ← useRequestAlgoAccess() (POST /algo/access-request), useAdminUsers() (GET /admin/users), useSetUserAlgoAccess() (PATCH /admin/users/:id/algo-access)
│   │   ├── useRiskSettings.js     ← TanStack Query hooks for /api/v1/risk/* (settings, live metrics, simulation, overrides)
│   │   ├── useLab.js              ← TanStack Query hooks for /api/v1/lab/* (simulations + optimizations, Plan 10)
│   │   └── useBinanceWS.js        ← registers/unregisters callbacks on the binanceWS singleton

│   ├── context/
│   │   └── SymbolContext.jsx  ← provides current symbol selection across Trade page sub-components
│   ├── lib/
│   │   ├── axios.js       ← configured Axios instance
│   │   ├── socket.js      ← Socket.IO client instance
│   │   ├── binanceWS.js   ← Binance WebSocket singleton connection manager
│   │   ├── queryClient.js ← TanStack Query client config
│   │   └── utils.js       ← misc utility helpers (cn classname merger, etc.)
│   ├── pages/             ← route-level page components
│   │   ├── Dashboard.jsx      ← route: /
│   │   ├── Backtest.jsx       ← route: /backtest
│   │   ├── Strategies.jsx     ← route: /strategies
│   │   ├── Settings.jsx       ← route: /settings
│   │   ├── Trade.jsx          ← route: /trade/:symbol (manual trading terminal)
│   │   ├── StrategyLab.jsx    ← route: /lab (Plan 10 — Robustness (MC) + Optimizer tabs)
│   │   ├── AlgoTrading.jsx    ← route: /algo (algo bot session management)
│   │   ├── OrderHistory.jsx   ← route: /order-history (paginated trade log; not in navbar)
│   │   ├── Login.jsx          ← route: /login (Google OAuth entry point, public)
│   │   ├── AdminPanel.jsx     ← route: /admin (admin-only, user table: grant/revoke algo access + category filter/sort)
│   │   ├── RiskDashboard.jsx  ← route: /risk-dashboard (Zone 1/2/3 risk intelligence, see CURRENT_STATE.md)
│   │   └── NotFound.jsx       ← route: * (catch-all 404, "Go to Dashboard" CTA)
│   │       Note: `client/src/store/` no longer exists — `useUIStore.js` (sidebar state) was its
│   │       only file and was deleted with the sidebar; no Zustand store directory remains.
│   ├── utils/
│   │   ├── formatters.js         ← formatQty, formatPrice, formatPct, formatPnl, formatSignedPct
│   │   ├── backtest-analytics.js ← Performance Calendar bucketing (Day/Week/Month/Quarter) over backtestTrades
│   │   ├── exporters.js          ← client-side JSON/CSV export helpers for backtest results
│   │   └── symbolLimits.js       ← per-symbol precision/tick-size rules for order form validation
│   │       ├── formatQty(value)        → max 6 decimal places, trimmed
│   │       ├── formatPrice(value)      → "$1,234.56" (2 dp, thousands sep)
│   │       ├── formatPct(value)        → "32.41%" (unsigned)
│   │       ├── formatPnl(value)        → { value: "+$123.45", isPositive: bool }
│   │       ├── formatSignedPct(value)  → "+32.41%" or "-8.20%" (always shows sign)
│   │       ├── formatCompact(value, {prefix, decimals}) → "$1.2M" / "1.5K" — abbreviated large numbers
│   │       ├── formatPercent(value, decimals=2) → "32.41%" (unsigned, configurable precision)
│   │       ├── formatDateTime(iso, {local}) → "Jul 1, 2026, 14:03:22 UTC" by default; local tz if {local:true}
│   │       └── formatDate(iso, {local})     → "Jul 1, 2026" date-only, UTC by default
│   └── main.jsx         ← entry point
├── index.html
├── vite.config.js
├── tailwind.config.js
└── .env
```

---

## Component rules

- One component per file
- PascalCase filename = PascalCase component name
- Props always destructured in function signature
- No inline styles — Tailwind only
- All components must handle loading and error states
- Use `React.memo` only when profiling shows it's needed — not by default
- `Sidebar.jsx` does not exist — replaced by a horizontal `Navbar.jsx` in `components/layout/`
- `components/layout/` contains: `Navbar.jsx`, `PageWrapper.jsx` — no Sidebar, no TopBar.jsx

---

## Data fetching rules

- All API calls go through `src/lib/axios.js` — never raw fetch
- All server state managed by TanStack Query — never useState for API data
- Query keys follow this pattern: `['resource', id, filters]`
  - e.g. `['backtest', backtestId]`
  - e.g. `['strategies']`
  - e.g. `['candles', 'BTC-USDT', '1h']`
- Mutations always invalidate the relevant query on success
- For real-time private state synchronization (account balances, positions, open orders), pass `{ refetchInterval: 4000 }` options to the query hooks to run active background polling.

---

## Realtime rules

- Socket.IO instance is a singleton in `src/lib/socket.js`
- Custom hook `useSocket(event, handler)` in `src/hooks/useSocket.js` for subscribing
- Always clean up socket listeners in useEffect cleanup functions
- Never call `socket.emit` directly from components — use hooks
- **Binance Public WebSocket feed:**
  - Connection manager `src/lib/binanceWS.js` manages `WebSocket` connections to `wss://fstream.binance.com/public/ws` (depth streams) or `wss://fstream.binance.com/market/ws` (everything else) — never the bare `/ws` or `/stream` path. See `workspace/docs/core/binance-api.md` for the authoritative path reference.
  - Custom hook `useBinanceWS(symbol, stream, callback)` registers/unregisters callbacks dynamically to prevent duplicate connections.
  - Isolate state updates to specific sub-components (e.g. `TickerBar`, `OrderBook`, `RecentTrades`) to avoid parent re-renders of the terminal layout.
  - Update lightweight-charts series imperatively using `seriesRef.current.update` inside the hook's callback to bypass React re-rendering cycles.
  - Always normalize depth payload arrays inside callbacks by fallback-checking `data.asks || data.a` and `data.bids || data.b` to support both partial depth streams and event diffs without unmount crashes.
  - **All-Ticker WebSocket Rule:** The multiplex all-ticker WebSocket stream (`!ticker@arr`) must only be subscribed to when the symbol search dropdown is open. Connect the stream when the dropdown state changes to `open === true` and unsubscribe immediately when it changes to `open === false` or unmounts.

---

## WebSocket depth parsing

Binance USD-M Futures depth streams return two different key shapes depending on stream type:

| Stream type | asks key | bids key |
|-------------|----------|----------|
| Partial depth snapshot (`@depth20@100ms`) | `"asks"` | `"bids"` |
| Diff depth update (`@depth@`) | `"a"` | `"b"` |

**Rule:** Always use the fallback pattern when reading depth data inside any `onDepth` callback:

```js
const asks = data.asks || data.a || [];
const bids = data.bids || data.b || [];
```

Never access `data.a` or `data.b` directly without a fallback. Doing so causes a
`TypeError: Cannot read properties of undefined (reading 'slice')` when a partial depth
snapshot arrives, which crashes and unmounts the React component tree.

The fallback must be applied inside the component callback (e.g. `OrderBook`), not inside
`binanceWS.js` or `useBinanceWS.js`, to keep the connection manager generic.

---

## Candle data fetching rule

**Never fetch candle/kline data directly from `https://fapi.binance.com` in client code.**

Binance public REST APIs reject browser-originated cross-origin requests from `localhost`,
which prevents chart initialisation. All candle requests must go through the Express proxy:

```
GET /api/v1/trade/klines?symbol=BTCUSDT&interval=1m&limit=200
```

Express forwards the request to the FastAPI engine (`GET /trade/klines`), which calls
`fapi.binance.com` server-side where there are no CORS restrictions.

This rule applies to all components that need historical OHLCV data for chart initialisation
(e.g. `ChartContainer` in `Trade.jsx`). Real-time candle updates still come from the public
WebSocket stream (`@kline_<interval>`) — only the initial REST fetch is affected by this rule.

---

## Layout rules

- **Navbar:** fixed top, full width, 56px tall, `bg-title-bg` (`#0a0d13`) `border-b border-slate-700/50`
  - Logo: "ENMA" text, `text-emerald-400 font-medium`, left-aligned
  - Nav items (desktop, `md:flex`, hidden below `md`): **Dashboard, Trade, Strategies, Risk Dashboard, Backtest, Strategy Lab, AlgoTrading, Order History** (8 items, `client/src/components/layout/Navbar.jsx`'s `navItems`). `Settings` is a standalone icon button next to the avatar (not in the nav item list). Strategy Lab (`/lab`) added 2026-07-19 (Plan 10 Phase 2).
  - Nav item default: `text-slate-400`, transparent bg, `border-b-2 border-transparent`
  - Nav item hover: `text-gray-100`, `bg-slate-800/50`
  - Nav item active: `text-emerald-400`, `bg-emerald-400/10`, `border-b-2 border-emerald-400`
  - Nav item focus (keyboard): `focus-visible:ring-2 focus-visible:ring-emerald-500`
  - **Mobile (`<md`):** hamburger toggle (`Menu`/`X` icon, `aria-label`/`aria-expanded`/`aria-controls="mobile-nav-menu"`) opens a full-width drawer (`#mobile-nav-menu`) listing the same items + a running-session count badge on AlgoTrading. This is an intentional improvement over the original "desktop only" spec.
  - Avatar button: `aria-haspopup="menu"`, `aria-expanded`, `aria-label="User menu"`. Circle shape uses the Tailwind arbitrary class `[border-radius:50%]` (not inline `style=`) because the global `tailwind.config.js` sets `borderRadius: 0`, so `rounded-full` resolves to square corners.
- **PageWrapper:** `pt-[56px]` to clear navbar, `bg-[#060a0f]` (deepest layer), full width, **no padding** — content is edge-to-edge
- **PageHeader:** full-width bar with `px-6 py-3 border-b border-slate-700/50 bg-title-bg title-fade` — not a floating title, it's a connected header row
- **Page content padding:** none — panels go edge-to-edge; use `border-r`/`border-b`/`divide-*` for separation
- **Cards:** `bg-[#0d1117] border border-slate-700/50 shadow-2xl hover:border-slate-600/70 transition-all duration-300` — **no `rounded-xl`** (global borderRadius is 0px)
- **Panel grids:** always `gap-0` — sections are connected, not floating
- **No Rounded Corners (global):** All `borderRadius` values are `0px` via `tailwind.config.js` theme override. Never write `rounded-*` classes.
- **No Sidebar component** — Sidebar.jsx is removed; all navigation lives in the top navbar (Navbar.jsx)

## Dashboard page spec

The Dashboard (`/`) leads with **live account data** (balances + prices), then backtest metrics.
Section order: `TickerStrip` → `AccountOverview` → `BacktestKpiStrip` → Recent Live Runs + Recent
Backtests (2-col) → `StrategyLeaderboard` → `CollapsibleSection`(TimescaleDB Cache, default closed).
Each section loads independently — a live-data failure must not blank the backtest sections. Full spec:
`workspace/docs/features/dashboard/SPEC.md`.

### Components (all under `client/src/features/dashboard/`)

**TickerStrip** — live price strip. Symbols = `['BTCUSDT','ETHUSDT'] ∪ openPositionSymbols`, deduped,
capped at 8, memoized. Inner `TickerItem` isolates per-symbol state and subscribes via
`useBinanceWS(`${sym}@ticker`, cb)` (browser-direct Binance public WS — no server load). Never uses
`!ticker@arr`. Price `formatPrice`, 24h % `formatSignedPct` (emerald/red).

**AccountOverview** — 4 tiles (`grid grid-cols-2 lg:grid-cols-4 gap-0`): Testnet Balance, Mainnet
Balance (read-only), Unrealized P&L (testnet), Margin Balance + open-position count. Data from
`useAccountBalances()` (`GET /api/v1/trade/balances`) + `useTradePositions()`. Handles per-env
not-configured / fetch-error states.

**BacktestKpiStrip** — condensed 8-metric strip (`grid-cols-2 sm:grid-cols-4 xl:grid-cols-8`),
replacing the old 8 large `StatCard`s: Total Runs, Best Strategy, Avg Win Rate, Profit Factor, Sharpe,
Sortino, Max Drawdown (red when >0), Expectancy (signed emerald/red).

**CollapsibleSection** — toggle wrapper (default closed) demoting the candle inventory.

**StatCard** — legacy single-metric card; **no longer used by Dashboard** (orphaned, file retained).

**CachedCandlesTable** — table of OHLCV ranges currently stored in TimescaleDB.
- Data source: `GET /api/v1/candles/cached` via `useCachedCandles()` hook
- Columns: Symbol, Timeframe, Exchange, Type (spot/futures), Start Date, End Date, Total Candles
- Dates rendered as `YYYY-MM-DD` (date part only, not full ISO timestamp)
- Total Candles formatted with thousands separator
- Must handle loading skeleton and empty state ("No candle data cached yet.")
- No pagination — all rows shown (at most ~50 symbol×timeframe combinations expected)

**RecentActivityTable** — last 5 completed backtest runs.
- Data source: `GET /api/v1/backtest?limit=5` via existing `useBacktestList({ limit: 5 })` hook
- Columns: Strategy, Symbol, Timeframe, Win Rate, Net Profit, Date
- Each row has a "View" button that navigates to `/backtest?jobId={id}`
- Must handle loading skeleton and empty state ("No backtests run yet.")

**StrategyLeaderboard** — per-strategy averaged metrics across all runs.
- Data source: `GET /api/v1/dashboard/stats` (leaderboard array) via `useDashboardStats()` hook
- Columns: Strategy, Runs, Avg Win Rate, Avg Net Profit, Avg Sharpe
- Sorted by Avg Net Profit descending (server returns pre-sorted)
- Must handle loading skeleton and empty state ("Run your first backtest to see the leaderboard.")

### Hooks (`client/src/hooks/useDashboard.js`)

```js
// Query keys follow existing pattern
useDashboardStats()   // ['dashboard', 'stats']  → GET /api/v1/dashboard/stats
useCachedCandles()    // ['candles', 'cached']   → GET /api/v1/candles/cached
```

Both hooks follow the standard TanStack Query pattern used by all other hooks in this project.

---

## Error handling rules

- **Never use `alert()` for errors.** `alert()` blocks the browser thread and cannot be styled.
- Always use local `errorMessage` state (string | null) rendered as an inline error banner inside the page.
- Banner style: `bg-red-950/20 border border-red-800/40 rounded-lg p-4` with `AlertTriangle` icon from lucide-react and `text-red-400` text.
- Clear `errorMessage` (set to null) when the user initiates a new run/action attempt.

---

## Backtest page spec

- `Backtest.jsx` is state management + layout wiring only. The launch wizard, history list, and KPI cards are extracted to `features/backtest/`.
- **Launch flow:** a "New Backtest" button in the `PageHeader` opens `NewBacktestWizard` in a `Dialog` (mirrors the AlgoTrading "New Bot" pipeline). The wizard steps through Strategy → Parameters (skipped when the strategy exposes no PARAMS) → Market → Settings → Review, then calls `onRun(config)` which closes the dialog and triggers `handleRun`. There is no longer an inline config form; the left column is Run History only. While a run is active the "New Backtest" button is disabled and a "Cancel Backtest" button renders inside the running progress card.
- `NewBacktestWizard.jsx` — owns all config inputs (incl. per-run strategy `alphaParams`) and the multi-step UI; emits the full run config via `onRun`
- `BacktestHistory.jsx` — owns the history sidebar list with emerald `border-l-2 border-emerald-500` highlight for selected item
- `BacktestMetricCard.jsx` — single reusable KPI card; replaces 6 inline copies; props: `label`, `value`, `subtext`, `icon`
- KPI cards: 3 per row, 2 rows (grid-cols-3) — not 6 in one row
- Quantity format: max 6 decimal places (`.toFixed(6)` or similar)
- Price format: 2 decimal places with `$` prefix
- Progress message: human-readable string showing phase + percentage (e.g. `"Fetching candles... 15%"` or `"Simulating BTC-USDT 1h — 60%"`)
- History list: no fixed `max-height`; scrollable within the page layout
- Selected history item: clear emerald left border highlight (`border-l-2 border-emerald-500`)
- **`?jobId=` query param:** on mount, read `jobId` from `useSearchParams()`. If present, auto-select that result in the history list and fetch its data. Main results are retrieved via `GET /api/v1/backtest/{jobId}`, and associated trades are loaded asynchronously using pagination via `GET /api/v1/backtest/{jobId}/trades` (default page size 50). This supports deep-linking from the Dashboard RecentActivityTable. If the jobId is not found, show a "Result not found" inline error and fall back to the normal empty state.
- **Trades rendering:** The trades list in the backtest result details is paginated and dynamically fetched via the `useBacktestTrades` hook, avoiding memory bloat or rendering lag.
- **Equity curve:** Renders downsampled data points ($\le$ 1,000 points, pre-filtered by the engine) to maintain UI chart responsiveness and rapid loading.


## useCandles.js rules

- Only `useSymbols()` hook is exported — `useAvailableImports()` and `useImportCandles()` are removed
- `useSymbols()` calls `GET /api/v1/candles/symbols` and returns `{ futures, spot }`
- No other candle hooks exist in this file

---

## Styling rules

> **Single source of truth:** `workspace/docs/core/UI_STYLE_GUIDE.md` — the canonical
> midnight-blue trading-terminal palette, typography, component patterns, and the full
> **What to Avoid** list. Read it before writing or changing any `className`. To restyle an
> existing component/page to the guide, run the **`/restyle-ui`** skill. The rules below are the
> condensed working set; if they ever disagree with the guide, the guide wins.

- Dark theme by default — the app is a trading dashboard, always dark
- Color palette (use these Tailwind classes consistently — midnight blue, not warm gray):
  - Page / deepest layer: `bg-[#060a0f]` (also terminal/log boxes)
  - Panel rows: `bg-[#080b10]` (row 1) / `bg-[#0a0d13]` (row 2, inputs/selects)
  - Card / panel base: `bg-[#0d1117]`
  - Borders: cards/dividers `border-slate-700/50`; inner tiles `border-slate-700/40`; table rows `border-slate-700/30`
  - Text primary / values: `text-gray-100`
  - Text secondary labels / body copy: `text-slate-400` (`text-slate-500` on `#060a0f` is ~3.0:1, below WCAG AA 4.5:1 — do not use it for labels, descriptions, or any copy under 18px). `text-slate-500` is reserved for purely decorative/muted captions at ≥18px only. Section titles: `text-gray-300`.
  - Profit/positive P&L: `text-emerald-400`, `bg-emerald-400/10` — **never `text-green-400`**
  - Loss/negative P&L: `text-red-400`, `bg-red-400/10`
  - Primary action: `bg-emerald-600 hover:bg-emerald-700`; destructive: `bg-red-600 hover:bg-red-700`
  - Warning / caution: `text-amber-400`, `bg-amber-400/10`
  - Monospaced data (prices, qty, timestamps): `font-mono tabular-nums`
- **Avoid** `bg-gray-900`/`bg-gray-800` panel backgrounds (too warm), `text-gray-500` labels
  (use `text-slate-400`), glass buttons for primary/destructive actions, `opacity-50` to dim rows,
  and inline styles. See the guide's "What to Avoid".
- **Favorites & Highlights:** Stars and interactive favorites elements follow standard highlighting (yellow when selected; e.g., `text-yellow-400`). P&L coloring rules (`text-emerald-400` / `text-red-400`) apply to green/red ticker price feeds only.

---

## Number & date/time formatting policy

- **Always use `src/utils/formatters.js`** — never inline `toFixed`, `toLocaleString`, `toLocaleDateString`, or `toLocaleTimeString`. Local one-off `fmtPrice`/`fmtQty`/`fmtNum` helpers are drift and must be removed in favor of the canonical functions.
- **Precision:** prices `formatPrice` (2 dp, `$` prefix, thousands separator); quantities `formatQty` (max 6 dp, trimmed); percentages `formatPct`/`formatSignedPct`/`formatPercent`; large aggregates (notional, volume) `formatCompact` (e.g. `$1.2M`).
- **Dates/times:** `formatDateTime`/`formatDate` render in **UTC by default** and append a `UTC` suffix so traders in different timezones read the same absolute time. Pass `{ local: true }` only where the local viewing timezone is explicitly relevant (rare). The Trade page header shows a small "UTC" indicator next to timestamps for this reason.

## Chart rules (Recharts)

- Equity curve: `LineChart` with `CartesianGrid`, `Tooltip`, `ResponsiveContainer`
- Drawdown: `AreaChart` with negative fill
- Trade distribution: `BarChart`
- All charts use dark theme colors matching the palette above:
  - Axis ticks `fill: '#94a3b8'` (slate-400), axis/grid stroke `#1e293b` (slate-800)
  - Baseline reference line `stroke="#4B5563" strokeDasharray="3 3"`
  - Equity line `#34d399` (emerald-400) when positive, `#f87171` (red-400) when negative
- Chart wrappers live in `src/components/charts/`
- Never use chart libraries other than Recharts

---

## What Claude Code must NOT do in client/

- Add a state management library other than Zustand + TanStack Query
- Use CSS modules, styled-components, or inline styles
- Call the Python engine directly (all calls go through `server/`)
- Store sensitive data (API keys, tokens beyond JWT) in localStorage or state
- Use class components or legacy React patterns
