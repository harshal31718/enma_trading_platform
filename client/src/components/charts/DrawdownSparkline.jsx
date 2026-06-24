import { ResponsiveContainer, AreaChart, Area } from 'recharts'

/**
 * Minimal drawdown sparkline. Derives drawdown client-side from an
 * equity curve (running-max drawdown as a percentage).
 *
 * Props:
 *   data: equityCurve array — each entry { timestamp, balance }
 *
 * Fill red-400/20, stroke red-400.
 */
export default function DrawdownSparkline({ data = [] }) {
  if (!data || data.length === 0) {
    return (
      <div className="h-[90px] flex items-center justify-center border border-slate-700/50 bg-title-bg text-slate-500 text-xs">
        No drawdown data
      </div>
    )
  }

  let runningMax = -Infinity
  const points = data.map((d) => {
    const balance = parseFloat(d.balance)
    if (balance > runningMax) runningMax = balance
    const ddPct = runningMax > 0 ? ((balance - runningMax) / runningMax) * 100 : 0
    return { value: parseFloat(ddPct.toFixed(2)) }
  })

  return (
    <div className="h-[90px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={points} margin={{ top: 4, right: 4, left: 4, bottom: 4 }}>
          <Area
            type="monotone"
            dataKey="value"
            stroke="#f87171"
            fill="#f87171"
            fillOpacity={0.2}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
