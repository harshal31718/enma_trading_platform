import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import toast from 'react-hot-toast'
import { useQueryClient } from '@tanstack/react-query'
import PageWrapper from '@/components/layout/PageWrapper'
import PageHeader from '@/components/ui/PageHeader'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import socket from '../lib/socket'
import { useRunMonteCarlo, useSimulation, useRunOptimization, useOptimization, useRunPBO, usePBO } from '../hooks/useLab'
import { useBacktestResult } from '../hooks/useBacktest'
import RunWizard from '../components/lab/RunWizard'
import HistoryRail from '../components/lab/HistoryRail'
import FanChart from '../components/lab/FanChart'
import PercentileSpread from '../components/lab/PercentileSpread'
import ExceedanceCurve from '../components/lab/ExceedanceCurve'
import RuinCard from '../components/lab/RuinCard'
import VerdictStrip from '../components/lab/VerdictStrip'
import ConfigDrawer from '../components/lab/ConfigDrawer'
import WalkForwardWizard from '../components/lab/WalkForwardWizard'
import OptimizationHistoryRail from '../components/lab/OptimizationHistoryRail'
import FoldResultsTable from '../components/lab/FoldResultsTable'
import TrialsExplorer from '../components/lab/TrialsExplorer'
import RobustPickPanel from '../components/lab/RobustPickPanel'
import StitchedOOSCard from '../components/lab/StitchedOOSCard'
import DegradationVerdict from '../components/lab/DegradationVerdict'
import PBOWizard from '../components/lab/PBOWizard'
import PBOHistoryRail from '../components/lab/PBOHistoryRail'
import PBOVerdictCard from '../components/lab/PBOVerdictCard'
import PBOCandidatesTable from '../components/lab/PBOCandidatesTable'

// Plan 10 Phase 2/3c — Strategy Lab page. Two tabs per §4.1: Robustness (MC)
// and Optimizer (walk-forward). Both are job-based against the same
// labResults/BullMQ/Socket.IO infrastructure.
export default function StrategyLab() {
  const [searchParams] = useSearchParams()
  const sourceJobIdParam = searchParams.get('sourceJobId') || ''

  return (
    <PageWrapper>
      <PageHeader title="Strategy Lab" description="Monte Carlo robustness simulation and walk-forward optimization" />
      <div className="p-6">
        <Tabs defaultValue="robustness" className="w-full">
          <TabsList className="mb-4 border-b border-slate-800">
            <TabsTrigger value="robustness">Robustness (MC)</TabsTrigger>
            <TabsTrigger value="optimizer">Optimizer</TabsTrigger>
            <TabsTrigger value="pbo">Overfitting (PBO)</TabsTrigger>
          </TabsList>
          <TabsContent value="robustness">
            <RobustnessTab sourceJobIdParam={sourceJobIdParam} />
          </TabsContent>
          <TabsContent value="optimizer">
            <OptimizerTab />
          </TabsContent>
          <TabsContent value="pbo">
            <PBOTab />
          </TabsContent>
        </Tabs>
      </div>
    </PageWrapper>
  )
}

function RobustnessTab({ sourceJobIdParam }) {
  const queryClient = useQueryClient()

  const [sourceJobId, setSourceJobId] = useState(sourceJobIdParam)
  const [selectedLabId, setSelectedLabId] = useState(null)
  const [progressPct, setProgressPct] = useState(0)
  const [progressMessage, setProgressMessage] = useState('')

  const runMutation = useRunMonteCarlo()
  const { data: sim } = useSimulation(selectedLabId)
  const { data: parentBacktest } = useBacktestResult(sourceJobId || null)

  useEffect(() => {
    if (sourceJobIdParam) setSourceJobId(sourceJobIdParam)
  }, [sourceJobIdParam])

  // Socket.IO progress streaming — mirrors Backtest.jsx's pattern exactly,
  // against the simulation:{labId} room (server/src/services/socketEmitter.js).
  useEffect(() => {
    if (!selectedLabId) return

    const handleProgress = (data) => {
      if (data.simId === selectedLabId) {
        setProgressPct(data.pct || 0)
        setProgressMessage(data.message || '')
      }
    }
    const handleComplete = (data) => {
      if (data.simId === selectedLabId) {
        setProgressPct(0)
        setProgressMessage('')
        toast.success('Robustness run completed')
        queryClient.invalidateQueries({ queryKey: ['lab', 'simulations', selectedLabId] })
        queryClient.invalidateQueries({ queryKey: ['lab', 'simulations', 'list'] })
      }
    }
    const handleError = (data) => {
      if (data.simId === selectedLabId) {
        setProgressPct(0)
        setProgressMessage('')
        toast.error(`Robustness run failed: ${data.error}`)
        queryClient.invalidateQueries({ queryKey: ['lab', 'simulations', selectedLabId] })
      }
    }

    socket.connect()
    socket.emit('join', `simulation:${selectedLabId}`)
    socket.on('simulation:progress', handleProgress)
    socket.on('simulation:complete', handleComplete)
    socket.on('simulation:error', handleError)

    return () => {
      socket.off('simulation:progress', handleProgress)
      socket.off('simulation:complete', handleComplete)
      socket.off('simulation:error', handleError)
    }
  }, [selectedLabId, queryClient])

  const handleRun = async (config) => {
    setSourceJobId(config.sourceJobId)
    try {
      const res = await runMutation.mutateAsync(config)
      setSelectedLabId(res.labId)
      if (res.cached) toast.success('Identical config already run — showing cached result')
      else toast.success('Robustness run queued')
    } catch (err) {
      toast.error(err.response?.data?.message || 'Failed to queue run')
    }
  }

  const results = sim?.results
  const isRunning = sim && ['queued', 'running'].includes(sim.status)
  const isFailed = sim?.status === 'failed'
  const pointEstimatePct = parentBacktest?.metrics?.netProfitPct != null
    ? parseFloat(parentBacktest.metrics.netProfitPct)
    : null

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-6">
      {/* Left rail */}
      <div className="space-y-4">
        <RunWizard
          initialSourceJobId={sourceJobIdParam}
          onRun={handleRun}
          submitting={runMutation.isPending}
        />
        <HistoryRail
          sourceJobId={sourceJobId}
          selectedLabId={selectedLabId}
          onSelect={setSelectedLabId}
        />
      </div>

      {/* Results canvas */}
      <div className="space-y-4">
        {!selectedLabId && (
          <div className="border border-dashed border-slate-800 p-12 text-center text-xs text-slate-500 font-mono italic">
            Configure and run a robustness simulation, or select one from history.
          </div>
        )}

        {selectedLabId && isRunning && (
          <div className="border border-slate-800 bg-slate-950 p-8 text-center">
            <p className="text-xs text-emerald-400 font-mono animate-pulse mb-3">
              {progressMessage || 'Running simulation on engine…'}
            </p>
            <div className="w-full h-1.5 bg-slate-900 max-w-md mx-auto">
              <div className="h-1.5 bg-emerald-500 transition-all" style={{ width: `${progressPct}%` }} />
            </div>
          </div>
        )}

        {selectedLabId && isFailed && (
          <div className="border border-red-800/40 bg-red-950/10 p-8 text-center text-xs text-red-400 font-mono">
            Simulation failed: {sim.error || 'unknown error'}
          </div>
        )}

        {selectedLabId && results && sim.status === 'completed' && (
          <>
            <VerdictStrip
              pointEstimatePct={pointEstimatePct}
              finalEquityPercentiles={results.finalEquityPercentiles}
              mode={results.meta?.mode}
            />

            <div className="border border-slate-800 bg-slate-950 p-4">
              <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">
                Equity fan chart ({results.meta?.nRuns?.toLocaleString()} runs, {results.meta?.mode} bootstrap)
              </h4>
              <FanChart equityBands={results.equityBands} />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <PercentileSpread
                title="Final equity (% return)"
                percentiles={
                  results.finalEquityPercentiles
                    ? Object.fromEntries(
                        Object.entries(results.finalEquityPercentiles).map(([k, v]) => [k, (v - 1) * 100])
                      )
                    : null
                }
              />
              <PercentileSpread
                title="Max drawdown (%)"
                percentiles={
                  results.maxDrawdownPercentiles
                    ? Object.fromEntries(
                        Object.entries(results.maxDrawdownPercentiles).map(([k, v]) => [k, v * 100])
                      )
                    : null
                }
                positiveIsGood={false}
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-[1fr_280px] gap-4">
              <div className="border border-slate-800 bg-slate-950 p-4">
                <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">
                  Drawdown exceedance
                </h4>
                <ExceedanceCurve
                  drawdownExceedance={results.drawdownExceedance}
                  ruinThresholdPct={sim.config?.ruinThresholdPct}
                />
              </div>
              <RuinCard
                ruinProbability={results.ruinProbability}
                ruinThresholdPct={sim.config?.ruinThresholdPct}
              />
            </div>

            <ConfigDrawer
              config={sim.config}
              meta={results.meta}
              labId={sim.labId}
              sourceJobId={sim.sourceJobId}
            />
          </>
        )}
      </div>
    </div>
  )
}

function OptimizerTab() {
  const queryClient = useQueryClient()
  const [selectedLabId, setSelectedLabId] = useState(null)
  const [progressPct, setProgressPct] = useState(0)
  const [progressMessage, setProgressMessage] = useState('')

  const runMutation = useRunOptimization()
  const { data: opt } = useOptimization(selectedLabId)

  // Socket.IO progress streaming against the optimization:{labId} room.
  useEffect(() => {
    if (!selectedLabId) return

    const handleProgress = (data) => {
      if (data.labId === selectedLabId) {
        setProgressPct(data.pct || 0)
        setProgressMessage(data.message || '')
      }
    }
    const handleComplete = (data) => {
      if (data.labId === selectedLabId) {
        setProgressPct(0)
        setProgressMessage('')
        toast.success('Walk-forward run completed')
        queryClient.invalidateQueries({ queryKey: ['lab', 'optimizations', selectedLabId] })
        queryClient.invalidateQueries({ queryKey: ['lab', 'optimizations', 'list'] })
      }
    }
    const handleError = (data) => {
      if (data.labId === selectedLabId) {
        setProgressPct(0)
        setProgressMessage('')
        toast.error(`Walk-forward run failed: ${data.error}`)
        queryClient.invalidateQueries({ queryKey: ['lab', 'optimizations', selectedLabId] })
      }
    }

    socket.connect()
    socket.emit('join', `optimization:${selectedLabId}`)
    socket.on('optimization:progress', handleProgress)
    socket.on('optimization:complete', handleComplete)
    socket.on('optimization:error', handleError)

    return () => {
      socket.off('optimization:progress', handleProgress)
      socket.off('optimization:complete', handleComplete)
      socket.off('optimization:error', handleError)
    }
  }, [selectedLabId, queryClient])

  const handleRun = async (config) => {
    try {
      const res = await runMutation.mutateAsync(config)
      setSelectedLabId(res.labId)
      if (res.cached) toast.success('Identical config already run — showing cached result')
      else toast.success('Walk-forward run queued (this can take several minutes)')
    } catch (err) {
      toast.error(err.response?.data?.message || 'Failed to queue run')
    }
  }

  const results = opt?.results
  const isRunning = opt && ['queued', 'running'].includes(opt.status)
  const isFailed = opt?.status === 'failed'

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-6">
      <div className="space-y-4">
        <WalkForwardWizard onRun={handleRun} submitting={runMutation.isPending} />
        <OptimizationHistoryRail selectedLabId={selectedLabId} onSelect={setSelectedLabId} />
      </div>

      <div className="space-y-4">
        {!selectedLabId && (
          <div className="border border-dashed border-slate-800 p-12 text-center text-xs text-slate-500 font-mono italic">
            Configure and run a walk-forward optimization, or select one from history.
          </div>
        )}

        {selectedLabId && isRunning && (
          <div className="border border-slate-800 bg-slate-950 p-8 text-center">
            <p className="text-xs text-emerald-400 font-mono animate-pulse mb-3">
              {progressMessage || 'Running walk-forward optimization on engine — this can take several minutes…'}
            </p>
            <div className="w-full h-1.5 bg-slate-900 max-w-md mx-auto">
              <div className="h-1.5 bg-emerald-500 transition-all" style={{ width: `${progressPct}%` }} />
            </div>
          </div>
        )}

        {selectedLabId && isFailed && (
          <div className="border border-red-800/40 bg-red-950/10 p-8 text-center text-xs text-red-400 font-mono">
            Optimization failed: {opt.error || 'unknown error'}
          </div>
        )}

        {selectedLabId && results && opt.status === 'completed' && (
          <>
            <DegradationVerdict
              avgDegradationRatio={results.avgDegradationRatio}
              nFoldsBuilt={results.nFoldsBuilt}
              mode={results.mode}
              method={results.method}
            />
            <StitchedOOSCard stitchedOOS={results.stitchedOOS} minTradesWarning={results.minTradesWarning} />
            <FoldResultsTable folds={results.folds} />
            <RobustPickPanel folds={results.folds} config={opt.config} />
            <TrialsExplorer folds={results.folds} />
            <div className="border border-dashed border-slate-800 p-3 text-[10px] text-slate-500 font-mono italic">
              MC-scored selection (above) is opt-in — <span className="text-slate-400">mcScoring: false</span> reproduces
              today's raw-loss-only fold winner exactly, unchanged. PBO (Probability of Backtest
              Overfitting) is a separate, deliberately non-walk-forward procedure — see the
              "Overfitting (PBO)" tab.
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function PBOTab() {
  const queryClient = useQueryClient()
  const [selectedLabId, setSelectedLabId] = useState(null)
  const [progressPct, setProgressPct] = useState(0)
  const [progressMessage, setProgressMessage] = useState('')

  const runMutation = useRunPBO()
  const { data: pboRun } = usePBO(selectedLabId)

  // Socket.IO progress streaming against the pbo:{labId} room — mirrors the
  // Optimizer tab's optimization:{labId} wiring exactly.
  useEffect(() => {
    if (!selectedLabId) return

    const handleProgress = (data) => {
      if (data.labId === selectedLabId) {
        setProgressPct(data.pct || 0)
        setProgressMessage(data.message || '')
      }
    }
    const handleComplete = (data) => {
      if (data.labId === selectedLabId) {
        setProgressPct(0)
        setProgressMessage('')
        toast.success('PBO run completed')
        queryClient.invalidateQueries({ queryKey: ['lab', 'pbo', selectedLabId] })
        queryClient.invalidateQueries({ queryKey: ['lab', 'pbo', 'list'] })
      }
    }
    const handleError = (data) => {
      if (data.labId === selectedLabId) {
        setProgressPct(0)
        setProgressMessage('')
        toast.error(`PBO run failed: ${data.error}`)
        queryClient.invalidateQueries({ queryKey: ['lab', 'pbo', selectedLabId] })
      }
    }

    socket.connect()
    socket.emit('join', `pbo:${selectedLabId}`)
    socket.on('pbo:progress', handleProgress)
    socket.on('pbo:complete', handleComplete)
    socket.on('pbo:error', handleError)

    return () => {
      socket.off('pbo:progress', handleProgress)
      socket.off('pbo:complete', handleComplete)
      socket.off('pbo:error', handleError)
    }
  }, [selectedLabId, queryClient])

  const handleRun = async (config) => {
    try {
      const res = await runMutation.mutateAsync(config)
      setSelectedLabId(res.labId)
      if (res.cached) toast.success('Identical config already run — showing cached result')
      else toast.success('PBO run queued (this can take a few minutes)')
    } catch (err) {
      toast.error(err.response?.data?.message || 'Failed to queue run')
    }
  }

  const results = pboRun?.results
  const isRunning = pboRun && ['queued', 'running'].includes(pboRun.status)
  const isFailed = pboRun?.status === 'failed'

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-6">
      <div className="space-y-4">
        <PBOWizard onRun={handleRun} submitting={runMutation.isPending} />
        <PBOHistoryRail selectedLabId={selectedLabId} onSelect={setSelectedLabId} />
      </div>

      <div className="space-y-4">
        {!selectedLabId && (
          <div className="border border-dashed border-slate-800 p-12 text-center text-xs text-slate-500 font-mono italic">
            Configure and run a PBO (Probability of Backtest Overfitting) check, or select one from history.
          </div>
        )}

        {selectedLabId && isRunning && (
          <div className="border border-slate-800 bg-slate-950 p-8 text-center">
            <p className="text-xs text-emerald-400 font-mono animate-pulse mb-3">
              {progressMessage || 'Running PBO on engine — this can take a few minutes…'}
            </p>
            <div className="w-full h-1.5 bg-slate-900 max-w-md mx-auto">
              <div className="h-1.5 bg-emerald-500 transition-all" style={{ width: `${progressPct}%` }} />
            </div>
          </div>
        )}

        {selectedLabId && isFailed && (
          <div className="border border-red-800/40 bg-red-950/10 p-8 text-center text-xs text-red-400 font-mono">
            PBO run failed: {pboRun.error || 'unknown error'}
          </div>
        )}

        {selectedLabId && results && pboRun.status === 'completed' && (
          <>
            <PBOVerdictCard
              pbo={results.pbo}
              nCandidates={results.nCandidates}
              nEvaluated={results.nEvaluated}
              nCombinations={results.nCombinations}
              insufficientData={results.insufficientData}
            />
            <div className="border border-slate-800 bg-slate-950 p-4">
              <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">
                Candidates ({results.nCandidates}, {results.method} search, full date range)
              </h4>
              <PBOCandidatesTable candidates={results.candidates} />
            </div>
            <div className="border border-dashed border-slate-800 p-3 text-[10px] text-slate-500 font-mono italic">
              CSCV subsampling ({results.nBlocks} blocks, {results.nCombinations?.toLocaleString()} train/test
              splits) runs entirely against each candidate's own already-persisted full-range
              trades — no extra backtests beyond the {results.nCandidates} candidates above. Not a
              walk-forward variant: see the Optimizer tab for sequential rolling/anchored
              re-optimization instead.
            </div>
          </>
        )}
      </div>
    </div>
  )
}
