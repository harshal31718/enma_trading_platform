import { useNavigate } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../../components/ui/table'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/card'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
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
  return 'info'
}

export default function RecentActivityTable({ data }) {
  const navigate = useNavigate()

  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent Activity</CardTitle>
        <CardDescription>Last 5 backtest execution runs</CardDescription>
      </CardHeader>
      <CardContent>
        {!data || data.length === 0 ? (
          <p className="text-gray-500 text-sm text-center py-6">No simulation history found.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Strategy</TableHead>
                <TableHead>Market</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Run Date</TableHead>
                <TableHead className="text-right">Net P&L</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((run) => {
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
                        <span className="text-gray-500">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => navigate(`/backtest?jobId=${run.jobId}`)}
                        className="h-8 w-8 p-0"
                      >
                        <ChevronRight className="size-4 text-gray-500 hover:text-emerald-400" />
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
