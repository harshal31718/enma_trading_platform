import {
  ResponsiveContainer,
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
} from 'recharts'

// Plan 10 Phase 2 §4.2.1 — equity fan chart. X axis is the (synthetic) trade
// sequence index, not wall-clock time — block-bootstrap paths don't map 1:1
// to the original candle timestamps (engine's own note in equityBands).
// `equityBands` values are equity multiples of starting capital (1.0 = flat);
// rendered here as % return so the P&L invariant (emerald-400/red-400) reads
// naturally against the zero line.
export default function FanChart({ equityBands }) {
  const { tradeIndices = [], p5, p25, p50, p75, p95 } = equityBands || {}

  if (!tradeIndices.length) {
    return (
      <div className="h-64 flex items-center justify-center border border-slate-800 bg-slate-950 text-slate-500 text-xs font-mono">
        No equity band data (zero resampled trades).
      </div>
    )
  }

  const toPct = (v) => (v - 1) * 100

  const data = tradeIndices.map((idx, i) => ({
    idx,
    p5: toPct(p5[i]),
    p25: toPct(p25[i]),
    p50: toPct(p50[i]),
    p75: toPct(p75[i]),
    p95: toPct(p95[i]),
    // Recharts stacked-band trick: draw p5→p95 and p25→p75 as offset+span areas
    outerSpan: toPct(p95[i]) - toPct(p5[i]),
    innerSpan: toPct(p75[i]) - toPct(p25[i]),
  }))

  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 10, right: 16, left: 8, bottom: 0 }}>
          <CartesianGrid stroke="#1f2937" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="idx"
            stroke="#4b5563"
            fontSize={10}
            tickLine={false}
            axisLine={false}
            label={{ value: 'Trade sequence #', position: 'insideBottom', offset: -2, fill: '#4b5563', fontSize: 10 }}
          />
          <YAxis
            stroke="#4b5563"
            fontSize={10}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => `${v.toFixed(0)}%`}
          />
          <ReferenceLine y={0} stroke="#4b5563" strokeDasharray="2 2" />
          <Tooltip
            contentStyle={{ backgroundColor: '#111827', borderColor: '#1f2937' }}
            labelStyle={{ color: '#9ca3af', fontSize: 11 }}
            labelFormatter={(v) => `Trade #${v}`}
            formatter={(val, name) => [`${val.toFixed(2)}%`, name]}
          />
          {/* p5-p95 band (wide, faint) */}
          <Area dataKey="p5" stackId="outer" stroke="none" fill="transparent" isAnimationActive={false} name="p5" />
          <Area dataKey="outerSpan" stackId="outer" stroke="none" fill="#34d399" fillOpacity={0.08} isAnimationActive={false} name="p5-p95 band" />
          {/* p25-p75 band (narrower, stronger) */}
          <Area dataKey="p25" stackId="inner" stroke="none" fill="transparent" isAnimationActive={false} name="p25" />
          <Area dataKey="innerSpan" stackId="inner" stroke="none" fill="#34d399" fillOpacity={0.18} isAnimationActive={false} name="p25-p75 band" />
          <Line type="monotone" dataKey="p50" stroke="#34d399" strokeWidth={2} dot={false} name="median" />
          <Line type="monotone" dataKey="p5" stroke="#f87171" strokeWidth={1} strokeDasharray="4 4" dot={false} opacity={0.6} name="p5 (worst 5%)" />
          <Line type="monotone" dataKey="p95" stroke="#4b5563" strokeWidth={1} strokeDasharray="4 4" dot={false} opacity={0.6} name="p95 (best 5%)" />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
