import { useState, useEffect } from 'react'
import { useBacktestsList } from '../../hooks/useBacktest'

// Plan 10 Phase 2 §4.1/§4.3.7 — MC run wizard (left rail, "New Run ▸").
// Only the two Phase-1-shipped modes (block/iid) are offered — skip-trades/
// cost-stress/start-date modes (§2.1 items 3-5) aren't implemented by the
// engine yet (Phase 1's own documented scope decision); add a mode picker
// entry here when they land.
export default function RunWizard({ initialSourceJobId, onRun, submitting }) {
  const { data: listData, isLoading } = useBacktestsList(1, 50, { status: 'completed' })
  const backtests = listData?.backtests || []

  const [sourceJobId, setSourceJobId] = useState(initialSourceJobId || '')
  const [mode, setMode] = useState('block')
  const [runs, setRuns] = useState(5000)
  const [blockLen, setBlockLen] = useState('')
  const [ruinThresholdPct, setRuinThresholdPct] = useState(30)

  useEffect(() => {
    if (initialSourceJobId) setSourceJobId(initialSourceJobId)
  }, [initialSourceJobId])

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!sourceJobId) return
    onRun({
      sourceJobId,
      mode,
      runs: Number(runs),
      blockLen: blockLen === '' ? undefined : Number(blockLen),
      ruinThresholdPct: Number(ruinThresholdPct),
    })
  }

  return (
    <form onSubmit={handleSubmit} className="border border-slate-800 bg-slate-950 p-4 space-y-3">
      <h3 className="text-[10px] font-bold uppercase tracking-wider text-slate-400">New Run</h3>

      <div>
        <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block mb-1">Source backtest</label>
        <select
          className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200"
          value={sourceJobId}
          onChange={(e) => setSourceJobId(e.target.value)}
          disabled={isLoading}
        >
          <option value="">-- Select completed backtest --</option>
          {backtests.map((b) => (
            <option key={b.jobId} value={b.jobId}>
              {b.strategyName} · {b.symbol} ({new Date(b.createdAt).toLocaleDateString()})
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block mb-1">Resampling mode</label>
        <div className="flex gap-2 text-xs font-mono">
          <button
            type="button"
            onClick={() => setMode('block')}
            className={`flex-1 py-1.5 border ${mode === 'block' ? 'border-emerald-500 text-emerald-400 bg-emerald-950/20' : 'border-slate-700 text-slate-400'}`}
          >
            Block bootstrap
          </button>
          <button
            type="button"
            onClick={() => setMode('iid')}
            className={`flex-1 py-1.5 border ${mode === 'iid' ? 'border-emerald-500 text-emerald-400 bg-emerald-950/20' : 'border-slate-700 text-slate-400'}`}
          >
            i.i.d. resample
          </button>
        </div>
        <p className="text-[9px] text-slate-600 mt-1 italic">
          Block preserves win/loss clustering (default, recommended). i.i.d. is wider/less realistic — shown for comparison.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block mb-1">Runs</label>
          <input
            type="number"
            min={1}
            max={20000}
            className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200"
            value={runs}
            onChange={(e) => setRuns(e.target.value)}
          />
        </div>
        <div>
          <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block mb-1">Block length</label>
          <input
            type="number"
            min={1}
            placeholder="auto (√N)"
            className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200 placeholder-slate-600"
            value={blockLen}
            onChange={(e) => setBlockLen(e.target.value)}
            disabled={mode !== 'block'}
          />
        </div>
      </div>

      <div>
        <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block mb-1">Ruin threshold (% drawdown)</label>
        <input
          type="number"
          min={1}
          max={100}
          className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200"
          value={ruinThresholdPct}
          onChange={(e) => setRuinThresholdPct(e.target.value)}
        />
      </div>

      <button
        type="submit"
        disabled={!sourceJobId || submitting}
        className="w-full bg-emerald-900/30 hover:bg-emerald-900/50 active:bg-emerald-900/60 disabled:opacity-40 disabled:cursor-not-allowed text-emerald-400 border border-emerald-800 py-2 px-4 font-mono text-xs uppercase tracking-wider"
      >
        {submitting ? 'Queuing…' : 'Run Robustness Check'}
      </button>
    </form>
  )
}
