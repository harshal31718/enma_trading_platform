import { useNavigate } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell, SortableHeader } from '../../components/ui/table'
import { Card, CardHeader, CardTitle, CardContent } from '../../components/ui/card'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { useTableSort } from '../../hooks/useTableSort'
import { formatPnl, formatPct, formatSignedPct } from '../../utils/formatters'

function formatDate(dateStr) {
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function statusVariant(status) {
  if (status === 'completed') return 'default'
  if (status === 'failed') return 'danger'
  if (status === 'cancelled') return 'warning'
  if (status === 'running') return 'info'
  return 'secondary'
}

export default function RecentActivityTable({ data }) {
  const navigate = useNavigate()
  const { sortedRows, sortState, onSort } = useTableSort(data, {
    getValue: (row, key) => {
      if (key === 'pnl') return row.metrics?.netProfit ?? 0
      return row[key]
    }
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent Activity</CardTitle>
      </CardHeader>
      <CardContent>
        {!data || data.length === 0 ? (
          <div className="border border-dashed border-slate-700/30 p-8 flex flex-col items-center justify-center text-center gap-3">
            <p className="text-slate-400 text-xs">No simulation history found.</p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => navigate('/backtest')}
              className="border-slate-700/50 text-slate-400 hover:text-gray-200 text-xs h-8 px-3"
            >
              Run Backtest
            </Button>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <SortableHeader sortKey="strategyName" sortState={sortState} onSort={onSort}>Strategy</SortableHeader>
                <SortableHeader sortKey="symbol" sortState={sortState} onSort={onSort}>Market</SortableHeader>
                <SortableHeader sortKey="status" sortState={sortState} onSort={onSort}>Status</SortableHeader>
                <SortableHeader sortKey="createdAt" sortState={sortState} onSort={onSort}>Run Date</SortableHeader>
                <SortableHeader sortKey="pnl" sortState={sortState} onSort={onSort} className="text-right">Net P&L</SortableHeader>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedRows.map((run) => {
                const pnl = run.metrics ? formatPnl(run.metrics.netProfit) : null
                return (
                  <TableRow key={run.jobId}>
                    <TableCell className="font-semibold text-gray-200">{run.strategyName}</TableCell>
                    <TableCell className="text-gray-400 text-xs">
                      {run.symbol} ({run.timeframe})
                    </TableCell>
                    <TableCell>
                      <Badge variant={statusVariant(run.status)}>{run.status}</Badge>
                    </TableCell>
                    <TableCell className="text-gray-400 text-xs">{formatDate(run.createdAt)}</TableCell>
                    <TableCell className="text-right font-mono text-xs font-semibold">
                      {pnl ? (
                        <span className={pnl.isPositive ? 'text-emerald-400' : 'text-red-400'}>
                          {pnl.value} ({formatSignedPct(run.metrics.netProfitPct)})
                        </span>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => navigate(`/backtest?jobId=${run.jobId}`)}
                        className="h-8 w-8 p-0"
                      >
                        <ChevronRight className="size-4 text-slate-400 hover:text-emerald-400" />
                      </Button>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}
