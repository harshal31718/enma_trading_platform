# Dashboard Page Restructure Plan

## Goal
Redesign the Dashboard (`/`) to provide a more comprehensive, at-a-glance overview of backtest performance and cache status while adhering to the constraint that it shows only simulation metrics (no live trading data). The goal is to enhance user insight into strategy performance, risk metrics, and data availability without overwhelming the user.

## Proposed Changes

### 1. Enhanced Stat Cards
Replace or supplement the current four stat cards with a richer set of key performance indicators (KPIs) aggregated across all backtest runs. Each stat card will follow the existing `StatCard` component pattern.

**Proposed Stat Cards:**
- **Total Runs**: Total number of completed backtests (unchanged).
- **Best Strategy**: Strategy with highest average net profit (unchanged).
- **Average Win Rate**: Overall win rate across all trades in all backtests (formatted as %).
- **Average Profit Factor**: Gross profit / gross loss across all trades.
- **Average Sharpe Ratio**: Risk-adjusted return measure.
- **Average Sortino Ratio**: Downside-risk adjusted return.
- **Maximum Drawdown**: Largest peak-to-trough equity decline (as %).
- **Expectancy**: Average profit per trade.

*Layout:* Use a responsive grid (e.g., `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4`) to allow 2-4 columns based on screen size.

### 2. New Visualization Widgets
Introduce lightweight charts to provide visual trends without heavy charting libraries (using existing Recharts wrappers or simple SVG sparklines if needed).

#### a. Equity Curve Sparkline
- **Description**: A small line chart showing equity growth over time for the top-performing strategy or an equally-weighted aggregate of all strategies.
- **Data Source**: New endpoint `GET /api/v1/dashboard/equity-curve` (returns time-series of equity points) or compute from existing `backtestResults` data.
- **Styling**: Use emerald-400 for upward trends, red-400 for drawdowns; match existing chart aesthetics.

#### b. Drawdown Chart
- **Description**: An area chart showing historical drawdown periods.
- **Data Source**: New endpoint `GET /api/v1/dashboard/drawdown` or compute from equity curve.
- **Styling**: Red fill with transparency (`bg-red-400/20`).

#### c. Performance Calendar (Heatmap)
- **Description**: A month-view heatmap showing daily P&L (profit/loss) across all backtests, similar to the existing `BacktestCalendar` but smaller and optimized for dashboard.
- **Data Source**: New endpoint `GET /api/v1/dashboard/performance-calendar` (returns day-wise P&L aggregates).
- **Styling**: Profit cells in emerald-400/20, loss cells in red-400/20; neutral cells in slate-800/20.

### 3. Enhanced Tables
Keep existing tables but consider improvements:

#### a. Recent Activity Table
- **Enrichment**: Add columns for Profit Factor and Sharpe Ratio per run (if available).
- **Action**: Keep "View" button linking to `/backtest?jobId={id}`.

#### b. Strategy Leaderboard
- **Enrichment**: Add columns for Sortino Ratio and Max Drawdown per strategy.
- **Sorting**: Default by Avg Net Profit (descending), but allow sorting via column headers (if implementing client-side sorting; otherwise rely on server sorting).

#### c. Cached Candles Table
- **No changes** needed; retains columns: Symbol, Timeframe, Exchange, Type, Start Date, End Date, Total Candles.

### 4. Layout Structure
Proposed responsive grid (using Tailwind CSS grid):

#### Large Screen (lg: and up)
```
------------------------------------------------------------
| Stat Cards (6 items, 2 rows of 3)                        |
------------------------------------------------------------
| Equity Sparkline   | Drawdown Chart   | Recent Activity |
| (small)            | (small)          | Table           |
------------------------------------------------------------
| Performance Calendar (full width)                        |
------------------------------------------------------------
| Cached Candles Table (full width)                        |
------------------------------------------------------------
```

#### Medium Screen (md: and up)
```
------------------------------------------------------------
| Stat Cards (4 items, 2 rows of 2)                        |
------------------------------------------------------------
| Equity Sparkline   | Recent Activity Table        |
| (small)            |                              |
------------------------------------------------------------
| Drawdown Chart     | Strategy Leaderboard         |
| (small)            |                              |
------------------------------------------------------------
| Performance Calendar (full width)                        |
------------------------------------------------------------
| Cached Candles Table (full width)                        |
------------------------------------------------------------
```

#### Small Screen (sm: and down)
```
------------------------------------------------------------
| Stat Cards (stacked vertically)                          |
------------------------------------------------------------
| Equity Sparkline (full width)                            |
------------------------------------------------------------
| Drawdown Chart (full width)                              |
------------------------------------------------------------
| Performance Calendar (full width)                        |
------------------------------------------------------------
| Recent Activity Table (full width)                       |
------------------------------------------------------------
| Strategy Leaderboard (full width)                        |
------------------------------------------------------------
| Cached Candles Table (full width)                        |
------------------------------------------------------------
```

*Note: Exact arrangement can be adjusted based on user testing and priority.*

### 5. Additional Features
- **Timeframe Selector**: Add a dropdown (e.g., "Last 30 Days", "Last 90 Days", "All Time") to filter data in charts and tables (excluding cache table which is static).
- **Auto-Refresh**: Optional toggle to refresh dashboard data every N seconds (via TanStack Query refetchInterval).
- **Empty States**: Improved empty/loading states with illustrative graphics or messages.
- **Error Handling**: Consistent error banners using existing pattern (`bg-red-950/20 border border-red-800/40`).

### 6. Data Requirements
To support the new widgets, the following backend endpoints may need to be created or extended (to be implemented by backend team):
- `GET /api/v1/dashboard/aggregates` → Returns aggregated metrics (win rate, profit factor, sharpe, sortino, max drawdown, expectancy).
- `GET /api/v1/dashboard/equity-curve` → Returns time-series equity data.
- `GET /api/v1/dashboard/drawdown` → Returns drawdown series.
- `GET /api/v1/dashboard/performance-calendar` → Returns day-wise P&L for heatmap.

If creating new endpoints is not feasible, consider deriving some metrics from existing endpoints (e.g., `/api/v1/dashboard/stats` already returns leaderboard data; could aggregate further on client side, but note performance implications for large datasets).

### 7. Implementation Steps (for future reference)
1. Update `src/hooks/useDashboard.js` with new hooks for each data source.
2. Modify `client/src/features/dashboard/` components:
   - Enhance `StatCard.js` to accept optional icon props (already supports icon).
   - Create new chart components (e.g., `EquitySparkline.js`, `DrawdownChart.js`) using Recharts wrappers or lightweight SVG.
   - Enhance existing table components with new columns if needed.
3. Update `Dashboard.jsx` to implement the new layout using Tailwind grid.
4. Add timeframe selector component (reusing existing UI patterns).
5. Update any relevant documentation in `workspace/docs/`.

### 8. Compliance with Enma Rules
- **Single-user**: No `user_id` introduced.
- **Data Ownership**: Dashboard continues to show only backtest results and cache data (engine-owned).
- **Aesthetics Invariant**: All profit metrics use `emerald-400`, loss metrics use `red-400`.
- **No Redux**: State managed via React hooks and TanStack Query.
- **Dev Environment**: Changes remain within client/; no Docker or host modifications.
- **File Edit Preference**: Use direct Edit/Write tools for file changes.

### 9. Open Questions
- Should the equity curve show aggregate equity across all strategies or just the best strategy? (Aggregation may require normalization; per-strategy may be more insightful.)
- What is the performance impact of computing aggregates on the client vs. adding backend endpoints?
- Should the performance calendar show absolute P&L or percentage return? (Percentage may be more comparable across different capital levels.)

---
*This plan is intended to guide the redesign of the dashboard page. Implementation should follow the Enma development workflow, including running `/sync-spec` after code changes and potentially invoking the `drift-reviewer` subagent for large refactors.*