// Condensed backtest-metrics strip. Replaces the 8 large StatCards (each
// min-h-96px, icon + subtext) with a single tight row — same 8 metrics, no
// dead space. Design system: gap-0, border separators, no rounded corners.

function pct(value) {
  return `${(parseFloat(value) * 100).toFixed(0)}%`
}

function signed(value, decimals = 2) {
  const v = parseFloat(value)
  if (Number.isNaN(v)) return '0.00'
  return `${v >= 0 ? '+' : ''}${v.toFixed(decimals)}`
}

function Cell({ label, value, className = 'text-gray-100' }) {
  return (
    <div className="px-4 py-3 border-r border-b border-slate-700/50 last:border-r-0">
      <div className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold truncate">{label}</div>
      <div className={`mt-1 text-base font-mono tabular-nums font-semibold truncate ${className}`}>{value}</div>
    </div>
  )
}

export default function BacktestKpiStrip({ stats }) {
  const drawdown = parseFloat(stats.worstDrawdown)
  const expectancy = parseFloat(stats.avgExpectancy)

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-8 gap-0 border-t border-slate-700/50">
      <Cell label="Total Runs" value={stats.totalRuns} />
      <Cell label="Best Strategy" value={stats.bestStrategy} />
      <Cell label="Avg Win Rate" value={pct(stats.averageWinRate)} />
      <Cell label="Profit Factor" value={parseFloat(stats.avgProfitFactor).toFixed(2)} />
      <Cell label="Avg Sharpe" value={parseFloat(stats.avgSharpe).toFixed(2)} />
      <Cell label="Avg Sortino" value={parseFloat(stats.avgSortino).toFixed(2)} />
      <Cell
        label="Max Drawdown"
        value={`${drawdown.toFixed(2)}%`}
        className={drawdown > 0 ? 'text-red-400' : 'text-gray-100'}
      />
      <Cell
        label="Expectancy"
        value={signed(stats.avgExpectancy)}
        className={expectancy >= 0 ? 'text-emerald-400' : 'text-red-400'}
      />
    </div>
  )
}
