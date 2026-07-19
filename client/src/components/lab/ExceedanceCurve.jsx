import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
} from 'recharts'

// Plan 10 Phase 2 §4.2.3 — P(max drawdown > x) exceedance curve, replacing
// the legacy 5-fixed-bucket drawdownDistribution. `drawdownExceedance` is
// finer-grained (5..50 step 5, see engine EXCEEDANCE_BUCKETS). The user's
// ruin threshold (ruinThresholdPct from the run's own config) is drawn as a
// reference line rather than a truly draggable marker — dragging would imply
// live recompute, which isn't wired (the plan calls this "draggable" as an
// interaction goal; here it re-runs are the mechanism to explore a different
// threshold, done via the wizard's own ruinThresholdPct field).
export default function ExceedanceCurve({ drawdownExceedance, ruinThresholdPct }) {
  if (!drawdownExceedance?.length) {
    return (
      <div className="h-56 flex items-center justify-center border border-slate-800 bg-slate-950 text-slate-500 text-xs font-mono">
        No exceedance data (zero resampled trades).
      </div>
    )
  }

  const data = drawdownExceedance.map((d) => ({
    dd: parseFloat(d.drawdownPct),
    prob: parseFloat(d.probability) * 100,
  }))

  return (
    <div className="h-56 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 10, right: 16, left: 8, bottom: 0 }}>
          <defs>
            <linearGradient id="exceedanceGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#f87171" stopOpacity={0.35} />
              <stop offset="100%" stopColor="#f87171" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#1f2937" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="dd"
            stroke="#4b5563"
            fontSize={10}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => `${v}%`}
            label={{ value: 'Drawdown threshold', position: 'insideBottom', offset: -2, fill: '#4b5563', fontSize: 10 }}
          />
          <YAxis
            stroke="#4b5563"
            fontSize={10}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => `${v}%`}
            domain={[0, 100]}
          />
          {ruinThresholdPct != null && (
            <ReferenceLine
              x={ruinThresholdPct}
              stroke="#fbbf24"
              strokeDasharray="4 4"
              label={{ value: `ruin @ ${ruinThresholdPct}%`, position: 'top', fill: '#fbbf24', fontSize: 10 }}
            />
          )}
          <Tooltip
            contentStyle={{ backgroundColor: '#111827', borderColor: '#1f2937' }}
            labelStyle={{ color: '#9ca3af', fontSize: 11 }}
            labelFormatter={(v) => `P(DD > ${v}%)`}
            formatter={(val) => [`${val.toFixed(1)}%`, 'probability']}
          />
          <Area type="monotone" dataKey="prob" stroke="#f87171" fill="url(#exceedanceGradient)" strokeWidth={2} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
