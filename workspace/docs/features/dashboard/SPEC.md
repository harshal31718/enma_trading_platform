# Feature: Dashboard

**Status:** Implemented
**Last updated:** 2026-07-02 — redesigned: added live account data (testnet + mainnet balances via
`AccountOverview`, live prices via `TickerStrip`), condensed the 8 KPI cards into `BacktestKpiStrip`,
demoted the candle inventory into a collapsible section, and reordered sections to lead with
live/account data. Previous version was backtest-metrics only.

---

## What It Does

The home page. Now leads with **live account data** — a live price strip (open-position symbols +
BTC/ETH majors) and an account overview showing both **testnet and mainnet balances** — followed by
backtest performance: condensed aggregate KPIs, a strategy leaderboard, recent backtest and
live-session activity with deep-links, and a collapsible cached-candle inventory. Stats are scoped
to the logged-in user.

**Section order (top → bottom):** TickerStrip → AccountOverview → BacktestKpiStrip → Recent Live Runs
+ Recent Backtests (2-col) → StrategyLeaderboard → TimescaleDB Cache (collapsible, default closed).

**Balances:** `GET /api/v1/trade/balances` returns both environments. Mainnet is **read-only**
(balance display only — see `DECISIONS.md` and `API_CONTRACTS.md`); all trading stays on testnet.
The testnet side rides the manual-trade WebSocket (`useTradeStream` invalidates `['trade','balances']`
on `ACCOUNT_UPDATE`); the mainnet side is 60s-polled.

**Live prices:** `TickerStrip` reuses the browser-direct Binance public WebSocket
(`useBinanceWS(<sym>@ticker)`, `client/src/lib/binanceWS.js`) — no server load. Streams are capped at
8 symbols (majors first, then open-position symbols); `!ticker@arr` is never used.

---

## Data Flow

```
Client navigates to Dashboard
        ↓
TanStack Query fires 3 parallel fetches:

1. GET /api/v1/dashboard/stats
        ↓
   Server proxies → engine GET /dashboard/stats with { params: { userId: req.user.id } }
        ↓
   Engine queries MongoDB backtestResults (status='completed', scoped to userId):
     - totalRuns: COUNT(*)
     - averageWinRate: MEAN(metrics.winRate)
     - bestStrategy: strategyName with highest averageNetProfit
     - avgProfitFactor, avgSharpe, avgSortino, worstDrawdown, avgExpectancy, latestRunId
     - leaderboard: GROUP BY strategyName → runs, avgWinRate, avgNetProfit, avgSharpe
                    SORT BY avgNetProfit DESC
        ↓
   Returns: { stats: {...}, leaderboard: [...] }

1b. GET /api/v1/dashboard/performance-calendar
        ↓
   Server proxies → engine GET /dashboard/performance-calendar (user-scoped)
        ↓
   Returns: { calendar: [{ date, netProfit, tradeCount }] } — backs `DashboardCalendar.jsx`,
   built but not yet wired into this page (candidate for wiring in a future pass).

2. GET /api/v1/candles/cached
        ↓
   Server proxies → engine GET /candles/cached
        ↓
   Engine queries TimescaleDB:
     SELECT exchange, symbol, timeframe, instrument_type,
            MIN(time), MAX(time), COUNT(*)
     FROM candles GROUP BY ...
        ↓
   Returns: { cached: [...] }

3. GET /api/v1/backtest?limit=5
        ↓
   Server queries MongoDB backtestResults (last 5 completed, scoped to req.user.id)
        ↓
   Returns paginated backtest list
        ↓
Client renders the inline RecentRunsPanel (backtests) and RecentLiveRunsPanel (algo sessions)
with "View" buttons → /backtest?jobId={id} (deep-link to result)
```

---

## Service Responsibilities

| Layer | Owns | Does NOT own |
|-------|------|-------------|
| Client | Rendering KPI cards, leaderboard table, candle inventory table | Any computation |
| Node server | Route proxy for /dashboard/stats, /candles/cached | Aggregation logic |
| Python engine | All MongoDB aggregation, all TimescaleDB group-by queries | UI rendering |

---

## Key Invariants

- **Completed runs only.** Dashboard aggregations filter to `status='completed'` — failed, cancelled, or queued jobs are excluded.
- **Server does no aggregation.** All metric computation happens in the engine. The Node server is a pure proxy for dashboard and candle routes. (`/trade/balances` is the exception — the server fans out two engine `/trade/account` calls and trims the response, but does no math.)
- **Mainnet is read-only.** The mainnet balance is display-only; `X-Binance-Mode` is pinned to `testnet` on all trading routes (`requireBinanceCredentials`). Live prices come browser-direct from Binance public WS, never proxied.
- **Recent activity is last 5.** The backtest list is capped at 5 items using the existing `GET /api/v1/backtest?limit=5` endpoint — no separate "recent" endpoint.
- **Granular loading.** Each section loads independently — a balances/positions failure must not blank the backtest sections.

---

## UI Components

| Component | Data Source | Description |
|-----------|-------------|-------------|
| `TickerStrip` | Binance public WS (`<sym>@ticker`) | Live price + 24h % for BTC/ETH majors + open-position symbols (capped at 8). Browser-direct, no server load. Per-symbol state isolation via inner `TickerItem`. |
| `AccountOverview` | `/trade/balances`, `/trade/positions` | 4 tiles: Testnet Balance, Mainnet Balance (read-only), Unrealized P&L (testnet), Margin Balance + open-position count. Handles not-configured / fetch-error states per env. |
| `BacktestKpiStrip` | `/dashboard/stats` | Condensed 8-metric strip (Total Runs, Best Strategy, Avg Win Rate, Profit Factor, Avg Sharpe, Avg Sortino, Max Drawdown, Expectancy) — replaces the 8 large `StatCard`s. |
| `StrategyLeaderboard` | `/dashboard/stats` → `leaderboard` | Per-strategy: runs, avg win rate, avg net profit, avg Sharpe |
| `RecentRunsPanel` (inline in `Dashboard.jsx`) | `/backtest?limit=5` | Last 5 completed backtests with deep-link "View" button — **replaces** `RecentActivityTable.jsx`, which still exists on disk but is orphaned (zero imports) |
| `RecentLiveRunsPanel` (inline in `Dashboard.jsx`) | `/algo/sessions` | Recent live/algo sessions (rendered left of Recent Backtests) |
| `CollapsibleSection` | — | Toggle wrapper (default closed) demoting the candle inventory below the fold |
| `CachedCandlesTable` | `/candles/cached` | Symbol, Timeframe, Exchange, Type, Date Range, Total Candles — inside `CollapsibleSection` |
| `StatCard` | — | **No longer used by Dashboard** (replaced by `BacktestKpiStrip`). File retained; orphaned. |
| `DashboardCalendar` (built, unwired) | `/dashboard/performance-calendar` | Performance-calendar heatmap — component exists but is not rendered by `Dashboard.jsx` yet |

---

## Leaderboard Metrics

All metrics are per-strategy averages across all completed backtest runs for that strategy:

| Metric | Description |
|--------|-------------|
| `runs` | Total completed runs for this strategy |
| `averageWinRate` | Mean win rate (%, 2 decimal places) |
| `averageNetProfit` | Mean net profit in base currency (2 decimal places) |
| `averageSharpe` | Mean Sharpe ratio (2 decimal places) |

Sorted by `averageNetProfit` descending.

---

## REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/dashboard/stats` | Aggregate stats + strategy leaderboard (user-scoped) |
| GET | `/api/v1/dashboard/performance-calendar` | Per-day P&L calendar data (user-scoped, unwired in UI) |
| GET | `/api/v1/trade/balances` | Combined testnet + mainnet balance snapshot (`{ testnet, mainnet, fetchedAt }`); per-env `{configured, ok, totalWalletBalance, totalMarginBalance, totalUnrealizedProfit, availableBalance}`. Public route (JWT only), tolerates a missing/failing env. See `API_CONTRACTS.md`. |
| GET | `/api/v1/trade/positions` | Open positions (shared with Trade feature) — drives ticker symbols + open-position count |
| GET | `/api/v1/candles/cached` | Cached candle inventory (shared with Candle Management) |
| GET | `/api/v1/backtest?limit=5` | Recent backtests (shared with Backtest feature) |

---

## Related Files

| File | Role |
|------|------|
| `client/src/pages/Dashboard.jsx` | Main dashboard page |
| `client/src/features/dashboard/TickerStrip.jsx` | Live price strip (Binance public WS) |
| `client/src/features/dashboard/AccountOverview.jsx` | Testnet + mainnet balance tiles |
| `client/src/features/dashboard/BacktestKpiStrip.jsx` | Condensed 8-metric KPI strip |
| `client/src/features/dashboard/CollapsibleSection.jsx` | Toggle wrapper for demoted sections |
| `client/src/features/dashboard/StatCard.jsx` | Legacy KPI card — orphaned (superseded by `BacktestKpiStrip`) |
| `client/src/features/dashboard/StrategyLeaderboard.jsx` | Leaderboard table |
| `client/src/hooks/useTrade.js` | `useAccountBalances()` (+ existing trade hooks) |
| `server/src/controllers/trade.controller.js` | `getBalances` (fans out two engine `/trade/account` calls) |
| `client/src/features/dashboard/RecentActivityTable.jsx` | **Orphaned** — zero imports; superseded by the inline `RecentRunsPanel` in `Dashboard.jsx`. Candidate for removal. |
| `client/src/features/dashboard/DashboardCalendar.jsx` | Performance-calendar component — built but not wired into `Dashboard.jsx` |
| `client/src/features/dashboard/CachedCandlesTable.jsx` | Candle inventory table |
| `client/src/hooks/useDashboard.js` | `useDashboardStats()`, `useCachedCandles()` |
| `server/src/routes/dashboard.routes.js` | GET /stats, GET /performance-calendar |
| `server/src/controllers/dashboard.controller.js` | Proxy to engine, forwards `req.user.id` as a query param |
| `engine/routers/dashboard.py` | MongoDB aggregation logic for stats + leaderboard + performance calendar |
