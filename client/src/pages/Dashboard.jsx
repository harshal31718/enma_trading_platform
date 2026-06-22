import { Play, TrendingUp, Percent, Database } from 'lucide-react'

import PageWrapper from '../components/layout/PageWrapper'
import PageHeader from '../components/ui/PageHeader'
import { Skeleton } from '../components/ui/skeleton'
import StatCard from '../features/dashboard/StatCard'
import CachedCandlesTable from '../features/dashboard/CachedCandlesTable'
import RecentActivityTable from '../features/dashboard/RecentActivityTable'
import StrategyLeaderboard from '../features/dashboard/StrategyLeaderboard'

import { useDashboardStats, useCachedCandles } from '../hooks/useDashboard'
import { useBacktestsList } from '../hooks/useBacktest'

export default function Dashboard() {
  const { data: statsData, isLoading: loadingStats, isError: errorStats } = useDashboardStats()
  const { data: candlesData, isLoading: loadingCandles, isError: errorCandles } = useCachedCandles()
  const { data: listData } = useBacktestsList(1, 5)

  const stats = statsData?.stats ?? { totalRuns: 0, bestStrategy: 'N/A', averageWinRate: '0.00' }
  const leaderboard = statsData?.leaderboard ?? []
  const cachedCandles = candlesData?.cached ?? []
  const recentRuns = listData?.backtests ?? []

  const formattedWinRate = `${(parseFloat(stats.averageWinRate) * 100).toFixed(0)}%`

  const isLoading = loadingStats || loadingCandles
  const isError = errorStats || errorCandles

  return (
    <PageWrapper>
      <PageHeader title="Dashboard" />

      {isLoading ? (
        <div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-0">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-28 bg-slate-800/50" />
            ))}
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-0">
            <Skeleton className="h-80 bg-slate-800/50" />
            <Skeleton className="h-80 bg-slate-800/50" />
          </div>
          <Skeleton className="h-64 bg-slate-800/50" />
        </div>
      ) : isError ? (
        <p className="text-red-400 text-sm">Failed to load dashboard data. Ensure the backend is running.</p>
      ) : (
        <div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-0">
            <StatCard
              title="Total Runs"
              value={stats.totalRuns}
              subtext="Completed & failed backtests"
              icon={Play}
            />
            <StatCard
              title="Best Strategy"
              value={stats.bestStrategy}
              subtext="Highest average net profit"
              icon={TrendingUp}
            />
            <StatCard
              title="Avg Win Rate"
              value={formattedWinRate}
              subtext="Average across completed runs"
              icon={Percent}
            />
            <StatCard
              title="Local DB Cache"
              value={`${cachedCandles.length} markets`}
              subtext="Cached candle streams"
              icon={Database}
            />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-0">
            <RecentActivityTable data={recentRuns} />
            <StrategyLeaderboard data={leaderboard} />
          </div>

          <div>
            <CachedCandlesTable data={cachedCandles} />
          </div>
        </div>
      )}
    </PageWrapper>
  )
}
