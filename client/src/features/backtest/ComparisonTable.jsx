// Plan 7 Step 7.4 (CLI-1): extracted out of Backtest.jsx.
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table'
import { formatPrice, formatPct, formatSignedPct, formatPnl, formatIsoDate } from '@/utils/formatters'

export default function ComparisonTable({ results }) {
  const metricRows = [
    { label: 'Net Profit', getValue: (r) => formatPrice(r.metrics?.netProfit ?? 0), isPnl: true },
    { label: 'Net Profit %', getValue: (r) => formatSignedPct(r.metrics?.netProfitPct ?? 0), isPnl: true },
    { label: 'Win Rate', getValue: (r) => formatPct((parseFloat(r.metrics?.winRate || 0) || 0) * 100) },
    { label: 'Profit Factor', getValue: (r) => (r.metrics?.profitFactor ? parseFloat(r.metrics.profitFactor).toFixed(2) : '-'), isPF: true },
    { label: 'Max Drawdown', getValue: (r) => formatPct(parseFloat(r.metrics?.maxDrawdown || 0)), isLoss: true },
    { label: 'Sharpe', getValue: (r) => parseFloat(r.metrics?.sharpeRatio || 0).toFixed(2) },
    { label: 'Sortino', getValue: (r) => parseFloat(r.metrics?.sortinoRatio || 0).toFixed(2) },
    { label: 'Calmar', getValue: (r) => parseFloat(r.metrics?.calmarRatio || 0).toFixed(2) },
    { label: 'Total Trades', getValue: (r) => r.metrics?.totalTrades ?? '-' },
    { label: 'Win / Loss', getValue: (r) => `${r.metrics?.winningTrades ?? '-'} / ${r.metrics?.losingTrades ?? '-'}` },
    { label: 'Expectancy', getValue: (r) => (r.metrics?.expectancy != null ? formatPnl(r.metrics.expectancy).value : '-'), isPnl: true },
    { label: 'Capital', getValue: (r) => formatPrice(r.capital) },
    { label: 'Leverage', getValue: (r) => `${r.leverage}x` },
    { label: 'Fee Rate', getValue: (r) => `${((r.feeRate || 0) * 100).toFixed(2)}%` },
    { label: 'Date Range', getValue: (r) => `${formatIsoDate(r.startDate)} → ${formatIsoDate(r.endDate)}` },
  ]

  const getValClass = (row, r) => {
    const raw = row.getValue(r)
    const n = parseFloat(raw)
    if (row.isPnl) return n > 0 ? 'text-emerald-400' : n < 0 ? 'text-red-400' : 'text-gray-300'
    if (row.isLoss) return 'text-red-400'
    if (row.isPF) return n >= 1 ? 'text-emerald-400' : 'text-red-400'
    return 'text-gray-300'
  }

  return (
    <div className="flex-1 flex flex-col rounded-lg border-x-0 border-t-0 border-b border-gray-800 overflow-hidden bg-title-bg">
        <Table wrapperClassName="flex-1 overflow-y-auto">
          <TableHeader className="sticky top-0 z-10">
            <TableRow className="h-11 shrink-0 bg-title-bg title-fade border-b border-slate-700/50">
              <TableHead className="w-[180px] text-gray-400 font-medium text-xs">Metric</TableHead>
              {results.map((r) => (
                <TableHead key={r.jobId} className="text-gray-200 font-semibold text-xs">
                  <div className="truncate max-w-[140px]">{r.strategyName}</div>
                  <div className="text-[10px] text-gray-500 font-normal">{r.symbol} · {r.timeframe}</div>
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {metricRows.map((row, idx) => (
              <TableRow key={row.label}>
                <TableCell className="text-gray-400 text-xs font-medium">{row.label}</TableCell>
                {results.map((r) => (
                  <TableCell key={`${r.jobId}-${row.label}`} className={`font-mono text-xs font-semibold ${getValClass(row, r)}`}>
                    {row.getValue(r)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
    </div>
  )
}
