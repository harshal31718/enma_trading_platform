// Plan 7 Step 7.4 (CLI-1): extracted out of Backtest.jsx.
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table'
import { formatPct, formatSignedPct, formatPnl } from '@/utils/formatters'

export default function PerformanceTable({ bySide }) {
  if (!bySide) return null;

  const rows = [
    { label: 'Net Profit', key: 'netProfit', format: (val, r) => `${formatPnl(val).value} (${formatSignedPct(r.netProfitPct)})`, isPnl: true },
    { label: 'Gross Profit', key: 'grossProfit', format: (val) => formatPnl(val).value, isPnl: true },
    { label: 'Gross Loss', key: 'grossLoss', format: (val) => formatPnl(val).value, isPnl: true },
    { label: 'Profit Factor', key: 'profitFactor', format: (val) => parseFloat(val).toFixed(2), highlightPF: true },
    { label: 'Total Trades', key: 'totalTrades', format: (val) => val },
    { label: 'Winning Trades', key: 'winningTrades', format: (val) => val },
    { label: 'Losing Trades', key: 'losingTrades', format: (val) => val },
    { label: 'Win Rate (% Profitable)', key: 'winRate', format: (val) => formatPct(parseFloat(val) * 100) },
    { label: 'Expectancy (Avg P&L)', key: 'expectancy', format: (val) => formatPnl(val).value, isPnl: true },
    { label: 'Avg Win', key: 'averageWin', format: (val) => formatPnl(val).value, isPnl: true },
    { label: 'Avg Loss', key: 'averageLoss', format: (val) => formatPnl(val).value, isPnl: true },
    { label: 'Payoff Ratio (Win/Loss)', key: 'payoffRatio', format: (val) => parseFloat(val).toFixed(2) },
    {
      label: 'Avg Holding Period', key: 'averageHoldingPeriod', format: (val) => {
        const secs = parseInt(val)
        if (secs >= 3600) return `${(secs / 3600).toFixed(1)}h`
        if (secs >= 60) return `${(secs / 60).toFixed(1)}m`
        return `${secs}s`
      }
    },
    { label: 'Max Consecutive Wins', key: 'maxConsecutiveWins', format: (val) => val },
    { label: 'Max Consecutive Losses', key: 'maxConsecutiveLosses', format: (val) => val },
  ]

  const getPnlClass = (val) => {
    const n = parseFloat(val)
    if (n > 0) return 'text-emerald-400 font-semibold'
    if (n < 0) return 'text-red-400 font-semibold'
    return 'text-gray-300'
  }

  const getPFClass = (val) => {
    const n = parseFloat(val)
    if (n >= 1) return 'text-emerald-400 font-semibold'
    if (n > 0) return 'text-red-400 font-semibold'
    return 'text-gray-300'
  }

  return (
    <div className="h-full flex flex-col bg-title-bg border border-slate-700/50 overflow-hidden">
      <Table wrapperClassName="flex-1 overflow-y-auto">
        <TableHeader className="sticky top-0 z-10">
          <TableRow className="h-11 shrink-0 bg-title-bg title-fade border-b border-slate-700/50">
            <TableHead className="w-[250px]">Metric</TableHead>
            <TableHead>All Trades</TableHead>
            <TableHead>Long Trades</TableHead>
            <TableHead>Short Trades</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => {
            const allVal = bySide.all?.[row.key] ?? '-'
            const longVal = bySide.long?.[row.key] ?? '-'
            const shortVal = bySide.short?.[row.key] ?? '-'

            return (
              <TableRow key={row.key}>
                <TableCell className="font-medium text-gray-300">{row.label}</TableCell>
                <TableCell className={row.isPnl ? getPnlClass(allVal) : row.highlightPF ? getPFClass(allVal) : 'text-gray-400 font-mono text-sm'}>
                  {allVal !== '-' ? row.format(allVal, bySide.all) : '-'}
                </TableCell>
                <TableCell className={row.isPnl ? getPnlClass(longVal) : row.highlightPF ? getPFClass(longVal) : 'text-gray-400 font-mono text-sm'}>
                  {longVal !== '-' ? row.format(longVal, bySide.long) : '-'}
                </TableCell>
                <TableCell className={row.isPnl ? getPnlClass(shortVal) : row.highlightPF ? getPFClass(shortVal) : 'text-gray-400 font-mono text-sm'}>
                  {shortVal !== '-' ? row.format(shortVal, bySide.short) : '-'}
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}
