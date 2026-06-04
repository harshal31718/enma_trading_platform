import { useState, useEffect } from 'react'
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
} from 'lucide-react'

import PageWrapper from '../components/layout/PageWrapper'
import PageHeader from '../components/ui/PageHeader'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/card'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../components/ui/table'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import EquityCurve from '../components/charts/EquityCurve'
import BacktestConfigForm from '../features/backtest/BacktestConfigForm'
import BacktestHistory from '../features/backtest/BacktestHistory'
import BacktestMetricCard from '../features/backtest/BacktestMetricCard'

import {
  useRunBacktest,
  useBacktestsList,
  useBacktestResult,
  useCancelBacktest,
  useBacktestTrades,
} from '../hooks/useBacktest'
import { formatQty, formatPrice, formatPct, formatSignedPct, formatPnl, formatIsoDate } from '../utils/formatters'
import socket from '../lib/socket'
import { useQueryClient } from '@tanstack/react-query'

export default function Backtest() {
  const queryClient = useQueryClient()
  const { data: listData, isLoading: loadingHistory, refetch: refetchHistory } = useBacktestsList(1, 20)

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

  return (
    <PageWrapper>
      <PageHeader
        title="Backtest"
        description="Test strategy rules against historical candle data with full metrics and charts"
      />

      {errorMessage && (
        <div className="mt-4 bg-red-950/20 border border-red-800/40 rounded-lg p-3 flex items-center gap-2 text-red-400 text-sm">
          <AlertTriangle className="size-4 shrink-0" />
          {errorMessage}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 mt-6">
        {/* Left Column */}
        <div className="lg:col-span-1 space-y-6">
          <BacktestConfigForm
            isRunning={!!activeJobId}
            onSubmit={handleRun}
            onCancel={handleCancel}
          />
          <BacktestHistory
            data={listData?.backtests}
            selectedId={selectedResultId}
            onSelect={(id) => { setSelectedResultId(id); setTradePage(1) }}
            onRefresh={refetchHistory}
            isLoading={loadingHistory}
          />
        </div>

        {/* Right Column */}
        <div className="lg:col-span-3 space-y-6">
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
            <div className="space-y-6">
              {activeResult.status === 'failed' && (
                <div className="bg-red-950/20 border border-red-800/40 rounded-lg p-4 flex items-center gap-3 text-red-400 text-sm">
                  <AlertTriangle className="size-5 shrink-0" />
                  <div>
                    <span className="font-semibold">Execution Failed:</span>{' '}
                    {activeResult.error || 'Unknown error occurred.'}
                  </div>
                </div>
              )}

              {activeResult.metrics && (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <BacktestMetricCard
                    title="Net Profit"
                    value={formatPrice(activeResult.metrics.netProfit)}
                    subtext={formatSignedPct(activeResult.metrics.netProfitPct)}
                    icon={DollarSign}
                    valueClassName={getPnlClass(activeResult.metrics.netProfit)}
                  />
                  <BacktestMetricCard
                    title="Max Drawdown"
                    value={formatPct(activeResult.metrics.maxDrawdown)}
                    subtext="Peak equity drop"
                    icon={Percent}
                    valueClassName="text-red-400"
                  />
                  <BacktestMetricCard
                    title="Win Rate"
                    value={formatPct(parseFloat(activeResult.metrics.winRate) * 100)}
                    subtext={`${activeResult.metrics.winningTrades} of ${activeResult.metrics.totalTrades} trades`}
                    icon={TrendingUp}
                  />
                  <BacktestMetricCard
                    title="Sharpe Ratio"
                    value={parseFloat(activeResult.metrics.sharpeRatio).toFixed(2)}
                    subtext="Risk-adjusted return"
                    icon={Activity}
                  />
                  <BacktestMetricCard
                    title="Sortino Ratio"
                    value={parseFloat(activeResult.metrics.sortinoRatio).toFixed(2)}
                    subtext="Downside adjusted"
                    icon={Activity}
                  />
                  <BacktestMetricCard
                    title="Calmar Ratio"
                    value={parseFloat(activeResult.metrics.calmarRatio).toFixed(2)}
                    subtext="Return/DD ratio"
                    icon={Activity}
                  />
                </div>
              )}

              <Card>
                <CardHeader>
                  <CardTitle>Performance Charts</CardTitle>
                  <CardDescription>Visualizing balance history and drawdowns over time</CardDescription>
                </CardHeader>
                <CardContent>
                  <EquityCurve data={activeResult.equityCurve} />
                </CardContent>
              </Card>

              <Card className="p-5">
                <h4 className="text-gray-100 font-semibold mb-3">Simulation Config</h4>
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
                </div>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Execution Log</CardTitle>
                  <CardDescription>
                    Complete historical trade record ({tradesData?.pagination?.total || 0} trades)
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {tradesData?.trades && tradesData.trades.length > 0 ? (() => {
                    const totalTrades = tradesData.pagination.total
                    const totalPages = tradesData.pagination.totalPages
                    const startIdx = (tradePage - 1) * TRADES_PER_PAGE
                    const pageTrades = tradesData.trades

                    return (
                      <div className="space-y-4">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead>ID</TableHead>
                              <TableHead>Type</TableHead>
                              <TableHead>Quantity</TableHead>
                              <TableHead>Entry Price</TableHead>
                              <TableHead>Exit Price</TableHead>
                              <TableHead>Entry Time</TableHead>
                              <TableHead>Reason</TableHead>
                              <TableHead className="text-right">Net P&L</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {pageTrades.map((tr) => {
                              const pnl = formatPnl(tr.pnl)
                              return (
                                <TableRow key={tr.id}>
                                  <TableCell className="font-mono text-xs">{tr.id}</TableCell>
                                  <TableCell>
                                    <Badge variant={tr.type === 'long' ? 'profit' : 'destructive'}>
                                      {tr.type.toUpperCase()}
                                    </Badge>
                                  </TableCell>
                                  <TableCell className="font-mono text-xs">{formatQty(tr.qty)}</TableCell>
                                  <TableCell className="font-mono text-xs">{formatPrice(tr.entryPrice)}</TableCell>
                                  <TableCell className="font-mono text-xs">{formatPrice(tr.exitPrice)}</TableCell>
                                  <TableCell className="text-gray-400 text-xs">
                                    {new Date(tr.entryAt).toLocaleDateString('en-US', {
                                      month: 'short', day: 'numeric',
                                      hour: '2-digit', minute: '2-digit',
                                    })}
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
                          <div className="flex items-center justify-between pt-2 border-t border-gray-800">
                            <span className="text-xs text-gray-500">
                              Showing {startIdx + 1}–{Math.min(startIdx + TRADES_PER_PAGE, totalTrades)} of {totalTrades} trades
                            </span>
                            <div className="flex items-center gap-1">
                              <button
                                onClick={() => setTradePage((p) => Math.max(1, p - 1))}
                                disabled={tradePage === 1}
                                className="p-1.5 rounded border border-gray-800 text-gray-400 hover:text-gray-100 hover:border-gray-600 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                              >
                                <ChevronLeft className="size-4" />
                              </button>
                              {Array.from({ length: totalPages }, (_, i) => i + 1)
                                .filter((p) => p === 1 || p === totalPages || Math.abs(p - tradePage) <= 2)
                                .reduce((acc, p, idx, arr) => {
                                  if (idx > 0 && p - arr[idx - 1] > 1) acc.push('…')
                                  acc.push(p)
                                  return acc
                                }, [])
                                .map((item, idx) =>
                                  item === '…' ? (
                                    <span key={`e-${idx}`} className="px-1 text-gray-600 text-xs">…</span>
                                  ) : (
                                    <button
                                      key={item}
                                      onClick={() => setTradePage(item)}
                                      className={`min-w-[28px] h-7 px-1.5 rounded border text-xs font-medium transition-colors ${
                                        tradePage === item
                                          ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-400'
                                          : 'border-gray-800 text-gray-400 hover:text-gray-100 hover:border-gray-600'
                                      }`}
                                    >
                                      {item}
                                    </button>
                                  )
                                )}
                              <button
                                onClick={() => setTradePage((p) => Math.min(totalPages, p + 1))}
                                disabled={tradePage === totalPages}
                                className="p-1.5 rounded border border-gray-800 text-gray-400 hover:text-gray-100 hover:border-gray-600 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                              >
                                <ChevronRight className="size-4" />
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    )
                  })() : (
                    <div className="text-center text-gray-500 py-6">
                      No trades were executed during this backtest. Try relaxing strategy rules or expanding dates.
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
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
    </PageWrapper>
  )
}
