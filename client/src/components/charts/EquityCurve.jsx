import {
  ResponsiveContainer,
  LineChart,
  Line,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from 'recharts'

const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

function fmtTick(iso) {
  const d = new Date(iso)
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} '${String(d.getUTCFullYear()).slice(2)}`
}

function fmtTooltipLabel(iso) {
  const d = new Date(iso)
  const hh = String(d.getUTCHours()).padStart(2, '0')
  const mm = String(d.getUTCMinutes()).padStart(2, '0')
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} '${String(d.getUTCFullYear()).slice(2)}  ${hh}:${mm}`
}

// Pick ~6 evenly-spaced indices to use as explicit X-axis ticks
function buildTicks(timestamps, count = 6) {
  if (timestamps.length <= count) return timestamps
  const step = Math.floor((timestamps.length - 1) / (count - 1))
  return Array.from({ length: count }, (_, i) =>
    i === count - 1 ? timestamps[timestamps.length - 1] : timestamps[i * step]
  )
}

export default function EquityCurve({ data = [], startingCapital, buyHoldReturnPct = 0 }) {
  if (!data || data.length === 0) {
    return (
      <div className="h-64 flex items-center justify-center border border-gray-800 rounded bg-gray-950 text-gray-500">
        No equity curve data available.
      </div>
    )
  }

  const startCap = startingCapital ? parseFloat(startingCapital) : (data.length > 0 ? parseFloat(data[0].balance) : 10000)
  const buyHoldPct = parseFloat(buyHoldReturnPct || 0)

  // Format data and calculate running drawdown
  let maxBalance = -1e9
  const chartData = data.map((d, index) => {
    const balance = parseFloat(d.balance)
    if (balance > maxBalance) maxBalance = balance
    const drawdownPct = maxBalance > 0 ? ((balance - maxBalance) / maxBalance) * 100 : 0
    
    // Linear approximation of Buy & Hold path
    const progress = data.length > 1 ? index / (data.length - 1) : 0
    const buyHold = startCap * (1 + (buyHoldPct / 100) * progress)

    return {
      time: d.timestamp,   // keep raw ISO — tick/tooltip formatters handle display
      balance,
      buyHold: parseFloat(buyHold.toFixed(2)),
      drawdown: parseFloat(drawdownPct.toFixed(2)),
    }
  })

  const ticks = buildTicks(chartData.map((d) => d.time))

  return (
    <div className="space-y-6">
      {/* Equity Line Chart */}
      <div>
        <h4 className="text-gray-400 text-xs font-semibold uppercase tracking-wider mb-2">Equity Growth vs Buy & Hold Benchmark</h4>
        <div className="h-[260px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
              <CartesianGrid stroke="#1f2937" strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="time"
                stroke="#4b5563"
                fontSize={10}
                tickLine={false}
                axisLine={false}
                ticks={ticks}
                tickFormatter={fmtTick}
              />
              <YAxis
                stroke="#4b5563"
                fontSize={10}
                tickLine={false}
                axisLine={false}
                domain={['auto', 'auto']}
                tickFormatter={(val) => `$${val.toLocaleString()}`}
              />
              <Tooltip
                contentStyle={{ backgroundColor: '#111827', borderColor: '#1f2937' }}
                labelStyle={{ color: '#9ca3af', fontSize: 11 }}
                labelFormatter={fmtTooltipLabel}
                formatter={(val, name) => {
                  const formatted = `$${parseFloat(val).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                  if (name === 'balance') return [formatted, 'Strategy Balance']
                  if (name === 'buyHold') return [formatted, 'Buy & Hold']
                  return [formatted, name]
                }}
              />
              <Line
                type="monotone"
                dataKey="balance"
                name="balance"
                stroke="#10b981"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4 }}
              />
              <Line
                type="monotone"
                dataKey="buyHold"
                name="buyHold"
                stroke="#6b7280"
                strokeDasharray="4 4"
                strokeWidth={1.5}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Drawdown Area Chart */}
      <div>
        <h4 className="text-gray-400 text-xs font-semibold uppercase tracking-wider mb-2">Relative Drawdown (%)</h4>
        <div className="h-[120px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
              <CartesianGrid stroke="#1f2937" strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="time"
                stroke="#4b5563"
                fontSize={10}
                tickLine={false}
                axisLine={false}
                ticks={ticks}
                tickFormatter={fmtTick}
                hide
              />
              <YAxis
                stroke="#4b5563"
                fontSize={10}
                tickLine={false}
                axisLine={false}
                domain={['auto', 0]}
                tickFormatter={(val) => `${val}%`}
              />
              <Tooltip
                contentStyle={{ backgroundColor: '#111827', borderColor: '#1f2937' }}
                labelStyle={{ color: '#9ca3af', fontSize: 11 }}
                itemStyle={{ color: '#f87171', fontSize: 12 }}
                labelFormatter={fmtTooltipLabel}
                formatter={(val) => [`${val}%`, 'Drawdown']}
              />
              <Area
                type="monotone"
                dataKey="drawdown"
                stroke="#ef4444"
                fill="#b91c1c"
                fillOpacity={0.25}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}
