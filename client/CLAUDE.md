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
- Radix UI primitives (`@radix-ui/react-dialog`, `-dropdown-menu`, `-label`, `-select`, `-tabs`, `-tooltip`) — unstyled accessible components
- `lucide-react` for icons
- `clsx` + `tailwind-merge` + `class-variance-authority` — utility-class helpers (used in `src/lib/utils.js`)
- **Dev:** `vitest`, `@testing-library/react`, `msw` (API mocking), `puppeteer` (E2E)

---

## Folder structure

```
client/
├── public/
├── src/
│   ├── components/      ← shared reusable components
│   │   ├── ui/          ← generic UI (Button, Input, Modal, Card, Badge, PageHeader, skeleton)
│   │   │                   Note: DataTable.jsx, EmptyState.jsx, StatusBadge.jsx, and the
│   │   │                   original StatCard.jsx have been deleted — they were never imported.
│   │   ├── charts/      ← Recharts wrappers (EquityCurve.jsx only — DrawdownChart/CandleChart do not exist)
│   │   ├── layout/      ← Navbar.jsx, PageWrapper.jsx (no Sidebar)
│   │   ├── algo/        ← AlgoTrading feature components
│   │   │   ├── NewSessionWizard.jsx  ← multi-step wizard for starting a bot session
│   │   │   ├── SessionCard.jsx       ← single live session display card
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
│   │   │   └── StrategyLeaderboard.jsx ← per-strategy averaged metrics
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
│   │   ├── useTrade.js            ← TanStack Query hooks: useTradeAccount(), useTradePositions(), useTradeOpenOrders(), useTradeSymbolConfig(symbol), useChangeLeverage(), useChangeMarginType(), usePlaceOrder(), usePlaceOrderWithTpSl(), useCancelOrder(), useClosePosition(), useCancelAllOrders()
│   │   ├── useAlgoSessions.js     ← TanStack Query hooks for /api/v1/algo/* endpoints (includes useStartChaos)
│   │   ├── useExchangeSettings.js ← TanStack Query hooks for /api/v1/settings/exchange
│   │   ├── useOcoMonitor.js       ← monitors OCO order fill/cancel state via polling
│   │   ├── useOrderHistory.js     ← useOrderHistory({ page, limit, filters }) → GET /api/v1/order-history
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
│   │   ├── AlgoTrading.jsx    ← route: /algo (algo bot session management)
│   │   └── OrderHistory.jsx   ← route: /order-history (paginated trade log; not in navbar)
│   ├── store/
│   │       Note: useUIStore.js has been deleted — it tracked sidebar state that no longer exists.
│   ├── utils/
│   │   ├── formatters.js    ← formatQty, formatPrice, formatPct, formatPnl, formatSignedPct
│   │   └── symbolLimits.js  ← per-symbol precision/tick-size rules for order form validation
│   │       ├── formatQty(value)        → max 6 decimal places, trimmed
│   │       ├── formatPrice(value)      → "$1,234.56" (2 dp, thousands sep)
│   │       ├── formatPct(value)        → "32.41%" (unsigned)
│   │       ├── formatPnl(value)        → { value: "+$123.45", isPositive: bool }
│   │       └── formatSignedPct(value)  → "+32.41%" or "-8.20%" (always shows sign)
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
  - Connection manager `src/lib/binanceWS.js` manages a single `WebSocket` connection to `wss://fstream.binance.com/ws` (or `wss://fstream.binance.com/stream`).
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

- **Navbar:** fixed top, full width, 56px tall, `bg-[#0a0d13] border-b border-slate-700/50`
  - Logo: "Enma" text, `text-emerald-400 font-medium`, left-aligned
  - Nav items: horizontal, left-aligned after logo — **Dashboard, Strategies, Backtest, Trade, AlgoTrading, Settings** (6 items; Import Candles is removed permanently)
  - Nav item default: `text-slate-400`, transparent bg
  - Nav item hover: `text-gray-100`, `bg-slate-800/50`
  - Nav item active: `text-emerald-400`, `bg-emerald-400/10`, `border-b-2 border-emerald-400`
  - Desktop only — no mobile hamburger menu
- **PageWrapper:** `pt-[56px]` to clear navbar, `bg-[#060a0f]` (deepest layer), full width, **no padding** — content is edge-to-edge
- **PageHeader:** full-width bar with `px-6 py-3 border-b border-slate-700/50 bg-title-bg title-fade` — not a floating title, it's a connected header row
- **Page content padding:** none — panels go edge-to-edge; use `border-r`/`border-b`/`divide-*` for separation
- **Cards:** `bg-[#0d1117] border border-slate-700/50 shadow-2xl hover:border-slate-600/70 transition-all duration-300` — **no `rounded-xl`** (global borderRadius is 0px)
- **Panel grids:** always `gap-0` — sections are connected, not floating
- **No Rounded Corners (global):** All `borderRadius` values are `0px` via `tailwind.config.js` theme override. Never write `rounded-*` classes.
- **No Sidebar component** — Sidebar.jsx is removed; all navigation lives in the top navbar (Navbar.jsx)

## Dashboard page spec

The Dashboard (`/`) is a simulation metrics hub. It has no live trading data — it shows backtest history and cached candle state only.

### Components (all under `client/src/features/dashboard/`)

**StatCard** — generic display card for a single numeric metric.
- Props: `title` (string), `value` (string | number), `subtitle` (string, optional)
- Grid layout: 4 cards in one row (`grid grid-cols-4 gap-0`)
- Cards: **Total Runs** (totalRuns), **Best Strategy** (bestStrategy name), **Avg Win Rate** (averageWinRate as %, 1 decimal), **Cached Symbols** (count of distinct rows in CachedCandlesTable)
- Style: `bg-[#0d1117] border border-slate-700/50 p-4` (uses the shared `Card` component — no rounded corners)
- Value text: `text-2xl font-semibold tabular-nums text-gray-100`; title: `text-[11px] uppercase tracking-wider text-slate-400`

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
  - Text secondary labels: `text-slate-400`; muted/supporting: `text-slate-500`; section titles: `text-gray-300`
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
