// Plan 10 Phase 2 §4.2.6 — verdict strip: point-estimate vs MC-p5 gap, in
// plain language ("your backtest's +43% has a 1-in-20 outcome of -12% under
// cost stress" is the plan's own example sentence).
export default function VerdictStrip({ pointEstimatePct, finalEquityPercentiles, mode }) {
  if (!finalEquityPercentiles || finalEquityPercentiles['5'] == null) return null

  const p5Pct = (finalEquityPercentiles['5'] - 1) * 100
  const gap = pointEstimatePct != null ? pointEstimatePct - p5Pct : null
  const modeLabel = mode === 'iid' ? 'i.i.d. resample' : 'block bootstrap'

  return (
    <div className="border border-amber-800/40 bg-amber-950/10 px-4 py-3 text-xs font-mono text-slate-200">
      {pointEstimatePct != null ? (
        <>
          This backtest's point estimate of{' '}
          <span className={pointEstimatePct >= 0 ? 'text-emerald-400 font-bold' : 'text-red-400 font-bold'}>
            {pointEstimatePct >= 0 ? '+' : ''}{pointEstimatePct.toFixed(1)}%
          </span>{' '}
          has a 1-in-20 outcome of{' '}
          <span className={p5Pct >= 0 ? 'text-emerald-400 font-bold' : 'text-red-400 font-bold'}>
            {p5Pct >= 0 ? '+' : ''}{p5Pct.toFixed(1)}%
          </span>{' '}
          under {modeLabel} resampling
          {gap != null && (
            <span className="text-slate-400"> (a {Math.abs(gap).toFixed(1)}pt fragility gap).</span>
          )}
        </>
      ) : (
        <>
          Worst 1-in-20 ({modeLabel}) outcome:{' '}
          <span className={p5Pct >= 0 ? 'text-emerald-400 font-bold' : 'text-red-400 font-bold'}>
            {p5Pct >= 0 ? '+' : ''}{p5Pct.toFixed(1)}%
          </span>
        </>
      )}
    </div>
  )
}
