import { useState, useEffect, useMemo, useRef, lazy, Suspense } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import toast from 'react-hot-toast'
import {
  AlertTriangle,
  Activity,
  Loader2,
  Download,
  Plus,
  Square,
  Dices,
} from 'lucide-react'

import PageWrapper from '../components/layout/PageWrapper'
import PageHeader from '../components/ui/PageHeader'
import { Card } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Dialog, DialogContent } from '../components/ui/dialog'
import BacktestHistory from '../features/backtest/BacktestHistory'
import PerformanceTable from '../features/backtest/PerformanceTable'
import OverviewTab from '../features/backtest/OverviewTab'
import TradesTab from '../features/backtest/TradesTab'
import ComparisonTab from '../features/backtest/ComparisonTab'

const NewBacktestWizard = lazy(() => import('../features/backtest/NewBacktestWizard'))

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
import { exportResultAsJSON } from '../utils/exporters'
import socket from '../lib/socket'
import { useQueryClient, useQueries } from '@tanstack/react-query'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../components/ui/tabs'

const HISTORY_FILTER_KEYS = ['strategyName', 'symbol', 'timeframe', 'status', 'createdAfter', 'createdBefore']

export default function Backtest() {
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const jobIdParam = searchParams.get('jobId')

  // Phase 4b (Plan 10 §4.3 item 5) — RobustPickPanel's "Copy robust pick →
  // Backtest" deep link. Prefixed `prefill*` names deliberately: bare
  // `symbol`/`timeframe` already belong to the history-filter params below.
  const prefillStrategyId = searchParams.get('prefillStrategyId')
  const prefillSymbol = searchParams.get('prefillSymbol')
  const prefillTimeframe = searchParams.get('prefillTimeframe')
  const prefillExchange = searchParams.get('prefillExchange')
  const prefillParamsRaw = searchParams.get('prefillParams')
  // Phase 4b (risk_pct/leverage search) — present only when the deep-linked
  // robust pick came from a run that searched risk_pct/leverage.
  const prefillLeverage = searchParams.get('prefillLeverage')
  const prefillRiskPct = searchParams.get('prefillRiskPct')

  // History filters live in the URL (?strategyName=&symbol=&...) per §3.4 — shareable,
  // survives refresh, back-button-able. jobId is a separate, pre-existing deep-link param.
  const historyFilters = {
    strategyName: searchParams.get('strategyName') || '',
    symbol: searchParams.get('symbol') || '',
    timeframe: searchParams.get('timeframe') || '',
    status: searchParams.get('status') || '',
    createdAfter: searchParams.get('createdAfter') || '',
    createdBefore: searchParams.get('createdBefore') || '',
  }

  function setHistoryFilters(nextFilters) {
    const next = new URLSearchParams(searchParams)
    HISTORY_FILTER_KEYS.forEach((key) => {
      const value = nextFilters[key]
      if (value === undefined || value === null || value === '') next.delete(key)
      else next.set(key, value)
    })
    setSearchParams(next)
  }

  const [comparisonIds, setComparisonIds] = useState([])
  const [compareError, setCompareError] = useState('')
  const [showWizard, setShowWizard] = useState(false)

  // Phase 4b prefill payload for NewBacktestWizard — undefined (not just
  // falsy) when no prefillStrategyId is present, so the wizard's own
  // "nothing passed" behavior is untouched for every normal "Run Backtest"/
  // "Run Again" click.
  const prefillConfig = useMemo(() => {
    if (!prefillStrategyId) return undefined
    let params
    if (prefillParamsRaw) {
      try {
        params = JSON.parse(prefillParamsRaw)
      } catch {
        params = undefined // malformed/tampered URL — degrade to no param prefill, not a crash
      }
    }
    return {
      strategyId: prefillStrategyId,
      symbol: prefillSymbol || undefined,
      timeframe: prefillTimeframe || undefined,
      exchange: prefillExchange || undefined,
      params,
      // Phase 4b: only present when the robust pick searched risk_pct/leverage.
      leverage: prefillLeverage || undefined,
      riskPct: prefillRiskPct || undefined,
    }
  }, [prefillStrategyId, prefillSymbol, prefillTimeframe, prefillExchange, prefillParamsRaw, prefillLeverage, prefillRiskPct])

  // Auto-open the wizard once for a deep-linked prefill — guarded so
  // navigating away and back within the same URL doesn't keep re-opening it.
  const prefillWizardOpened = useRef(false)
  useEffect(() => {
    if (prefillConfig && !prefillWizardOpened.current) {
      setShowWizard(true)
      prefillWizardOpened.current = true
    }
  }, [prefillConfig])

  const { data: listData, isLoading: loadingHistory, isError: historyError, refetch: refetchHistory } = useBacktestsList(1, 20, historyFilters)

  const [activeJobId, setActiveJobId] = useState(null)
  const [progressPct, setProgressPct] = useState(0)
  const [progressMessage, setProgressMessage] = useState('')
  const [selectedResultId, setSelectedResultId] = useState(null)
  const [errorMessage, setErrorMessage] = useState('')
  const [tradePage, setTradePage] = useState(1)
  const TRADES_PER_PAGE = 20

  const runMutation = useRunBacktest()
  const cancelMutation = useCancelBacktest()

  const { data: activeResult, isLoading: loadingResult, isError: resultError } = useBacktestResult(
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
        toast.success('Backtest simulation completed successfully')
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
        toast.error(`Backtest simulation failed: ${data.error}`)
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
      toast.success('Backtest run queued successfully')
    } catch (err) {
      // Roll back: clear active state so the UI doesn't hang
      setActiveJobId(null)
      setProgressPct(0)
      setProgressMessage('')
      const errorMsg = err.response?.data?.error?.message || err.message || 'Failed to start backtest'
      setErrorMessage(`Failed to start backtest: ${errorMsg}`)
      toast.error(errorMsg)
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
            Run Backtest
          </button>
        }
      />

      {errorMessage && (
        <div className="bg-red-950/20 border border-red-800/40 rounded-lg p-3 flex items-center gap-2 text-red-400 text-sm">
          <AlertTriangle className="size-4 shrink-0" />
          {errorMessage}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-0 h-auto lg:h-[calc(100vh-100px)] overflow-y-auto lg:overflow-hidden">
        {/* Left Column — Run History */}
        <div className="lg:col-span-1 border-b lg:border-b-0 lg:border-r border-slate-700/50 h-[320px] lg:h-full overflow-hidden">
          <BacktestHistory
            data={listData?.backtests}
            selectedId={selectedResultId}
            onSelect={(id) => { setSelectedResultId(id); setTradePage(1) }}
            onRefresh={refetchHistory}
            isLoading={loadingHistory}
            isError={historyError}
            filters={historyFilters}
            onApplyFilters={(nextFilters) => setHistoryFilters(nextFilters)}
            onClearFilters={(nextFilters) => setHistoryFilters(nextFilters)}
            comparisonIds={comparisonIds}
            onToggleComparison={toggleComparison}
          />
        </div>

        {/* Right Column */}
        <div className="lg:col-span-3 h-[600px] lg:h-full overflow-hidden flex flex-col">
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
          ) : resultError ? (
            <Card className="h-full flex justify-center items-center py-32">
              <div className="flex flex-col items-center gap-4 text-center">
                <AlertTriangle className="size-8 text-red-400" />
                <div>
                  <p className="text-sm font-medium text-slate-200">
                    {jobIdParam ? 'Result not found' : 'Failed to load result'}
                  </p>
                  <p className="mt-1 text-xs text-slate-400">
                    {jobIdParam
                      ? 'The backtest result linked in the URL could not be found.'
                      : 'Something went wrong loading the result.'}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => refetchHistory()}
                    className="px-3 py-1.5 text-xs border border-slate-700 rounded-lg text-slate-300 hover:bg-slate-800 transition-colors"
                  >
                    Browse all runs
                  </button>
                </div>
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
                <Link
                  to={`/lab?sourceJobId=${activeResult.jobId}`}
                  className="ml-auto flex items-center justify-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-sm rounded-lg transition-colors"
                  title="Run a Monte Carlo robustness simulation on this backtest"
                >
                  <Dices className="size-4 text-emerald-400" />
                  Robustness Check
                </Link>
                <button
                  onClick={() => exportResultAsJSON(activeResult, activeResult.strategyName || 'backtest')}
                  className="mr-4 flex items-center justify-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm rounded-lg transition-colors"
                >
                  <Download className="size-4" />
                  Export JSON
                </button>
              </div>

              {/* ── Scrollable content area ── */}
              <div className="flex-1 overflow-hidden flex flex-col relative">
                {activeResult.status === 'failed' ? (
                  <div className="flex flex-col items-center justify-center gap-4 p-8 text-center">
                    <div className="bg-red-950/20 border border-red-800/40 rounded-lg p-5 flex items-start gap-3 text-red-400 text-sm max-w-md w-full">
                      <AlertTriangle className="size-5 shrink-0 mt-0.5" />
                      <div className="text-left">
                        <p className="font-semibold mb-1">Backtest failed</p>
                        <p className="text-red-300/80 text-xs">{activeResult.error || 'Unknown error occurred.'}</p>
                      </div>
                    </div>
                    <button
                      onClick={() => setShowWizard(true)}
                      className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm rounded-lg transition-colors"
                    >
                      <Plus size={14} />
                      Run Again
                    </button>
                  </div>
                ) : null}

                <TabsContent value="overview" className={`h-full w-full m-0 outline-none overflow-y-auto ${activeResult.status === 'failed' ? 'hidden' : 'data-[state=active]:block'}`}>
                  <OverviewTab activeResult={activeResult} benchmarkData={benchmarkData} allTradesData={allTradesData} />
                </TabsContent>

                <TabsContent value="performance" className={`h-full w-full m-0 outline-none flex-col overflow-hidden ${activeResult.status === 'failed' ? 'hidden' : 'data-[state=active]:flex'}`}>
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
                <TabsContent value="trades" className={`h-full w-full m-0 outline-none flex-col overflow-hidden ${activeResult.status === 'failed' ? 'hidden' : 'data-[state=active]:flex'}`}>
                  <TradesTab tradesData={tradesData} tradePage={tradePage} setTradePage={setTradePage} tradesPerPage={TRADES_PER_PAGE} />
                </TabsContent>

                <TabsContent value="comparison" className={`h-full w-full m-0 outline-none flex-col overflow-hidden ${activeResult.status === 'failed' ? 'hidden' : 'data-[state=active]:flex'}`}>
                  <ComparisonTab
                    compareError={compareError}
                    comparisonIds={comparisonIds}
                    comparisonLoading={comparisonLoading}
                    comparisonResults={comparisonResults}
                  />
                </TabsContent>
              </div>
            </Tabs>
            ) : (
              <Card className="h-full flex flex-col items-center justify-center gap-3 py-32">
                <div className="size-12 rounded-full bg-gray-800 flex items-center justify-center">
                  <Activity className="size-5 text-gray-600" />
                </div>
                <p className="text-gray-400 text-sm">Select a backtest from history, or run a new one.</p>
              </Card>
            )}
          </div>
        </div>

        <Dialog open={showWizard} onOpenChange={setShowWizard}>
          <DialogContent className="max-w-2xl bg-title-bg border-slate-700/50">
            <Suspense fallback={<div className="p-8 text-center font-mono text-xs text-slate-400">Loading Wizard...</div>}>
              <NewBacktestWizard
                onCancel={() => setShowWizard(false)}
                onRun={(config) => { setShowWizard(false); handleRun(config) }}
                initialConfig={prefillConfig}
              />
            </Suspense>
          </DialogContent>
        </Dialog>
    </PageWrapper>
  )
}
