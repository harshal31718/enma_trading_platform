import { ResponsiveContainer, LineChart, Line } from 'recharts'

/**
 * Minimal equity sparkline. Pure visual — no axes, no tooltip, no grid.
 *
 * Props:
 *   data: equityCurve array from backtestResult — each entry { timestamp, balance }
 *
 * Line color flips emerald-400 / red-400 based on the final vs initial balance.
 */
export default function EquitySparkline({ data = [] }) {
  if (!data || data.length === 0) {
    return (
      <div className="h-[90px] flex items-center justify-center border border-slate-700/50 bg-title-bg text-slate-400 text-xs">
        No equity data
      </div>
    )
  }

  const points = data.map((d) => ({ value: parseFloat(d.balance) }))
  const start = points[0].value
  const end = points[points.length - 1].value
  const stroke = end >= start ? '#34d399' : '#f87171' // emerald-400 / red-400

  return (
    <div className="h-[90px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 4, right: 4, left: 4, bottom: 4 }}>
          <Line
            type="monotone"
            dataKey="value"
            stroke={stroke}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
