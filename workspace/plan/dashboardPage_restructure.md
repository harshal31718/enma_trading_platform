# Dashboard Page Restructure Plan

**Status:** Proposed — not implemented. Seq #3 in `workspace/plan/INDEX.md`.
**Last audited:** 2026-06-24 against actual codebase.

---

## 1. Current State (verified)

### Files that exist today

| File | What it does |
|------|-------------|
| `client/src/pages/Dashboard.jsx` | 4 stat cards + 2-col grid (RecentActivity, Leaderboard) + CachedCandlesTable |
| `client/src/features/dashboard/StatCard.jsx` | Generic single-metric card — props: `title`, `value`, `subtext`, `icon` |
| `client/src/features/dashboard/RecentActivityTable.jsx` | Last 5 runs, "View" deep-link |
| `client/src/features/dashboard/StrategyLeaderboard.jsx` | Per-strategy: Runs, Avg Win Rate, Avg Net Profit, Avg Sharpe |
| `client/src/features/dashboard/CachedCandlesTable.jsx` | TimescaleDB candle inventory |
| `client/src/hooks/useDashboard.js` | `useDashboardStats()`, `useCachedCandles()` |
| `client/src/utils/backtest-analytics.js` | `getDailyStats`, `getWeeklyStats`, `getMonthlyStats`, `getQuarterlyStats` — already works on an array of trades |
| `client/src/components/charts/EquityCurve.jsx` | Full equity+drawdown chart (Recharts) — used by Backtest page |
| `features/backtest/BacktestCalendar.jsx` | Full Day/Week/Month/Quarter heatmap — used by Backtest Overview tab |
| `server/src/controllers/dashboard.controller.js` | `getStats()` — pure proxy to engine |
| `server/src/routes/dashboard.routes.js` | `GET /stats` only |
| `engine/routers/dashboard.py` | `GET /stats` — reads `backtestResults`, computes totalRuns + leaderboard |

### Current `/dashboard/stats` response shape

```json
{
  "stats": {
    "totalRuns": 12,
    "bestStrategy": "AdaptiveTrend",
    "averageWinRate": "0.38"
  },
  "leaderboard": [
    { "strategyName": "AdaptiveTrend", "runs": 3, "averageWinRate": "0.38",
      "averageNetProfit": "1543.91", "averageSharpe": "1.12" }
  ]
}
```

---

## 2. Proposed Changes

### 2a. Extended stat cards (4 → 8 KPI cards)

Add 4 new cards alongside the existing 3 (Best Strategy card stays as-is):

| Card | Field | Source |
|------|-------|--------|
| Total Runs | `stats.totalRuns` | existing |
| Best Strategy | `stats.bestStrategy` | existing |
| Avg Win Rate | `stats.averageWinRate` | existing |
| Avg Profit Factor | `stats.avgProfitFactor` | **extend `/stats`** |
| Avg Sharpe | `stats.avgSharpe` | **extend `/stats`** |
| Avg Sortino | `stats.avgSortino` | **extend `/stats`** |
| Max Drawdown | `stats.worstDrawdown` | **extend `/stats`** |
| Expectancy | `stats.avgExpectancy` | **extend `/stats`** |

Layout: `grid grid-cols-4 gap-0` (two rows of 4, same `StatCard` component, no new component needed).

### 2b. Equity sparkline

- A small Recharts `LineChart` showing the equity curve of the most recent completed run
- Reuses data already available via `GET /api/v1/backtest/:id` (field `equityCurve`)
- Requires `/stats` to also return `latestRunId` (jobId of most recently completed run)
- **New component:** `client/src/components/charts/EquitySparkline.jsx`

### 2c. Drawdown sparkline

- Derived client-side from the same `equityCurve` array — no new endpoint needed
- Running max → drawdown pct at each point
- **New component:** `client/src/components/charts/DrawdownSparkline.jsx`

### 2d. Performance calendar heatmap

- Day-level aggregate P&L across **all** completed runs (not one run)
- Reuses `backtest-analytics.js` `getDailyStats()` on the aggregated trades
- Requires new endpoint (engine must query `backtestTrades` across all jobIds)
- **New component:** `client/src/features/dashboard/DashboardCalendar.jsx` — lightweight version of `BacktestCalendar.jsx`; no tab selector (day view only); smaller cells

### 2e. Timeframe selector

- Client-side filter only — no new endpoint
- Dropdown: "Last 30 days" / "Last 90 days" / "All Time"
- Filters the data returned by `/performance-calendar` by cutting off entries outside the window
- State: `useState` in `Dashboard.jsx` only, passed as a prop to `DashboardCalendar`

---

## 3. Backend Changes

### 3a. Extend `engine/routers/dashboard.py` → `GET /stats`

Add to the same aggregation loop that already iterates `backtestResults`:

```python
# New fields to collect per run from metrics (already fetched):
# metrics.profitFactor, metrics.sortinoRatio, metrics.maxDrawdown, metrics.expectancy

# New fields on the response stats dict:
stats["avgProfitFactor"]  = f"{mean(profit_factors):.2f}"
stats["avgSharpe"]        = f"{mean(sharpes):.2f}"
stats["avgSortino"]       = f"{mean(sortinos):.2f}"
stats["worstDrawdown"]    = f"{max(drawdowns):.2f}"    # largest peak-to-trough pct
stats["avgExpectancy"]    = f"{mean(expectancies):.2f}"
stats["latestRunId"]      = most_recent_completed_job_id   # str | None
```

No new engine file needed — extend the existing `GET /stats` handler.

### 3b. New `GET /dashboard/performance-calendar` — engine

New route in `engine/routers/dashboard.py`.

Queries `backtestTrades` for all trades across all completed runs, aggregates by `exitAt` date:

```python
@router.get("/performance-calendar")
async def get_performance_calendar():
    db = get_database()
    # Fetch minimal fields from all trades
    cursor = db.backtestTrades.find(
        {},
        {"exitAt": 1, "pnl": 1, "_id": 0}
    )
    trades = await cursor.to_list(length=100_000)
    # Group by YYYY-MM-DD and sum pnl
    by_day = {}
    for t in trades:
        if not t.get("exitAt"):
            continue
        day = t["exitAt"][:10]  # "2024-03-15"
        by_day.setdefault(day, {"date": day, "pnl": 0.0, "trades": 0})
        by_day[day]["pnl"] += float(t.get("pnl", 0))
        by_day[day]["trades"] += 1
    return {"success": True, "data": {"days": sorted(by_day.values(), key=lambda x: x["date"])}}
```

### 3c. New server proxy — `server/src/controllers/dashboard.controller.js`

```js
async function getPerformanceCalendar(req, res, next) {
  try {
    const response = await engineClient.get('/dashboard/performance-calendar')
    res.json(ApiResponse.success(response.data.data))
  } catch (err) {
    next(new ApiError(503, 'ENGINE_UNAVAILABLE', 'Could not fetch calendar data from engine'))
  }
}
```

### 3d. New server route — `server/src/routes/dashboard.routes.js`

```js
router.get('/performance-calendar', getPerformanceCalendar)
```

---

## 4. Client Changes

### 4a. `client/src/hooks/useDashboard.js` — add two hooks

```js
// Fetches extended /stats (latestRunId, avgSharpe, etc.)
// useDashboardStats() already exists — NO change to hook, only the response shape changes

export function useDashboardCalendar() {
  return useQuery({
    queryKey: ['dashboard', 'performance-calendar'],
    queryFn: async () => {
      const res = await api.get('/api/v1/dashboard/performance-calendar')
      return res.data.data
    },
    staleTime: 60_000,
  })
}
```

### 4b. `client/src/hooks/useBacktest.js` — nothing new

`useBacktestResult(id)` already exists and fetches equityCurve. Used by Backtest page today.
No changes needed — Dashboard will call it with `latestRunId` from `/stats`.

### 4c. New `client/src/components/charts/EquitySparkline.jsx`

- Props: `data` (equityCurve array from existing `backtestResult.equityCurve`)
- Recharts `LineChart` at ~300×90px, no axes, no tooltip — pure visual sparkline
- Line color: `#34d399` (emerald-400) if final value > initial, `#f87171` (red-400) otherwise

### 4d. New `client/src/components/charts/DrawdownSparkline.jsx`

- Props: `data` (same equityCurve array)
- Derives drawdown series client-side: `runningMax = max so far; dd = (val - runningMax)/runningMax`
- Recharts `AreaChart` at ~300×90px, fill `#f87171/20`, stroke `#f87171`

### 4e. New `client/src/features/dashboard/DashboardCalendar.jsx`

- Props: `days` (array from `/performance-calendar`), `timeframe` ("30d"|"90d"|"all")
- Filters `days` to the selected window client-side
- Day cells: emerald-400 intensity for profit, red-400 for loss — same color logic as `BacktestCalendar`
- No tab UI (day view only); no `backtest-analytics.js` needed here (data already pre-aggregated by endpoint)

### 4f. `client/src/pages/Dashboard.jsx` — new layout

```
┌─────────────────────────────────────────────────────┐
│ PageHeader: "Dashboard"            [Timeframe ▼]    │
├────────────┬───────────┬───────────┬────────────────┤
│ Total Runs │Best Strat │ Avg WR    │ Profit Factor  │
├────────────┼───────────┼───────────┼────────────────┤
│ Avg Sharpe │Avg Sortino│ Drawdown  │  Expectancy    │
├────────────┴─────┬─────┴───────────┴────────────────┤
│ Equity Sparkline │ Drawdown Sparkline │ Recent Runs  │
├──────────────────┴────────────────────┴──────────────┤
│ Performance Calendar Heatmap (full width)            │
├──────────────────────────────────────────────────────┤
│ Strategy Leaderboard (full width)                    │
├──────────────────────────────────────────────────────┤
│ Cached Candles Table (full width)                    │
└──────────────────────────────────────────────────────┘
```

Grid: `grid-cols-4 gap-0` for stat cards; `grid-cols-3 gap-0` for sparkline row.

---

## 5. Data Flow

```
Dashboard.jsx
  ├── useDashboardStats()  →  GET /api/v1/dashboard/stats
  │     └── server proxy  →  GET engine:8000/dashboard/stats (extended)
  │                              reads backtestResults — totalRuns, leaderboard,
  │                              avgSharpe, avgSortino, worstDrawdown, avgExpectancy,
  │                              avgProfitFactor, latestRunId
  │
  ├── useBacktestResult(latestRunId)  →  GET /api/v1/backtest/:id
  │     (existing hook, existing endpoint — equityCurve already in response)
  │
  ├── useDashboardCalendar()  →  GET /api/v1/dashboard/performance-calendar
  │     └── server proxy  →  GET engine:8000/dashboard/performance-calendar
  │                              reads backtestTrades — day-level pnl aggregates
  │
  └── useCachedCandles()  →  existing, unchanged
```

---

## 6. Files to Create / Modify

| Action | File | Change |
|--------|------|--------|
| **Modify** | `engine/routers/dashboard.py` | Extend `GET /stats` with 5 new fields + `latestRunId`; add `GET /performance-calendar` |
| **Modify** | `server/src/controllers/dashboard.controller.js` | Add `getPerformanceCalendar()` proxy |
| **Modify** | `server/src/routes/dashboard.routes.js` | Add `GET /performance-calendar` route |
| **Modify** | `client/src/hooks/useDashboard.js` | Add `useDashboardCalendar()` |
| **Create** | `client/src/components/charts/EquitySparkline.jsx` | New Recharts sparkline |
| **Create** | `client/src/components/charts/DrawdownSparkline.jsx` | New Recharts sparkline |
| **Create** | `client/src/features/dashboard/DashboardCalendar.jsx` | Lightweight day heatmap |
| **Modify** | `client/src/pages/Dashboard.jsx` | New 8-card + sparkline + calendar layout |

No changes to `StatCard.jsx`, `RecentActivityTable.jsx`, `CachedCandlesTable.jsx`, or `StrategyLeaderboard.jsx` — existing components are reused as-is.

---

## 7. Open Questions (resolved)

| Question | Decision |
|----------|----------|
| Equity curve: aggregate or best strategy? | Most recent completed run (`latestRunId` from `/stats`). Avoids normalization complexity. |
| Aggregation: client or server? | Engine (server is pure proxy — per `server/CLAUDE.md` architecture rule). |
| Drawdown: new endpoint or client-derived? | Client-derived from the same equityCurve array. No new endpoint. |
| Timeframe selector: endpoint param or client filter? | Client-side filter on the `/performance-calendar` full dataset. Simpler, no query param needed. |
| Performance calendar: reuse `BacktestCalendar.jsx`? | No — that component expects per-trade arrays and has tabs. Create `DashboardCalendar.jsx` from the pre-aggregated days array. |
| Separate `/aggregates` endpoint or extend `/stats`? | Extend `/stats` — same loop, one round-trip, no new route needed. |

---

## 8. Constraints

- No `user_id` anywhere
- All computation in engine; server is pure proxy
- `emerald-400` for profit, `red-400` for loss (including sparkline colors)
- No `rounded-*` classes (global border-radius = 0px per tailwind.config.js)
- `gap-0` grids — connected panels, not floating cards
- No new npm/pip packages (Recharts already available; no new deps needed)
