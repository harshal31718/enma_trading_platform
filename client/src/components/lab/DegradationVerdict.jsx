// Plan 10 Phase 3a's headline overfitting signal: average OOS-Sharpe /
// IS-Sharpe ratio across folds. 1.0 = OOS performed as well as IS (no
// detectable overfitting); well below 1.0 = the strategy curve-fit to its
// training windows. This is NOT the plan's §2.2 Deflated Sharpe Ratio / PBO
// statistics — those are a separate, harder deliverable explicitly deferred
// (see 10_monte-carlo-strategy-lab.md's Phase 3a section for why) — this is
// a simpler, honest signal built only from numbers the engine already
// computes for real.
export default function DegradationVerdict({ avgDegradationRatio, nFoldsBuilt, mode, method }) {
  if (avgDegradationRatio == null) {
    return (
      <div className="border border-slate-800 bg-slate-950 p-4 text-xs font-mono text-slate-500 italic">
        No valid degradation ratio across folds (every fold either had a zero in-sample Sharpe or was skipped).
      </div>
    )
  }

  let color = '#34d399'
  let verdict = 'Low overfitting risk'
  if (avgDegradationRatio < 0.4) {
    color = '#f87171'
    verdict = 'High overfitting risk'
  } else if (avgDegradationRatio < 0.8) {
    color = '#fbbf24'
    verdict = 'Moderate overfitting risk'
  }

  return (
    <div className="border border-slate-800 bg-slate-950 p-4 flex items-center justify-between">
      <div>
        <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1">
          Average IS → OOS degradation ({nFoldsBuilt} {mode} folds
          {method === 'bayesian' ? ', Bayesian/TPE search' : ''})
        </h4>
        <p className="text-[10px] text-slate-500 font-mono">
          out-of-sample Sharpe ÷ in-sample Sharpe, averaged across folds — 1.0 = no degradation
        </p>
      </div>
      <div className="text-right shrink-0 ml-4">
        <div className="text-2xl font-mono font-bold" style={{ color }}>
          {avgDegradationRatio.toFixed(2)}
        </div>
        <div className="text-[10px] font-mono uppercase tracking-wider" style={{ color }}>
          {verdict}
        </div>
      </div>
    </div>
  )
}
