// Plan 10 — PBO verdict card. Mirrors RuinCard.jsx's severity-card template (red/amber/emerald,
// big stat, explanatory footnote).
//
// Threshold reasoning (a judgment call, not from a specific citation — the CSCV paper itself
// doesn't prescribe a universal cutoff): PBO=50% means the in-sample-best candidate is no better
// than a coin flip at actually being the out-of-sample-best candidate — pure noise. <20% is
// comfortably better than chance; 20-50% is a real but not yet damning warning sign.
export default function PBOVerdictCard({ pbo, nCandidates, nEvaluated, nCombinations, insufficientData }) {
  if (insufficientData || pbo === null || pbo === undefined) {
    return (
      <div className="border border-slate-800 bg-slate-950 p-4 flex flex-col items-center justify-center text-center">
        <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">
          Probability of Backtest Overfitting
        </h4>
        <p className="text-xs text-slate-500 font-mono italic">
          Not enough OOS trade data in any train/test split to compute a PBO estimate — no
          fabricated number shown.
        </p>
      </div>
    )
  }

  const pct = pbo * 100
  let color = '#34d399'
  let severity = 'Low'
  if (pct >= 50) {
    color = '#f87171'
    severity = 'High — likely overfit'
  } else if (pct >= 20) {
    color = '#fbbf24'
    severity = 'Elevated'
  }

  return (
    <div className="border border-slate-800 bg-slate-950 p-4 flex flex-col items-center justify-center text-center">
      <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">
        Probability of Backtest Overfitting
      </h4>
      <div className="text-3xl font-mono font-bold" style={{ color }}>
        {pct.toFixed(1)}%
      </div>
      <div className="text-[10px] font-mono uppercase tracking-wider mt-1" style={{ color }}>
        {severity}
      </div>
      <p className="text-[10px] text-slate-500 font-mono mt-3">
        Fraction of {nEvaluated.toLocaleString()} evaluated train/test splits (of {nCombinations.toLocaleString()} total,
        {' '}{nCandidates} candidates) where the in-sample-best candidate ranked below the OOS median —
        50% = no better than chance at picking a genuinely robust strategy.
      </p>
    </div>
  )
}
