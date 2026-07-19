import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Dices, Loader2 } from 'lucide-react'
import socket from '../../lib/socket'
import { useRunMonteCarlo, useSimulation } from '../../hooks/useLab'

// Plan 10 §4.4 ("Everywhere else") — the backtest report's compact MC
// summary strip: "MC p5/median/p95 final equity · P(ruin), fed by an
// auto-enqueued default-config MC when a backtest completes (cheap: <1s
// vectorized), deep-linking to the Lab for the full analysis. This is what
// the user currently believes the backtest page should show, made real."
//
// Reuses the already-shipped, already-tested MC job infra (Phase 1a/1b)
// completely unchanged — this component adds no new engine math, just a
// client-side auto-trigger + compact render.
//
// Idempotent by construction, not by a client-side "does one already exist?"
// check: `buildMonteCarloConfig({})` (default mode/runs/ruinThresholdPct) +
// `computeConfigHash(sourceJobId, config)` already short-circuits identical
// resubmissions server-side (Phase 1's own acceptance criterion — "re-
// submitting an identical config returns the cached doc"). So this component
// safely re-fires its mutation every time it mounts for the same
// `sourceJobId`; the server returns the cached completed doc instantly
// instead of re-queueing a duplicate job.
//
// Fails quietly (renders nothing) on error — this is a bonus strip, not the
// backtest report itself, and a failed default-config MC (e.g. too few
// trades to resample) shouldn't put an alarming red banner on an otherwise
// successful backtest.
export default function MCSummaryStrip({ sourceJobId, enabled }) {
  const queryClient = useQueryClient()
  const [labId, setLabId] = useState(null)
  const [failed, setFailed] = useState(false)
  const runMutation = useRunMonteCarlo()
  const firedFor = useRef(null)

  // Fire once per sourceJobId (not once ever) — a different backtest result
  // selected in the same page session needs its own auto-enqueued run.
  useEffect(() => {
    if (!enabled || !sourceJobId || firedFor.current === sourceJobId) return
    firedFor.current = sourceJobId
    setLabId(null)
    setFailed(false)
    runMutation.mutate(
      { sourceJobId },
      {
        onSuccess: (res) => setLabId(res.labId),
        onError: () => setFailed(true),
      }
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, sourceJobId])

  const { data: sim } = useSimulation(labId)

  // Socket.IO terminal events only (no progress bar) — a default-config MC
  // run completes in under a second, per Phase 1's own acceptance criterion;
  // the engine doesn't even call `publish_progress` for a job this short
  // (documented in 10_monte-carlo-strategy-lab.md's Phase 1 section), so a
  // percentage readout would just sit at 0% the whole time.
  useEffect(() => {
    if (!labId) return
    const handleComplete = (data) => {
      if (data.simId === labId) {
        queryClient.invalidateQueries({ queryKey: ['lab', 'simulations', labId] })
      }
    }
    const handleError = (data) => {
      if (data.simId === labId) setFailed(true)
    }
    socket.connect()
    socket.emit('join', `simulation:${labId}`)
    socket.on('simulation:complete', handleComplete)
    socket.on('simulation:error', handleError)
    return () => {
      socket.off('simulation:complete', handleComplete)
      socket.off('simulation:error', handleError)
    }
  }, [labId, queryClient])

  if (!enabled || failed) return null

  const isPending = !sim || ['queued', 'running'].includes(sim.status)

  if (isPending) {
    return (
      <div className="flex items-center gap-2 px-4 py-2 border-b border-slate-700/50 bg-slate-900/40 text-xs text-slate-400 font-mono">
        <Loader2 className="size-3.5 animate-spin text-emerald-400" />
        Running a default robustness check…
      </div>
    )
  }

  if (sim.status === 'failed' || !sim.results) return null

  const results = sim.results
  const pct = (key) => (results.finalEquityPercentiles ? (results.finalEquityPercentiles[key] - 1) * 100 : null)
  const p5 = pct('5')
  const median = pct('50')
  const p95 = pct('95')
  const ruinPct = results.ruinProbability != null ? parseFloat(results.ruinProbability) * 100 : null

  const signCls = (v) => (v == null ? 'text-slate-500' : v >= 0 ? 'text-emerald-400' : 'text-red-400')
  const ruinCls = ruinPct == null ? 'text-slate-500' : ruinPct >= 15 ? 'text-red-400' : ruinPct >= 5 ? 'text-amber-400' : 'text-emerald-400'

  return (
    <div className="flex flex-wrap items-center gap-4 px-4 py-2 border-b border-slate-700/50 bg-slate-900/40 text-xs font-mono">
      <span className="text-[10px] text-slate-500 uppercase tracking-wider">MC robustness (default run)</span>
      <span className="text-slate-400">
        p5 <b className={signCls(p5)}>{p5 != null ? `${p5.toFixed(1)}%` : '—'}</b>
      </span>
      <span className="text-slate-400">
        median <b className={signCls(median)}>{median != null ? `${median.toFixed(1)}%` : '—'}</b>
      </span>
      <span className="text-slate-400">
        p95 <b className={signCls(p95)}>{p95 != null ? `${p95.toFixed(1)}%` : '—'}</b>
      </span>
      <span className="text-slate-400">
        P(ruin) <b className={ruinCls}>{ruinPct != null ? `${ruinPct.toFixed(1)}%` : '—'}</b>
      </span>
      <Link
        to={`/lab?sourceJobId=${sourceJobId}`}
        className="ml-auto flex items-center gap-1 text-emerald-400 hover:text-emerald-300 transition-colors"
      >
        <Dices className="size-3.5" />
        Full analysis in Lab →
      </Link>
    </div>
  )
}
