import { useState } from 'react'
import { ChevronRight } from 'lucide-react'

import PageWrapper from '../components/layout/PageWrapper'
import PageHeader from '../components/ui/PageHeader'
import { Skeleton } from '../components/ui/skeleton'
import { Button } from '../components/ui/button'
import { Badge } from '../components/ui/badge'
import CachedCandlesTable from '../features/dashboard/CachedCandlesTable'
import StrategyLeaderboard from '../features/dashboard/StrategyLeaderboard'
import TickerStrip from '../features/dashboard/TickerStrip'
import AccountOverview from '../features/dashboard/AccountOverview'
import BacktestKpiStrip from '../features/dashboard/BacktestKpiStrip'
import CollapsibleSection from '../features/dashboard/CollapsibleSection'
import DashboardCalendar from '../features/dashboard/DashboardCalendar'
import EquitySparkline from '../components/charts/EquitySparkline'
import DrawdownSparkline from '../components/charts/DrawdownSparkline'
import { useNavigate } from 'react-router-dom'
import { formatPnl } from '../utils/formatters'

import { useDashboardStats, useCachedCandles, useDashboardCalendar } from '../hooks/useDashboard'
import { useBacktestsList, useBacktestResult } from '../hooks/useBacktest'
import { useAlgoSessions } from '../hooks/useAlgoSessions'
import { useAccountBalances, useTradePositions } from '../hooks/useTrade'

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
        <div className="m-4 border border-dashed border-slate-700/30 py-6 px-4 text-center text-slate-400 text-xs">
          No simulation history found.
        </div>
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
                <div className="text-[10px] text-slate-400 font-mono mt-0.5 truncate">
                  {run.symbol} · {run.timeframe}
                </div>
              </div>
              <div className="text-right">
                {pnl ? (
                  <div className={`text-xs font-mono font-semibold ${pnl.isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                    {pnl.value}
                  </div>
                ) : (
                  <div className="text-slate-400 text-xs">—</div>
                )}
              </div>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => navigate(`/backtest?jobId=${run.jobId}`)}
                className="h-7 w-7 p-0 ml-2"
              >
                <ChevronRight className="size-4 text-slate-400 group-hover:text-emerald-400" />
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
        <div className="m-4 border border-dashed border-slate-700/30 py-6 px-4 text-center text-slate-400 text-xs">
          No live session history found.
        </div>
      ) : (
        sessions.map((session) => {
          const pnlVal = parseFloat(session.pnl || '0')
          const pnl = formatPnl(pnlVal)
          return (
            <div
              key={session._id}
              className="flex items-center justify-between px-4 py-2 hover:bg-slate-800/20 group"
            >
              <div className="min-w-0 flex-1 flex items-center gap-2 pr-3">
                <span className="text-gray-200 font-semibold text-xs shrink-0">
                  {session.strategyName}
                </span>
                <Badge variant={statusVariant(session.status)} className="shrink-0">{session.status}</Badge>
                <span className="text-[10px] text-slate-400 font-mono truncate flex-1 min-w-0">
                  {session.symbols.join(', ')} · {session.timeframe}
                </span>
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
                <ChevronRight className="size-4 text-slate-400 group-hover:text-emerald-400" />
              </Button>
            </div>
          )
        })
      )}
    </div>
  )
}

function PanelSection({ title, loading, children }) {
  return (
    <>
      <div className="h-11 title-fade flex items-center px-4 border-b border-slate-700/30">
        <h3 className="text-gray-200 font-semibold text-sm">{title}</h3>
      </div>
      {loading ? (
        <div className="p-4 space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-10 bg-slate-800/50" />
          ))}
        </div>
      ) : (
        children
      )}
    </>
  )
}

const CALENDAR_TIMEFRAMES = [
  { value: '30d', label: '30D' },
  { value: '90d', label: '90D' },
  { value: 'all', label: 'All' },
]

export default function Dashboard() {
  const { data: statsData, isLoading: loadingStats } = useDashboardStats()
  const { data: candlesData, isLoading: loadingCandles } = useCachedCandles()
  const { data: listData, isLoading: loadingBacktests } = useBacktestsList(1, 5)
  const { data: algoSessions = [], isLoading: loadingSessions } = useAlgoSessions()
  const { data: calendarData, isLoading: loadingCalendar } = useDashboardCalendar()
  const [calendarTimeframe, setCalendarTimeframe] = useState('90d')

  // Live account data — failures here must not blank the backtest sections.
  const { data: balances } = useAccountBalances()
  const { data: positions } = useTradePositions()

  const stats = statsData?.stats ?? DEFAULT_STATS
  const leaderboard = statsData?.leaderboard ?? []
  const cachedCandles = candlesData?.cached ?? []
  const recentRuns = listData?.backtests ?? []
  const calendarDays = calendarData?.days ?? []

  // Equity/drawdown sparklines mirror the most recently completed backtest
  // (Dashboard is a cross-strategy overview, not tied to one run — the
  // latest completed run is the only well-defined "current" equity curve).
  const { data: latestRun, isLoading: loadingLatestRun } = useBacktestResult(stats.latestRunId)
  const latestRunEquityCurve = latestRun?.equityCurve ?? []

  // "Live Runs" = currently active sessions (auto-hides when none are running).
  // "Recent Live Runs" = finished sessions (stopped/error), mirroring "Recent Backtests".
  const liveRuns = algoSessions.filter((s) => ['starting', 'running', 'stopping'].includes(s.status))
  const recentLiveRuns = algoSessions
    .filter((s) => !['starting', 'running', 'stopping'].includes(s.status))
    .slice(0, 5)

  const openPositions = Array.isArray(positions) ? positions : []
  const positionSymbols = openPositions
    .filter((p) => parseFloat(p.positionAmt) !== 0)
    .map((p) => p.symbol)

  return (
    <PageWrapper>
      <PageHeader title="Dashboard">
        {/* ── Live price strip ─────────────────────────────────────────── */}
        <TickerStrip positionSymbols={positionSymbols} />
      </PageHeader>

      {/* ── Account overview (testnet + mainnet balances) ────────────── */}
      <AccountOverview balances={balances} positions={openPositions} />

      {/* ── Condensed backtest KPIs ──────────────────────────────────── */}
      {loadingStats ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-8 gap-0 border-t border-slate-700/50">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-[58px] bg-slate-800/50" />
          ))}
        </div>
      ) : (
        <BacktestKpiStrip stats={stats} />
      )}

      {/* ── Latest Run — Equity / Drawdown sparklines ───────────────────── */}
      {stats.latestRunId && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-0 border-t border-slate-700/50">
          <div className="bg-title-bg border-b lg:border-b-0 lg:border-r border-slate-700/50">
            <PanelSection title="Latest Run — Equity Curve" loading={loadingLatestRun}>
              <div className="p-3">
                <EquitySparkline data={latestRunEquityCurve} />
              </div>
            </PanelSection>
          </div>
          <div className="bg-title-bg">
            <PanelSection title="Latest Run — Drawdown" loading={loadingLatestRun}>
              <div className="p-3">
                <DrawdownSparkline data={latestRunEquityCurve} />
              </div>
            </PanelSection>
          </div>
        </div>
      )}

      {/* ── Performance Calendar ─────────────────────────────────────────── */}
      <div className="border-t border-slate-700/50">
        {loadingCalendar ? (
          <div className="bg-title-bg border border-slate-700/50 p-4">
            <Skeleton className="h-[200px] bg-slate-800/50" />
          </div>
        ) : (
          <DashboardCalendar
            days={calendarDays}
            timeframe={calendarTimeframe}
            headerActions={
              <div className="flex items-center gap-1">
                {CALENDAR_TIMEFRAMES.map(({ value, label }) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setCalendarTimeframe(value)}
                    className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border transition-colors ${
                      calendarTimeframe === value
                        ? 'bg-emerald-400/10 text-emerald-400 border-emerald-500/20'
                        : 'bg-slate-500/10 text-slate-400 border-slate-500/20 hover:text-slate-200'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            }
          />
        )}
      </div>

      {/* ── Live Runs, Recent Live Runs & Recent Backtests ──────────────── */}
      <div className={`grid grid-cols-1 ${ (loadingSessions || liveRuns.length > 0) ? 'lg:grid-cols-3' : 'lg:grid-cols-2' } gap-0 border-t border-slate-700/50`}>
        {(loadingSessions || liveRuns.length > 0) && (
          <div className="bg-title-bg border-b lg:border-b-0 lg:border-r border-slate-700/50">
            <PanelSection title="Live Runs" loading={loadingSessions}>
              <RecentLiveRunsPanel sessions={liveRuns} />
            </PanelSection>
          </div>
        )}
        <div className="bg-title-bg border-b lg:border-b-0 lg:border-r border-slate-700/50">
          <PanelSection title="Recent Live Runs" loading={loadingSessions}>
            <RecentLiveRunsPanel sessions={recentLiveRuns} />
          </PanelSection>
        </div>
        <div className="bg-title-bg">
          <PanelSection title="Recent Backtests" loading={loadingBacktests}>
            <RecentRunsPanel runs={recentRuns} />
          </PanelSection>
        </div>
      </div>

      {/* ── Strategy Leaderboard ─────────────────────────────────────── */}
      <div className="bg-title-bg border-t border-slate-700/50">
        <PanelSection title="Strategy Leaderboard" loading={loadingStats}>
          <StrategyLeaderboard data={leaderboard} />
        </PanelSection>
      </div>

      {/* ── TimescaleDB Cache (demoted, collapsible) ─────────────────── */}
      <CollapsibleSection
        title="TimescaleDB Cache"
        meta={loadingCandles ? null : `${cachedCandles.length} dataset${cachedCandles.length === 1 ? '' : 's'}`}
      >
        <CachedCandlesTable data={cachedCandles} />
      </CollapsibleSection>
    </PageWrapper>
  )
}
