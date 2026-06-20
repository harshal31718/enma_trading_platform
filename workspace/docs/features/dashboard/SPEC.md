# Feature: Dashboard

**Status:** Implemented  
**Last updated:** 2026-06-05

---

## What It Does

The home page. Shows an overview of backtest performance across all strategies: aggregate stats (total runs, best strategy, average win rate), a strategy leaderboard, recent backtest activity with deep-links to results, and a cached candle inventory from TimescaleDB.

---

## Data Flow

```
Client navigates to Dashboard
        ↓
TanStack Query fires 3 parallel fetches:

1. GET /api/v1/dashboard/stats
        ↓
   Server proxies → engine GET /dashboard/stats
        ↓
   Engine queries MongoDB backtestResults (status='completed'):
     - totalRuns: COUNT(*)
     - averageWinRate: MEAN(metrics.winRate)
     - bestStrategy: strategyName with highest average winRate
     - leaderboard: GROUP BY strategyName → runs, avgWinRate, avgNetProfit, avgSharpe
                    SORT BY avgNetProfit DESC
        ↓
   Returns: { stats: {...}, leaderboard: [...] }

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
   Server queries MongoDB backtestResults (last 5 completed)
        ↓
   Returns paginated backtest list
        ↓
Client renders RecentActivityTable with "View" buttons
  → /backtest?jobId={id}  (deep-link to result)
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
- **Server does no aggregation.** All metric computation happens in the engine. The Node server is a pure proxy for dashboard and candle routes.
- **No live trading data.** Dashboard shows backtest metrics and cached candle state only. Live session PnL is not surfaced here.
- **Recent activity is last 5.** The backtest list is capped at 5 items using the existing `GET /api/v1/backtest?limit=5` endpoint — no separate "recent" endpoint.

---

## UI Components

| Component | Data Source | Description |
|-----------|-------------|-------------|
| `StatCard` × 4 | `/dashboard/stats` | Total Runs, Best Strategy, Avg Win Rate, (reserved) |
| `StrategyLeaderboard` | `/dashboard/stats` → `leaderboard` | Per-strategy: runs, avg win rate, avg net profit, avg Sharpe |
| `RecentActivityTable` | `/backtest?limit=5` | Last 5 completed backtests with deep-link "View" button |
| `CachedCandlesTable` | `/candles/cached` | Symbol, Timeframe, Exchange, Type, Date Range, Total Candles |

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
| GET | `/api/v1/dashboard/stats` | Aggregate stats + strategy leaderboard |
| GET | `/api/v1/candles/cached` | Cached candle inventory (shared with Candle Management) |
| GET | `/api/v1/backtest?limit=5` | Recent backtests (shared with Backtest feature) |

---

## Related Files

| File | Role |
|------|------|
| `client/src/pages/Dashboard.jsx` | Main dashboard page |
| `client/src/features/dashboard/StatCard.jsx` | Reusable KPI card component |
| `client/src/features/dashboard/StrategyLeaderboard.jsx` | Leaderboard table |
| `client/src/features/dashboard/RecentActivityTable.jsx` | Last 5 backtests with deep-link |
| `client/src/features/dashboard/CachedCandlesTable.jsx` | Candle inventory table |
| `client/src/hooks/useDashboard.js` | `useDashboardStats()`, `useCachedCandles()` |
| `server/src/routes/dashboard.routes.js` | GET /stats |
| `server/src/controllers/dashboard.controller.js` | Proxy to engine |
| `engine/routers/dashboard.py` | MongoDB aggregation logic for stats + leaderboard |
