// Plan 7 Step 7.4 (CLI-1): extracted out of Backtest.jsx.
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Pagination } from '@/components/ui/pagination'
import { formatQty, formatPrice, formatSignedPct, formatPnl } from '@/utils/formatters'

export default function TradesTab({ tradesData, tradePage, setTradePage, tradesPerPage }) {
  return (
    <div className="bg-title-bg border border-slate-700/50 overflow-hidden flex-1 flex flex-col">
      {tradesData?.trades && tradesData.trades.length > 0 ? (() => {
        const totalTrades = tradesData.pagination.total
        const totalPages = tradesData.pagination.totalPages
        const pageTrades = tradesData.trades

        return (
          <>
            <Table wrapperClassName="flex-1 overflow-y-auto">
              <TableHeader className="sticky top-0 z-10">
                <TableRow className="h-11 shrink-0 bg-title-bg title-fade border-b border-slate-700/50">
                  <TableHead>Symbol</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Qty</TableHead>
                  <TableHead>Entry Price</TableHead>
                  <TableHead>Exit Price</TableHead>
                  <TableHead>Entry Time</TableHead>
                  <TableHead>Run-up (MFE)</TableHead>
                  <TableHead>Drawdown (MAE)</TableHead>
                  <TableHead>Bars</TableHead>
                  <TableHead>Reason</TableHead>
                  <TableHead className="text-right">Net P&L</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pageTrades.map((tr) => {
                  const pnl = formatPnl(tr.pnl)
                  const runUp = tr.runUpPct ? `${tr.runUpPct}%` : '-'
                  const drawdown = tr.drawdownPct ? `${tr.drawdownPct}%` : '-'
                  const bars = tr.barsHeld ?? '-'

                  return (
                    <TableRow key={tr.id}>
                      <TableCell className="font-mono text-xs text-gray-300">
                        {tr.symbol || '-'}
                      </TableCell>
                      <TableCell>
                        <Badge variant={tr.type === 'long' ? 'profit' : 'destructive'}>
                          {tr.type.toUpperCase()}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-mono text-xs">{formatQty(tr.qty)}</TableCell>
                      <TableCell className="font-mono text-xs">{formatPrice(tr.entryPrice)}</TableCell>
                      <TableCell className="font-mono text-xs">{formatPrice(tr.exitPrice)}</TableCell>
                      <TableCell className="text-slate-400 text-xs font-mono tabular-nums">
                        {new Date(tr.entryAt).toLocaleDateString('en-US', {
                          month: 'short', day: 'numeric',
                          hour: '2-digit', minute: '2-digit',
                          timeZone: 'UTC',
                        })}
                      </TableCell>
                      <TableCell className="font-mono text-xs text-emerald-400">
                        {runUp}
                      </TableCell>
                      <TableCell className="font-mono text-xs text-red-400">
                        {drawdown}
                      </TableCell>
                      <TableCell className="font-mono text-xs text-gray-400">
                        {bars}
                      </TableCell>
                      <TableCell>
                        <span className="text-xs capitalize text-gray-300">
                          {tr.exitReason ? tr.exitReason.replace('_', ' ') : '-'}
                        </span>
                      </TableCell>
                      <TableCell className={`text-right font-mono text-xs font-semibold ${pnl.isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                        {pnl.value} ({formatSignedPct(tr.pnlPct)})
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>

            {totalPages > 1 && (
              <div className="shrink-0 border-t border-slate-700/50 px-3 py-2 flex items-center justify-between">
                <span className="text-[10px] text-gray-500 font-mono">
                  {(tradePage - 1) * tradesPerPage + 1}–{Math.min(tradePage * tradesPerPage, totalTrades)} of {totalTrades}
                </span>
                <Pagination page={tradePage} totalPages={totalPages} onPageChange={setTradePage} />
              </div>
            )}
          </>
        )
      })() : (
        <p className="text-center text-gray-500 py-6 text-sm">
          No trades were executed during this backtest. Try relaxing strategy rules or expanding dates.
        </p>
      )}
    </div>
  )
}
