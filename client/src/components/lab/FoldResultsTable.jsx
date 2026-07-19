// Plan 10 Phase 3c — per-fold walk-forward results. This is NOT the plan's
// §4.3.1 "trials table" (every combo evaluated, IS/OOS/DSR/rank per row) —
// this table shows one row per fold. See TrialsExplorer.jsx (Phase 3d,
// shipped 2026-07-19) for the per-combo trials table + 2-param loss heatmap.
// DSR column added Phase 3e — the winning combo's Deflated Sharpe Ratio,
// deflated against the pool of every trial scored on that fold's train
// window (services/stats.py). "—" when there isn't enough data to say
// anything (fold.dsr.insufficientData), not a fabricated confident number.
export default function FoldResultsTable({ folds }) {
  if (!folds?.length) return null

  return (
    <div className="border border-slate-800 bg-slate-950 overflow-x-auto">
      <table className="w-full text-xs font-mono text-left min-w-[860px]">
        <thead>
          <tr className="border-b border-slate-800 text-[10px] text-slate-400 uppercase tracking-wider">
            <th className="p-2">Fold</th>
            <th className="p-2">Train range</th>
            <th className="p-2">Test range</th>
            <th className="p-2">Best params</th>
            <th className="p-2 text-right">IS Sharpe</th>
            <th className="p-2 text-right">OOS Sharpe</th>
            <th className="p-2 text-right">Degradation</th>
            <th className="p-2 text-right">OOS trades</th>
            <th className="p-2 text-right" title="Deflated Sharpe Ratio — probability the winning combo's edge is genuine, after correcting for having picked the best of N trials">DSR</th>
          </tr>
        </thead>
        <tbody>
          {folds.map((f) => {
            if (f.skipped) {
              return (
                <tr key={f.fold} className="border-b border-slate-900/60 text-slate-600 italic">
                  <td className="p-2">{f.fold}</td>
                  <td className="p-2" colSpan={8}>Skipped — {f.reason}</td>
                </tr>
              )
            }
            const isSharpe = parseFloat(f.isMetrics?.sharpeRatio ?? 0)
            const oosSharpe = parseFloat(f.oosMetrics?.sharpeRatio ?? 0)
            const degradation = f.degradationRatio
            const degradationColor = degradation == null
              ? 'text-slate-500'
              : degradation >= 0.8 ? 'text-emerald-400' : degradation >= 0.4 ? 'text-amber-400' : 'text-red-400'
            const dsr = f.dsr
            const dsrColor = !dsr || dsr.insufficientData
              ? 'text-slate-500'
              : dsr.dsr >= 0.95 ? 'text-emerald-400' : dsr.dsr >= 0.8 ? 'text-amber-400' : 'text-red-400'
            return (
              <tr key={f.fold} className="border-b border-slate-900/60 hover:bg-slate-900/40">
                <td className="p-2 text-slate-300 font-bold">{f.fold}</td>
                <td className="p-2 text-slate-500 whitespace-nowrap">
                  {new Date(f.trainRange[0]).toLocaleDateString()} – {new Date(f.trainRange[1]).toLocaleDateString()}
                </td>
                <td className="p-2 text-slate-500 whitespace-nowrap">
                  {new Date(f.testRange[0]).toLocaleDateString()} – {new Date(f.testRange[1]).toLocaleDateString()}
                </td>
                <td className="p-2 text-slate-300">
                  {Object.entries(f.bestParams || {}).map(([k, v]) => `${k}=${v}`).join(', ')}
                </td>
                <td className="p-2 text-right text-slate-300">{isSharpe.toFixed(2)}</td>
                <td className="p-2 text-right text-slate-300">{oosSharpe.toFixed(2)}</td>
                <td className={`p-2 text-right font-bold ${degradationColor}`}>
                  {degradation != null ? degradation.toFixed(2) : '—'}
                </td>
                <td className="p-2 text-right text-slate-400">{f.oosTradeCount}</td>
                <td className={`p-2 text-right font-bold ${dsrColor}`}>
                  {!dsr || dsr.insufficientData ? '—' : `${(dsr.dsr * 100).toFixed(1)}%`}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
