import { useState, useEffect, lazy, Suspense } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  TrendingUp,
  Percent,
  AlertTriangle,
  DollarSign,
  Activity,
  Calendar,
  Loader2,
  ChevronRight,
  ChevronLeft,
  Download,
  Plus,
  Square,
} from 'lucide-react'

import PageWrapper from '../components/layout/PageWrapper'
import PageHeader from '../components/ui/PageHeader'
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/card'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../components/ui/table'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Dialog, DialogContent } from '../components/ui/dialog'
const EquityCurve = lazy(() => import('../components/charts/EquityCurve'))
import NewBacktestWizard from '../features/backtest/NewBacktestWizard'
import BacktestHistory from '../features/backtest/BacktestHistory'
import BacktestMetricCard from '../features/backtest/BacktestMetricCard'
import BacktestCalendar from '../features/backtest/BacktestCalendar'

import {
  useRunBacktest,
  useBacktestsList,
  useBacktestResult,
  useCancelBacktest,
  useBacktestTrades,
  useAllBacktestTrades,
  useBacktestBenchmark,
} from '../hooks/useBacktest'
import api from '../lib/axios'
import { formatQty, formatPrice, formatPct, formatSignedPct, formatPnl, formatIsoDate } from '../utils/formatters'
import { exportResultAsJSON } from '../utils/exporters'
import socket from '../lib/socket'
import { useQueryClient, useQueries } from '@tanstack/react-query'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../components/ui/tabs'

function PerformanceTable({ bySide }) {
  if (!bySide) return null;

  const rows = [
    { label: 'Net Profit', key: 'netProfit', format: (val, r) => `${formatPnl(val).value} (${formatSignedPct(r.netProfitPct)})`, isPnl: true },
    { label: 'Gross Profit', key: 'grossProfit', format: (val) => formatPnl(val).value, isPnl: true },
    { label: 'Gross Loss', key: 'grossLoss', format: (val) => formatPnl(val).value, isPnl: true },
    { label: 'Profit Factor', key: 'profitFactor', format: (val) => parseFloat(val).toFixed(2), highlightPF: true },
    { label: 'Total Trades', key: 'totalTrades', format: (val) => val },
    { label: 'Winning Trades', key: 'winningTrades', format: (val) => val },
    { label: 'Losing Trades', key: 'losingTrades', format: (val) => val },
    { label: 'Win Rate (% Profitable)', key: 'winRate', format: (val) => formatPct(parseFloat(val) * 100) },
    { label: 'Expectancy (Avg P&L)', key: 'expectancy', format: (val) => formatPnl(val).value, isPnl: true },
    { label: 'Avg Win', key: 'averageWin', format: (val) => formatPnl(val).value, isPnl: true },
    { label: 'Avg Loss', key: 'averageLoss', format: (val) => formatPnl(val).value, isPnl: true },
    { label: 'Payoff Ratio (Win/Loss)', key: 'payoffRatio', format: (val) => parseFloat(val).toFixed(2) },
    {
      label: 'Avg Holding Period', key: 'averageHoldingPeriod', format: (val) => {
        const secs = parseInt(val)
        if (secs >= 3600) return `${(secs / 3600).toFixed(1)}h`
        if (secs >= 60) return `${(secs / 60).toFixed(1)}m`
        return `${secs}s`
      }
    },
    { label: 'Max Consecutive Wins', key: 'maxConsecutiveWins', format: (val) => val },
    { label: 'Max Consecutive Losses', key: 'maxConsecutiveLosses', format: (val) => val },
  ]

  const getPnlClass = (val) => {
    const n = parseFloat(val)
    if (n > 0) return 'text-emerald-400 font-semibold'
    if (n < 0) return 'text-red-400 font-semibold'
    return 'text-gray-300'
  }

  const getPFClass = (val) => {
    const n = parseFloat(val)
    if (n >= 1) return 'text-emerald-400 font-semibold'
    if (n > 0) return 'text-red-400 font-semibold'
    return 'text-gray-300'
  }

  return (
    <div className="bg-title-bg border border-slate-700/50 overflow-hidden">
      <Table>
        <TableHeader className="bg-title-bg title-fade">
          <TableRow className="border-b border-slate-700/50 hover:bg-transparent">
            <TableHead className="w-[250px]">Metric</TableHead>
            <TableHead>All Trades</TableHead>
            <TableHead>Long Trades</TableHead>
            <TableHead>Short Trades</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => {
            const allVal = bySide.all?.[row.key] ?? '-'
            const longVal = bySide.long?.[row.key] ?? '-'
            const shortVal = bySide.short?.[row.key] ?? '-'

            return (
              <TableRow key={row.key}>
                <TableCell className="font-medium text-gray-300">{row.label}</TableCell>
                <TableCell className={row.isPnl ? getPnlClass(allVal) : row.highlightPF ? getPFClass(allVal) : 'text-gray-400 font-mono text-sm'}>
                  {allVal !== '-' ? row.format(allVal, bySide.all) : '-'}
                </TableCell>
                <TableCell className={row.isPnl ? getPnlClass(longVal) : row.highlightPF ? getPFClass(longVal) : 'text-gray-400 font-mono text-sm'}>
                  {longVal !== '-' ? row.format(longVal, bySide.long) : '-'}
                </TableCell>
                <TableCell className={row.isPnl ? getPnlClass(shortVal) : row.highlightPF ? getPFClass(shortVal) : 'text-gray-400 font-mono text-sm'}>
                  {shortVal !== '-' ? row.format(shortVal, bySide.short) : '-'}
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}



function ComparisonTable({ results }) {
  const metricRows = [
    { label: 'Net Profit', getValue: (r) => formatPrice(r.metrics?.netProfit ?? 0), isPnl: true },
    { label: 'Net Profit %', getValue: (r) => formatSignedPct(r.metrics?.netProfitPct ?? 0), isPnl: true },
    { label: 'Win Rate', getValue: (r) => formatPct((parseFloat(r.metrics?.winRate || 0) || 0) * 100) },
    { label: 'Profit Factor', getValue: (r) => (r.metrics?.profitFactor ? parseFloat(r.metrics.profitFactor).toFixed(2) : '-'), isPF: true },
    { label: 'Max Drawdown', getValue: (r) => formatPct(parseFloat(r.metrics?.maxDrawdown || 0)), isLoss: true },
    { label: 'Sharpe', getValue: (r) => parseFloat(r.metrics?.sharpeRatio || 0).toFixed(2) },
    { label: 'Sortino', getValue: (r) => parseFloat(r.metrics?.sortinoRatio || 0).toFixed(2) },
    { label: 'Calmar', getValue: (r) => parseFloat(r.metrics?.calmarRatio || 0).toFixed(2) },
    { label: 'Total Trades', getValue: (r) => r.metrics?.totalTrades ?? '-' },
    { label: 'Win / Loss', getValue: (r) => `${r.metrics?.winningTrades ?? '-'} / ${r.metrics?.losingTrades ?? '-'}` },
    { label: 'Expectancy', getValue: (r) => (r.metrics?.expectancy != null ? formatPnl(r.metrics.expectancy).value : '-'), isPnl: true },
    { label: 'Capital', getValue: (r) => formatPrice(r.capital) },
    { label: 'Leverage', getValue: (r) => `${r.leverage}x` },
    { label: 'Fee Rate', getValue: (r) => `${((r.feeRate || 0) * 100).toFixed(2)}%` },
    { label: 'Date Range', getValue: (r) => `${formatIsoDate(r.startDate)} → ${formatIsoDate(r.endDate)}` },
  ]

  const getValClass = (row, r) => {
    const raw = row.getValue(r)
    const n = parseFloat(raw)
    if (row.isPnl) return n > 0 ? 'text-emerald-400' : n < 0 ? 'text-red-400' : 'text-gray-300'
    if (row.isLoss) return 'text-red-400'
    if (row.isPF) return n >= 1 ? 'text-emerald-400' : 'text-red-400'
    return 'text-gray-300'
  }

  return (
    <div className="space-y-4">
      {/* Header cards */}
      <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${results.length}, minmax(0, 1fr))` }}>
        {results.map((r) => (
          <div key={r.jobId} className="rounded-lg border border-gray-800 bg-gray-900/60 p-3">
            <div className="text-sm font-semibold text-gray-100 truncate">{r.strategyName}</div>
            <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
              <span className="text-[10px] font-mono text-gray-400 bg-gray-800 px-1.5 py-0.5 rounded">{r.symbol}</span>
              <span className="text-[10px] font-mono text-gray-500 bg-gray-800/60 px-1.5 py-0.5 rounded">{r.timeframe}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Metric table */}
      <div className="rounded-lg border border-gray-800 overflow-hidden">
        <Table>
          <TableHeader className="bg-title-bg title-fade">
            <TableRow className="border-b border-slate-700/50 hover:bg-transparent">
              <TableHead className="w-[180px] text-gray-400 font-medium text-xs">Metric</TableHead>
              {results.map((r) => (
                <TableHead key={r.jobId} className="text-gray-200 font-semibold text-xs">
                  <div className="truncate max-w-[140px]">{r.strategyName}</div>
                  <div className="text-[10px] text-gray-500 font-normal">{r.symbol} · {r.timeframe}</div>
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {metricRows.map((row, idx) => (
              <TableRow key={row.label} className={idx % 2 === 0 ? 'bg-gray-900/40 border-b border-gray-800/60' : 'bg-transparent border-b border-gray-800/60'}>
                <TableCell className="text-gray-400 text-xs font-medium">{row.label}</TableCell>
                {results.map((r) => (
                  <TableCell key={`${r.jobId}-${row.label}`} className={`font-mono text-xs font-semibold ${getValClass(row, r)}`}>
                    {row.getValue(r)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

export default function Backtest() {
  const queryClient = useQueryClient()
  const [historyFilters, setHistoryFilters] = useState({
    strategyName: '',
    symbol: '',
    timeframe: '',
    status: '',
    createdAfter: '',
    createdBefore: '',
  })

  const [comparisonIds, setComparisonIds] = useState([])
  const [compareError, setCompareError] = useState('')
  const [showWizard, setShowWizard] = useState(false)

  const { data: listData, isLoading: loadingHistory, refetch: refetchHistory } = useBacktestsList(1, 20, historyFilters)

  const [activeJobId, setActiveJobId] = useState(null)
  const [progressPct, setProgressPct] = useState(0)
  const [progressMessage, setProgressMessage] = useState('')
  const [selectedResultId, setSelectedResultId] = useState(null)
  const [errorMessage, setErrorMessage] = useState('')
  const [tradePage, setTradePage] = useState(1)
  const TRADES_PER_PAGE = 20

  const [searchParams] = useSearchParams()
  const jobIdParam = searchParams.get('jobId')

  const runMutation = useRunBacktest()
  const cancelMutation = useCancelBacktest()

  const { data: activeResult, isLoading: loadingResult } = useBacktestResult(
    selectedResultId || null
  )

  const { data: tradesData, isLoading: loadingTrades } = useBacktestTrades(
    selectedResultId || null,
    tradePage,
    TRADES_PER_PAGE
  )

  const { data: allTradesData, isLoading: loadingAllTrades } = useAllBacktestTrades(
    selectedResultId || null
  )

  const { data: benchmarkData } = useBacktestBenchmark(
    selectedResultId || null
  )

  const comparisonQueries = useQueries({
    queries: comparisonIds.map((id) => ({
      queryKey: ['backtests', id],
      queryFn: async () => {
        const res = await api.get(`/api/v1/backtest/${id}`)
        return res.data.data
      },
      enabled: !!id,
      staleTime: Infinity,
    })),
  })

  const comparisonResults = comparisonQueries.map((q) => q.data).filter(Boolean)
  const comparisonLoading = comparisonQueries.some((q) => q.isLoading)

  // Auto-select deep-linked jobId or first completed run
  useEffect(() => {
    if (jobIdParam) {
      setSelectedResultId(jobIdParam)
    } else if (!selectedResultId && !activeJobId && listData?.backtests?.length > 0) {
      const firstCompleted = listData.backtests.find((b) => b.status === 'completed')
      if (firstCompleted) setSelectedResultId(firstCompleted.jobId)
    }
  }, [listData, selectedResultId, activeJobId, jobIdParam])

  // Socket.IO progress streaming
  useEffect(() => {
    if (!activeJobId) return

    // Room join already happened in handleRun before the POST fired.
    // This effect only registers/deregisters the event listeners.

    const handleProgress = (data) => {
      if (data.jobId === activeJobId) {
        setProgressPct(data.pct || 0)
        setProgressMessage(data.message || '')
      }
    }

    const handleComplete = (data) => {
      if (data.jobId === activeJobId) {
        setActiveJobId(null)
        setProgressPct(0)
        setProgressMessage('')
        setSelectedResultId(data.resultId)
        setTradePage(1)
        // Invalidate both the list and the individual result so they refetch
        queryClient.invalidateQueries({ queryKey: ['backtests'] })
        queryClient.invalidateQueries({ queryKey: ['backtests', data.resultId] })
      }
    }

    const handleError = (data) => {
      if (data.jobId === activeJobId) {
        setActiveJobId(null)
        setProgressPct(0)
        setProgressMessage('')
        setErrorMessage(`Simulation failed: ${data.error}`)
        refetchHistory()
      }
    }

    socket.on('backtest:progress', handleProgress)
    socket.on('backtest:complete', handleComplete)
    socket.on('backtest:error', handleError)

    return () => {
      socket.off('backtest:progress', handleProgress)
      socket.off('backtest:complete', handleComplete)
      socket.off('backtest:error', handleError)
    }
  }, [activeJobId, refetchHistory])

  const handleRun = async (config) => {
    setErrorMessage('')

    // Generate jobId here so we can join the socket room *before* the POST lands.
    // This closes the race where a fast backtest completes and emits backtest:complete
    // before the client has joined the room and set up its listeners.
    const jobId = crypto.randomUUID()

    socket.connect()
    socket.emit('join', `backtest:${jobId}`)

    setActiveJobId(jobId)
    setProgressPct(0)
    setProgressMessage('Queuing job...')

    try {
      await runMutation.mutateAsync({ ...config, jobId })
    } catch (err) {
      // Roll back: clear active state so the UI doesn't hang
      setActiveJobId(null)
      setProgressPct(0)
      setProgressMessage('')
      setErrorMessage(
        `Failed to start backtest: ${err.response?.data?.error?.message || err.message}`
      )
    }
  }

  const handleCancel = async () => {
    if (!activeJobId) return
    try {
      await cancelMutation.mutateAsync(activeJobId)
      setActiveJobId(null)
      setProgressPct(0)
      setProgressMessage('')
      refetchHistory()
    } catch (err) {
      setErrorMessage(`Failed to cancel: ${err.message}`)
    }
  }

  const getPnlClass = (val) => {
    const n = parseFloat(val)
    if (n > 0) return 'text-emerald-400'
    if (n < 0) return 'text-red-400'
    return 'text-gray-300'
  }

  const toggleComparison = (jobId) => {
    setComparisonIds((current) => {
      if (current.includes(jobId)) {
        setCompareError('')
        return current.filter((id) => id !== jobId)
      }
      if (current.length >= 4) {
        setCompareError('Maximum 4 runs can be compared at a time.')
        return current
      }
      setCompareError('')
      return [...current, jobId]
    })
  }

  return (
    <PageWrapper>
      <PageHeader
        title="Backtest"
        actions={
          <button
            onClick={() => setShowWizard(true)}
            disabled={!!activeJobId}
            className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm rounded-lg transition-colors"
          >
            <Plus size={16} />
            New Backtest
          </button>
        }
      />

      {errorMessage && (
        <div className="bg-red-950/20 border border-red-800/40 rounded-lg p-3 flex items-center gap-2 text-red-400 text-sm">
          <AlertTriangle className="size-4 shrink-0" />
          {errorMessage}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-0 h-[calc(100vh-100px)] overflow-hidden">
        {/* Left Column — Run History */}
        <div className="lg:col-span-1 border-r border-slate-700/50 h-full overflow-hidden">
          <BacktestHistory
            data={listData?.backtests}
            selectedId={selectedResultId}
            onSelect={(id) => { setSelectedResultId(id); setTradePage(1) }}
            onRefresh={refetchHistory}
            isLoading={loadingHistory}
            filters={historyFilters}
            onApplyFilters={(nextFilters) => setHistoryFilters(nextFilters)}
            onClearFilters={(nextFilters) => setHistoryFilters(nextFilters)}
            comparisonIds={comparisonIds}
            onToggleComparison={toggleComparison}
          />
        </div>

        {/* Right Column */}
        <div className="lg:col-span-3 h-full overflow-hidden flex flex-col">
          {activeJobId ? (
            <Card className="h-fit flex flex-col items-center justify-start py-12 px-6">
              <div className="space-y-6 text-center max-w-md w-full">
                <div className="relative flex justify-center">
                  <div className="animate-ping absolute inline-flex h-12 w-12 rounded-full bg-emerald-400 opacity-20" />
                  <Activity className="size-12 text-emerald-400 relative" />
                </div>
                <div className="space-y-2">
                  <h3 className="text-gray-100 font-semibold text-lg">Simulation Running</h3>
                  <p className="text-gray-400 text-sm leading-relaxed">
                    Executing logic in Python Engine. Progress is streamed live.
                  </p>
                </div>
                <div className="space-y-2 w-full">
                  <div className="flex justify-between text-xs font-medium">
                    <span className="text-emerald-400">{progressMessage}</span>
                    <span className="text-gray-400">{progressPct}%</span>
                  </div>
                  <div className="w-full bg-gray-950 h-2 rounded overflow-hidden border border-gray-800">
                    <div
                      className="bg-emerald-500 h-full transition-all duration-300"
                      style={{ width: `${progressPct}%` }}
                    />
                  </div>
                </div>
                <Button
                  variant="danger"
                  className="flex items-center justify-center gap-2"
                  onClick={handleCancel}
                  disabled={cancelMutation.isPending}
                >
                  <Square className="size-4" /> Cancel Backtest
                </Button>
              </div>
            </Card>
          ) : loadingResult ? (
            <Card className="h-full flex justify-center items-center py-32">
              <div className="flex flex-col items-center gap-3">
                <Loader2 className="size-8 animate-spin text-emerald-400" />
                <span className="text-gray-400 text-sm">Fetching backtest details...</span>
              </div>
            </Card>
          ) : activeResult ? (
            <Tabs defaultValue="overview" className="w-full h-full flex flex-col">
              {/* ── Tabs header bar — matches BacktestHistory header height ── */}
              <div className="h-11 shrink-0 bg-title-bg title-fade border-b border-slate-700/50 flex items-center px-2 gap-1">
                <TabsList className="h-full bg-transparent border-none gap-0 p-0">
                  <TabsTrigger value="overview">Overview</TabsTrigger>
                  <TabsTrigger value="performance">Performance Summary</TabsTrigger>
                  <TabsTrigger value="trades">List of Trades</TabsTrigger>
                  <TabsTrigger value="comparison" className="relative">
                    Compare
                    {comparisonIds.length > 0 && (
                      <span className="ml-1.5 inline-flex items-center justify-center size-4 rounded-full bg-emerald-500 text-[9px] font-bold text-white">
                        {comparisonIds.length}
                      </span>
                    )}
                  </TabsTrigger>
                </TabsList>
              </div>

              {/* ── Scrollable content area ── */}
              <div className="flex-1 overflow-y-auto">
                {activeResult.status === 'failed' && (
                  <div className="bg-red-950/20 border border-red-800/40 rounded-lg p-4 m-4 flex items-center gap-3 text-red-400 text-sm">
                    <AlertTriangle className="size-5 shrink-0" />
                    <div>
                      <span className="font-semibold">Execution Failed:</span>{' '}
                      {activeResult.error || 'Unknown error occurred.'}
                    </div>
                  </div>
                )}

                <TabsContent value="overview">
                  {activeResult.metrics && (() => {
                    const m = activeResult.metrics
                    const metrics = [
                      { label: 'Net Profit',    value: formatPrice(m.netProfit),                            cls: getPnlClass(m.netProfit) },
                      { label: 'Net P&L %',     value: formatSignedPct(m.netProfitPct),                    cls: getPnlClass(m.netProfit) },
                      { label: 'Max Drawdown',  value: formatPct(m.maxDrawdown),                           cls: 'text-red-400' },
                      { label: 'Win Rate',      value: formatPct(parseFloat(m.winRate) * 100),             cls: 'text-gray-100' },
                      { label: 'Total Trades',  value: m.totalTrades ?? '-',                               cls: 'text-gray-100' },
                      { label: 'Profit Factor', value: m.profitFactor ? parseFloat(m.profitFactor).toFixed(2) : '-', cls: m.profitFactor && parseFloat(m.profitFactor) >= 1 ? 'text-emerald-400' : 'text-red-400' },
                      { label: 'Sharpe',        value: parseFloat(m.sharpeRatio || 0).toFixed(2),          cls: 'text-gray-100' },
                      { label: 'Sortino',       value: parseFloat(m.sortinoRatio || 0).toFixed(2),         cls: 'text-gray-100' },
                      { label: 'Calmar',        value: parseFloat(m.calmarRatio || 0).toFixed(2),          cls: 'text-gray-100' },
                      { label: 'Expectancy',    value: m.expectancy ? formatPnl(m.expectancy).value : '-', cls: m.expectancy ? getPnlClass(m.expectancy) : 'text-gray-300' },
                    ]
                    return (
                      <div className="grid grid-cols-5 border-b border-slate-700/50 divide-x divide-y divide-slate-700/50">
                        {metrics.map(({ label, value, cls }) => (
                          <div key={label} className="flex flex-col justify-center px-3 h-11 bg-title-bg">
                            <span className="text-[9px] uppercase tracking-wider text-gray-500 leading-none mb-1">{label}</span>
                            <span className={`text-sm font-bold leading-none ${cls}`}>{value}</span>
                          </div>
                        ))}
                      </div>
                    )
                  })()}

                  {/* Performance Charts */}
                  <div className="border-b border-slate-700/50">
                    <div className="h-11 bg-title-bg title-fade flex items-center px-4 border-b border-slate-700/30">
                      <span className="text-sm font-semibold text-gray-100">Performance Charts</span>
                    </div>
                    <div className="p-4">
                      <Suspense fallback={<div className="h-48 flex items-center justify-center"><Loader2 className="size-6 animate-spin text-emerald-400" /></div>}>
                        <EquityCurve
                          data={activeResult.equityCurve}
                          startingCapital={activeResult.capital}
                          buyHoldReturnPct={activeResult.metrics?.buyHoldReturnPct || 0}
                          benchmark={benchmarkData ?? null}
                        />
                      </Suspense>
                    </div>
                  </div>

                  {allTradesData && allTradesData.length > 0 && (
                    <div className="border-b border-slate-700/50">
                      <BacktestCalendar
                        trades={allTradesData}
                        onSelectPeriod={(trades) => {}}
                      />
                    </div>
                  )}

                  {/* Simulation Config */}
                  <div className="border-b border-slate-700/50 px-5 py-4">
                    <h4 className="text-gray-100 font-semibold mb-3 text-sm">Simulation Config</h4>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                      <div>
                        <span className="text-gray-500 block">Date Range</span>
                        <span className="text-gray-300 font-medium flex items-center gap-1.5 mt-0.5">
                          <Calendar className="size-4 text-emerald-400" />
                          {formatIsoDate(activeResult.startDate)} to {formatIsoDate(activeResult.endDate)}
                        </span>
                      </div>
                      <div>
                        <span className="text-gray-500 block">Symbol / Exchange</span>
                        <span className="text-gray-300 font-medium block mt-0.5">
                          {activeResult.symbol} ({activeResult.exchange})
                        </span>
                      </div>
                      <div>
                        <span className="text-gray-500 block">Leverage / Fee Rate</span>
                        <span className="text-gray-300 font-medium block mt-0.5">
                          {activeResult.leverage}x / {(activeResult.feeRate * 100).toFixed(2)}%
                        </span>
                      </div>
                      <div>
                        <span className="text-gray-500 block">Total Fees Paid</span>
                        <span className="text-red-400 font-medium block mt-0.5">
                          {activeResult.metrics?.totalFees ? formatPrice(activeResult.metrics.totalFees) : '-'}
                        </span>
                      </div>
                      {activeResult.metrics?.liquidations != null && (
                        <div>
                          <span className="text-gray-500 block">Liquidations</span>
                          <span className={`font-medium block mt-0.5 ${activeResult.metrics.liquidations > 0 ? 'text-red-400' : 'text-gray-300'}`}>
                            {activeResult.metrics.liquidations}
                          </span>
                        </div>
                      )}
                      {parseFloat(activeResult.metrics?.totalFunding || 0) !== 0 && (
                        <div>
                          <span className="text-gray-500 block">Net Funding</span>
                          <span className={`font-medium block mt-0.5 ${parseFloat(activeResult.metrics.totalFunding) > 0 ? 'text-red-400' : 'text-emerald-400'}`}>
                            {parseFloat(activeResult.metrics.totalFunding) > 0 ? '-' : '+'}${Math.abs(parseFloat(activeResult.metrics.totalFunding)).toFixed(2)}
                          </span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Export Results */}
                  <div className="px-5 py-4 flex items-center justify-between">
                    <div>
                      <h4 className="text-gray-100 font-semibold text-sm">Export Results</h4>
                      <p className="text-gray-500 text-xs mt-0.5">Download backtest data for analysis</p>
                    </div>
                    <Button
                      onClick={() => exportResultAsJSON(activeResult, activeResult.strategyName || 'backtest')}
                      size="sm"
                      className="bg-emerald-600 hover:bg-emerald-700 text-white flex items-center gap-2"
                    >
                      <Download className="size-4" />
                      Export as JSON
                    </Button>
                  </div>
                </TabsContent>

                <TabsContent value="performance">
                  {activeResult.metrics?.bySide ? (
                    <PerformanceTable bySide={activeResult.metrics.bySide} />
                  ) : (
                    <div className="bg-title-bg border border-slate-700/50 overflow-hidden">
                      <p className="text-center text-gray-500 py-6 text-sm">
                        Long/Short breakdown metrics not available for this run.
                      </p>
                    </div>
                  )}
                </TabsContent>
                <TabsContent value="trades">
                  <div className="bg-title-bg border border-slate-700/50 overflow-hidden">
                    {tradesData?.trades && tradesData.trades.length > 0 ? (() => {
                      const totalTrades = tradesData.pagination.total
                      const totalPages = tradesData.pagination.totalPages
                      const startIdx = (tradePage - 1) * TRADES_PER_PAGE
                      const pageTrades = tradesData.trades

                      return (
                        <>
                          <Table>
                            <TableHeader className="bg-title-bg title-fade">
                              <TableRow className="border-b border-slate-700/50 hover:bg-transparent">
                                <TableHead>ID</TableHead>
                                <TableHead>Type</TableHead>
                                <TableHead>Qty</TableHead>
                                <TableHead>Entry Price</TableHead>
                                <TableHead>Exit Price</TableHead>
                                <TableHead>Entry Time</TableHead>
                                <TableHead>Run-up (MFE)</TableHead>
                                <TableHead>Drawdown (MAE)</TableHead>
                                <TableHead>Bars</TableHead>
                                <TableHead>Reason</TableHead>
                                <TableHead className="text-right">Net P&L</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {pageTrades.map((tr) => {
                                const pnl = formatPnl(tr.pnl)
                                const runUp = tr.runUpPct ? `${tr.runUpPct}%` : '-'
                                const drawdown = tr.drawdownPct ? `${tr.drawdownPct}%` : '-'
                                const bars = tr.barsHeld ?? '-'

                                return (
                                  <TableRow key={tr.id}>
                                    <TableCell className="font-mono text-xs text-slate-500">{tr.id}</TableCell>
                                    <TableCell>
                                      <Badge variant={tr.type === 'long' ? 'profit' : 'destructive'}>
                                        {tr.type.toUpperCase()}
                                      </Badge>
                                    </TableCell>
                                    <TableCell className="font-mono text-xs">{formatQty(tr.qty)}</TableCell>
                                    <TableCell className="font-mono text-xs">{formatPrice(tr.entryPrice)}</TableCell>
                                    <TableCell className="font-mono text-xs">{formatPrice(tr.exitPrice)}</TableCell>
                                    <TableCell className="text-slate-500 text-xs font-mono tabular-nums">
                                      {new Date(tr.entryAt).toLocaleDateString('en-US', {
                                        month: 'short', day: 'numeric',
                                        hour: '2-digit', minute: '2-digit',
                                      })}
                                    </TableCell>
                                    <TableCell className="font-mono text-xs text-emerald-400">
                                      {runUp}
                                    </TableCell>
                                    <TableCell className="font-mono text-xs text-red-400">
                                      {drawdown}
                                    </TableCell>
                                    <TableCell className="font-mono text-xs text-gray-400">
                                      {bars}
                                    </TableCell>
                                    <TableCell>
                                      <span className="text-xs capitalize text-gray-300">
                                        {tr.exitReason ? tr.exitReason.replace('_', ' ') : '-'}
                                      </span>
                                    </TableCell>
                                    <TableCell className={`text-right font-mono text-xs font-semibold ${pnl.isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                                      {pnl.value} ({formatSignedPct(tr.pnlPct)})
                                    </TableCell>
                                  </TableRow>
                                )
                              })}
                            </TableBody>
                          </Table>

                          {totalPages > 1 && (
                            <div className="flex items-center justify-between px-4 py-3 border-t border-slate-700/50">
                              <span className="text-sm text-slate-400">
                                {totalTrades} trades · page {tradePage} of {totalPages}
                              </span>
                              <div className="flex items-center gap-2">
                                <button
                                  onClick={() => setTradePage((p) => Math.max(1, p - 1))}
                                  disabled={tradePage === 1}
                                  className="p-1.5 rounded-lg text-slate-400 hover:text-gray-100 hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                                >
                                  <ChevronLeft className="size-4" />
                                </button>
                                <button
                                  onClick={() => setTradePage((p) => Math.min(totalPages, p + 1))}
                                  disabled={tradePage >= totalPages}
                                  className="p-1.5 rounded-lg text-slate-400 hover:text-gray-100 hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                                >
                                  <ChevronRight className="size-4" />
                                </button>
                              </div>
                            </div>
                          )}
                        </>
                      )
                    })() : (
                      <p className="text-center text-gray-500 py-6 text-sm">
                        No trades were executed during this backtest. Try relaxing strategy rules or expanding dates.
                      </p>
                    )}
                  </div>
                </TabsContent>

                <TabsContent value="comparison" className="space-y-3">
                  {compareError && (
                    <div className="flex items-center gap-2 px-3 py-2 rounded-md bg-amber-500/10 border border-amber-500/25 text-amber-400 text-xs">
                      <AlertTriangle className="size-3.5 shrink-0" />
                      {compareError}
                    </div>
                  )}
                  {comparisonIds.length < 2 ? (
                    <Card>
                      <CardContent className="py-16 text-center">
                        <div className="flex flex-col items-center gap-3">
                          <div className="size-12 rounded-full bg-gray-800 flex items-center justify-center">
                            <Activity className="size-5 text-gray-600" />
                          </div>
                          <p className="text-gray-400 font-medium text-sm">Select runs to compare</p>
                          <p className="text-gray-600 text-xs max-w-xs">
                            Tick the checkbox on at least 2 completed runs in History to see a side-by-side breakdown here.
                          </p>
                        </div>
                      </CardContent>
                    </Card>
                  ) : comparisonLoading ? (
                    <Card className="flex justify-center items-center py-24">
                      <div className="flex flex-col items-center gap-3">
                        <Loader2 className="size-8 animate-spin text-emerald-400" />
                        <span className="text-gray-400 text-sm">Loading comparison data…</span>
                      </div>
                    </Card>
                  ) : comparisonResults.length >= 2 ? (
                    <ComparisonTable results={comparisonResults} />
                  ) : (
                    <Card>
                      <CardContent className="py-10 text-center text-gray-500 text-sm">
                        Could not load data for the selected runs.
                      </CardContent>
                    </Card>
                  )}
                </TabsContent>
              </div>
            </Tabs>
          ) : (
            <Card className="h-full flex flex-col justify-center items-center py-20 px-6 text-center">
              <Activity className="size-10 text-gray-700 mb-3" />
              <h3 className="text-gray-300 font-semibold mb-1">No Simulation Results Loaded</h3>
              <p className="text-gray-500 text-sm max-w-sm">
                Select a previous run from History on the left, or configure and launch a new backtest simulation.
              </p>
            </Card>
          )}
        </div>
      </div>

      <Dialog open={showWizard} onOpenChange={(open) => { if (!open) setShowWizard(false) }}>
        <DialogContent className="w-[720px] max-w-[95vw] max-h-[90vh] overflow-y-auto overflow-x-hidden bg-title-bg">
          <NewBacktestWizard
            onCancel={() => setShowWizard(false)}
            onRun={(config) => {
              setShowWizard(false)
              handleRun(config)
            }}
          />
        </DialogContent>
      </Dialog>
    </PageWrapper>
  )
}
