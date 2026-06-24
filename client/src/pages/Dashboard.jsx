import { useState } from 'react'
import {
  Play,
  TrendingUp,
  Percent,
  Activity,
  Layers,
  GitBranch,
  TrendingDown,
  Target,
  ChevronRight,
} from 'lucide-react'

import PageWrapper from '../components/layout/PageWrapper'
import PageHeader from '../components/ui/PageHeader'
import { Select } from '../components/ui/select'
import { Skeleton } from '../components/ui/skeleton'
import { Button } from '../components/ui/button'
import { Badge } from '../components/ui/badge'
import StatCard from '../features/dashboard/StatCard'
import CachedCandlesTable from '../features/dashboard/CachedCandlesTable'
import StrategyLeaderboard from '../features/dashboard/StrategyLeaderboard'
import DashboardCalendar from '../features/dashboard/DashboardCalendar'
import EquitySparkline from '../components/charts/EquitySparkline'
import DrawdownSparkline from '../components/charts/DrawdownSparkline'
import { useNavigate } from 'react-router-dom'
import { formatPnl } from '../utils/formatters'

import { useDashboardStats, useCachedCandles, useDashboardCalendar } from '../hooks/useDashboard'
import { useBacktestsList, useBacktestResult } from '../hooks/useBacktest'

const DEFAULT_STATS = {
  totalRuns: 0,
  bestStrategy: 'N/A',
  averageWinRate: '0.00',
  avgProfitFactor: '0.00',
  avgSharpe: '0.00',
  avgSortino: '0.00',
  worstDrawdown: '0.00',
  avgExpectancy: '0.00',
  latestRunId: null,
}

function pct(value) {
  return `${(parseFloat(value) * 100).toFixed(0)}%`
}

function signed(value, decimals = 2) {
  const v = parseFloat(value)
  if (Number.isNaN(v)) return '0.00'
  return `${v >= 0 ? '+' : ''}${v.toFixed(decimals)}`
}

function statusVariant(status) {
  if (status === 'completed') return 'default'
  if (status === 'failed') return 'danger'
  if (status === 'cancelled') return 'warning'
  if (status === 'running') return 'info'
  return 'secondary'
}

function RecentRunsPanel({ runs }) {
  const navigate = useNavigate()
  return (
    <div className="divide-y divide-slate-700/30">
      {runs.length === 0 ? (
        <div className="px-4 py-6 text-center text-slate-400 text-xs">No simulation history found.</div>
      ) : (
        runs.map((run) => {
          const pnl = run.metrics ? formatPnl(run.metrics.netProfit) : null
          return (
            <div
              key={run.jobId}
              className="flex items-center justify-between px-4 py-2 hover:bg-slate-800/20 group"
            >
              <div className="min-w-0 flex-1 pr-3">
                <div className="flex items-center gap-2">
                  <span className="text-gray-200 font-semibold text-xs truncate">
                    {run.strategyName}
                  </span>
                  <Badge variant={statusVariant(run.status)}>{run.status}</Badge>
                </div>
                <div className="text-[10px] text-slate-500 font-mono mt-0.5 truncate">
                  {run.symbol} · {run.timeframe}
                </div>
              </div>
              <div className="text-right">
                {pnl ? (
                  <div className={`text-xs font-mono font-semibold ${pnl.isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                    {pnl.value}
                  </div>
                ) : (
                  <div className="text-slate-500 text-xs">—</div>
                )}
              </div>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => navigate(`/backtest?jobId=${run.jobId}`)}
                className="h-7 w-7 p-0 ml-2"
              >
                <ChevronRight className="size-4 text-slate-500 group-hover:text-emerald-400" />
              </Button>
            </div>
          )
        })
      )}
    </div>
  )
}

export default function Dashboard() {
  const [timeframe, setTimeframe] = useState('all')

  const { data: statsData, isLoading: loadingStats, isError: errorStats } = useDashboardStats()
  const { data: candlesData, isLoading: loadingCandles, isError: errorCandles } = useCachedCandles()
  const { data: calendarData, isLoading: loadingCalendar } = useDashboardCalendar()
  const { data: listData } = useBacktestsList(1, 5)

  const stats = statsData?.stats ?? DEFAULT_STATS
  const leaderboard = statsData?.leaderboard ?? []
  const cachedCandles = candlesData?.cached ?? []
  const calendarDays = calendarData?.days ?? []
  const recentRuns = listData?.backtests ?? []

  // Fetch the equity curve of the most-recently-completed run for the sparklines.
  const { data: latestRunData } = useBacktestResult(stats.latestRunId || undefined)
  const equityCurve = latestRunData?.equityCurve ?? []

  const isLoading = loadingStats || loadingCandles
  const isError = errorStats || errorCandles

  return (
    <PageWrapper>
      <PageHeader
        title="Dashboard"
        actions={
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">
              Calendar Window
            </span>
            <Select
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value)}
              className="h-8 w-36 text-xs"
            >
              <option value="30d">Last 30 days</option>
              <option value="90d">Last 90 days</option>
              <option value="all">All Time</option>
            </Select>
          </div>
        }
      />

      {isLoading ? (
        <div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-0">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-28 bg-slate-800/50" />
            ))}
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-0">
            <Skeleton className="h-32 bg-slate-800/50" />
            <Skeleton className="h-32 bg-slate-800/50" />
            <Skeleton className="h-32 bg-slate-800/50" />
          </div>
          <Skeleton className="h-64 bg-slate-800/50" />
        </div>
      ) : isError ? (
        <p className="text-red-400 text-sm p-6">
          Failed to load dashboard data. Ensure the backend is running.
        </p>
      ) : (
        <div>
          {/* ── 8 KPI cards (4-col grid, 2 rows) ─────────────────────────── */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-0">
            <StatCard
              title="Total Runs"
              value={stats.totalRuns}
              subtext="Completed backtests"
              icon={Play}
            />
            <StatCard
              title="Best Strategy"
              value={stats.bestStrategy}
              subtext="Highest avg net profit"
              icon={TrendingUp}
            />
            <StatCard
              title="Avg Win Rate"
              value={pct(stats.averageWinRate)}
              subtext="Across completed runs"
              icon={Percent}
            />
            <StatCard
              title="Profit Factor"
              value={parseFloat(stats.avgProfitFactor).toFixed(2)}
              subtext="Gross profit / loss"
              icon={Activity}
            />
            <StatCard
              title="Avg Sharpe"
              value={parseFloat(stats.avgSharpe).toFixed(2)}
              subtext="Risk-adjusted return"
              icon={Layers}
            />
            <StatCard
              title="Avg Sortino"
              value={parseFloat(stats.avgSortino).toFixed(2)}
              subtext="Downside-only return"
              icon={GitBranch}
            />
            <StatCard
              title="Max Drawdown"
              value={`${parseFloat(stats.worstDrawdown).toFixed(2)}%`}
              subtext="Worst peak-to-trough"
              icon={TrendingDown}
            />
            <StatCard
              title="Expectancy"
              value={signed(stats.avgExpectancy)}
              subtext="Avg P&L per trade"
              icon={Target}
            />
          </div>

          {/* ── Sparkline row (3-col) ────────────────────────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-0 border-t border-slate-700/50">
            <div className="bg-title-bg border-r border-slate-700/50">
              <div className="h-11 title-fade flex items-center px-4 border-b border-slate-700/30">
                <h3 className="text-gray-200 font-semibold text-sm">Latest Equity</h3>
              </div>
              <div className="p-4">
                {stats.latestRunId ? (
                  <>
                    <EquitySparkline data={equityCurve} />
                    <p className="text-[10px] text-slate-500 mt-2 uppercase tracking-wider font-bold">
                      Most recent completed run
                    </p>
                  </>
                ) : (
                  <div className="h-[90px] flex items-center justify-center border border-slate-700/50 text-slate-500 text-xs">
                    Run a backtest to see the equity curve.
                  </div>
                )}
              </div>
            </div>

            <div className="bg-title-bg border-r border-slate-700/50">
              <div className="h-11 title-fade flex items-center px-4 border-b border-slate-700/30">
                <h3 className="text-gray-200 font-semibold text-sm">Latest Drawdown</h3>
              </div>
              <div className="p-4">
                {stats.latestRunId ? (
                  <DrawdownSparkline data={equityCurve} />
                ) : (
                  <div className="h-[90px] flex items-center justify-center border border-slate-700/50 text-slate-500 text-xs">
                    No drawdown history.
                  </div>
                )}
              </div>
            </div>

            <div className="bg-title-bg">
              <div className="h-11 title-fade flex items-center px-4 border-b border-slate-700/30">
                <h3 className="text-gray-200 font-semibold text-sm">Recent Activity</h3>
              </div>
              <div className="max-h-[200px] overflow-y-auto">
                <RecentRunsPanel runs={recentRuns} />
              </div>
            </div>
          </div>

          {/* ── Performance Calendar (full width) ─────────────────────── */}
          <div className="border-t border-slate-700/50">
            {loadingCalendar ? (
              <Skeleton className="h-64 bg-slate-800/50" />
            ) : (
              <DashboardCalendar days={calendarDays} timeframe={timeframe} />
            )}
          </div>

          {/* ── Strategy Leaderboard (full width) ──────────────────────── */}
          <div className="border-t border-slate-700/50">
            <StrategyLeaderboard data={leaderboard} />
          </div>

          {/* ── Cached Candles (full width) ───────────────────────────── */}
          <div className="border-t border-slate-700/50">
            <CachedCandlesTable data={cachedCandles} />
          </div>
        </div>
      )}
    </PageWrapper>
  )
}
