// Plan 10 Phase 2 §4.2.4 — ruin card. red/amber/emerald severity coloring,
// ruin definition printed underneath (per the plan's own text).
export default function RuinCard({ ruinProbability, ruinThresholdPct }) {
  const prob = parseFloat(ruinProbability) * 100

  let color = '#34d399'
  let severity = 'Low'
  if (prob >= 15) {
    color = '#f87171'
    severity = 'High'
  } else if (prob >= 5) {
    color = '#fbbf24'
    severity = 'Elevated'
  }

  return (
    <div className="border border-slate-800 bg-slate-950 p-4 flex flex-col items-center justify-center text-center">
      <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">Probability of Ruin</h4>
      <div className="text-3xl font-mono font-bold" style={{ color }}>
        {prob.toFixed(1)}%
      </div>
      <div className="text-[10px] font-mono uppercase tracking-wider mt-1" style={{ color }}>
        {severity} risk
      </div>
      <p className="text-[10px] text-slate-500 font-mono mt-3">
        Ruin = max drawdown ≥ {ruinThresholdPct}% of starting capital, across all resampled runs.
      </p>
    </div>
  )
}
