// Plan 10 Phase 2 §4.2.2/§4.2.3 — final-equity and max-drawdown "histograms".
//
// Scope decision (this session): the engine's run_lab_simulation only persists
// PERCENTILES of the per-run final-equity / max-drawdown distributions
// (finalEquityPercentiles/maxDrawdownPercentiles — p5/p25/p50/p75/p95), not
// the raw per-run samples or precomputed bins. A true histogram needs the raw
// array (n_runs values, up to 20,000), which today is discarded after the
// percentiles are computed (engine/services/monte_carlo.py). Building real
// histograms means the engine additionally persisting binned counts — a small
// but real backend change, deferred rather than done silently here. This
// component renders the five percentiles as a labeled box/whisker-style
// spread instead, which is honest about what data actually exists and still
// answers "how wide is the distribution" at a glance.
export default function PercentileSpread({ title, percentiles, unit = '%', capitalMarker = null, positiveIsGood = true }) {
  if (!percentiles || Object.keys(percentiles).length === 0) {
    return (
      <div className="border border-slate-800 bg-slate-950 p-4 text-xs font-mono text-slate-500">
        No percentile data (zero resampled trades).
      </div>
    )
  }

  const p5 = percentiles['5']
  const p25 = percentiles['25']
  const p50 = percentiles['50']
  const p75 = percentiles['75']
  const p95 = percentiles['95']

  const min = Math.min(p5, 0)
  const max = Math.max(p95, 0)
  const range = max - min || 1
  const pct = (v) => ((v - min) / range) * 100

  const colorFor = (v) => {
    const good = positiveIsGood ? v >= 0 : v <= 0
    return good ? '#34d399' : '#f87171'
  }

  return (
    <div className="border border-slate-800 bg-slate-950 p-4">
      <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1">{title}</h4>
      <p className="text-[9px] text-slate-600 mb-3 italic">Percentile spread (p5–p95) — raw per-run distribution not persisted</p>

      <div className="relative h-8 bg-slate-900/60 mb-2">
        {/* p5-p95 whisker */}
        <div
          className="absolute top-1/2 -translate-y-1/2 h-0.5 bg-slate-600"
          style={{ left: `${pct(p5)}%`, width: `${pct(p95) - pct(p5)}%` }}
        />
        {/* p25-p75 box */}
        <div
          className="absolute top-1 bottom-1 bg-slate-700/70 border border-slate-600"
          style={{ left: `${pct(p25)}%`, width: `${Math.max(pct(p75) - pct(p25), 0.5)}%` }}
        />
        {/* median marker */}
        <div
          className="absolute top-0 bottom-0 w-0.5"
          style={{ left: `${pct(p50)}%`, backgroundColor: colorFor(p50) }}
        />
        {/* zero line */}
        {min < 0 && max > 0 && (
          <div className="absolute top-0 bottom-0 w-px bg-slate-500/50" style={{ left: `${pct(0)}%` }} />
        )}
      </div>

      <div className="grid grid-cols-5 gap-1 text-[10px] font-mono text-center">
        {[['p5', p5], ['p25', p25], ['p50', p50], ['p75', p75], ['p95', p95]].map(([label, v]) => (
          <div key={label}>
            <div className="text-slate-500">{label}</div>
            <div className="font-bold" style={{ color: colorFor(v) }}>
              {v >= 0 ? '+' : ''}{v.toFixed(2)}{unit}
            </div>
          </div>
        ))}
      </div>
      {capitalMarker != null && (
        <p className="text-[9px] text-slate-500 mt-2">P(loss) region shaded left of the zero line above.</p>
      )}
    </div>
  )
}
