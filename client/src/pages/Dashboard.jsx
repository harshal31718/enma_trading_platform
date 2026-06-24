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
import { Skeleton } from '../components/ui/skeleton'
import { Button } from '../components/ui/button'
import { Badge } from '../components/ui/badge'
import StatCard from '../features/dashboard/StatCard'
import CachedCandlesTable from '../features/dashboard/CachedCandlesTable'
import StrategyLeaderboard from '../features/dashboard/StrategyLeaderboard'
import { useNavigate } from 'react-router-dom'
import { formatPnl } from '../utils/formatters'

import { useDashboardStats, useCachedCandles } from '../hooks/useDashboard'
import { useBacktestsList } from '../hooks/useBacktest'
import { useAlgoSessions } from '../hooks/useAlgoSessions'

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

function RecentLiveRunsPanel({ sessions }) {
  const navigate = useNavigate()
  return (
    <div className="divide-y divide-slate-700/30">
      {sessions.length === 0 ? (
        <div className="px-4 py-6 text-center text-slate-400 text-xs">No live session history found.</div>
      ) : (
        sessions.map((session) => {
          const pnlVal = parseFloat(session.pnl || '0')
          const pnl = formatPnl(pnlVal)
          return (
            <div
              key={session._id}
              className="flex items-center justify-between px-4 py-2 hover:bg-slate-800/20 group"
            >
              <div className="min-w-0 flex-1 pr-3">
                <div className="flex items-center gap-2">
                  <span className="text-gray-200 font-semibold text-xs truncate">
                    {session.strategyName}
                  </span>
                  <Badge variant={statusVariant(session.status)}>{session.status}</Badge>
                </div>
                <div className="text-[10px] text-slate-500 font-mono mt-0.5 truncate">
                  {session.symbols.join(', ')} · {session.timeframe}
                </div>
              </div>
              <div className="text-right">
                <div className={`text-xs font-mono font-semibold ${pnl.isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                  {pnl.value}
                </div>
              </div>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => navigate('/algo')}
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
  const { data: statsData, isLoading: loadingStats, isError: errorStats } = useDashboardStats()
  const { data: candlesData, isLoading: loadingCandles, isError: errorCandles } = useCachedCandles()
  const { data: listData, isLoading: loadingBacktests } = useBacktestsList(1, 5)
  const { data: algoSessions = [], isLoading: loadingSessions, isError: errorSessions } = useAlgoSessions()

  const stats = statsData?.stats ?? DEFAULT_STATS
  const leaderboard = statsData?.leaderboard ?? []
  const cachedCandles = candlesData?.cached ?? []
  const recentRuns = listData?.backtests ?? []
  const recentLiveRuns = algoSessions.slice(0, 5)

  const isLoading = loadingStats || loadingCandles || loadingBacktests || loadingSessions
  const isError = errorStats || errorCandles || errorSessions

  return (
    <PageWrapper>
      <PageHeader title="Dashboard" />

      {isLoading ? (
        <div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-0">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-28 bg-slate-800/50" />
            ))}
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-0">
            <Skeleton className="h-48 bg-slate-800/50" />
            <Skeleton className="h-48 bg-slate-800/50" />
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

          {/* ── Split Row: Recent Backtests & Recent Live Runs (2-col) ──────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-0 border-t border-slate-700/50">
            <div className="bg-title-bg border-r border-slate-700/50">
              <div className="h-11 title-fade flex items-center px-4 border-b border-slate-700/30">
                <h3 className="text-gray-200 font-semibold text-sm">Recent Backtests</h3>
              </div>
              <div className="max-h-[220px] overflow-y-auto [&::-webkit-scrollbar]:hidden [scrollbar-width:none]">
                <RecentRunsPanel runs={recentRuns} />
              </div>
            </div>

            <div className="bg-title-bg">
              <div className="h-11 title-fade flex items-center px-4 border-b border-slate-700/30">
                <h3 className="text-gray-200 font-semibold text-sm">Recent Live Runs</h3>
              </div>
              <div className="max-h-[220px] overflow-y-auto [&::-webkit-scrollbar]:hidden [scrollbar-width:none]">
                <RecentLiveRunsPanel sessions={recentLiveRuns} />
              </div>
            </div>
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
