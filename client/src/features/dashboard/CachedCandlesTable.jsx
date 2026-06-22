import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../../components/ui/table'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/card'
import { Badge } from '../../components/ui/badge'

function formatDate(dateStr) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

export default function CachedCandlesTable({ data }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>TimescaleDB Cache</CardTitle>
        <CardDescription>Locally cached historical candle ranges</CardDescription>
      </CardHeader>
      <CardContent>
        {!data || data.length === 0 ? (
          <p className="text-slate-400 text-sm text-center py-6">No historical candle data cached locally yet.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Symbol</TableHead>
                <TableHead>Timeframe</TableHead>
                <TableHead>Exchange</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Start Date</TableHead>
                <TableHead>End Date</TableHead>
                <TableHead className="text-right">Total Candles</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((item, idx) => (
                <TableRow key={`${item.symbol}-${item.timeframe}-${idx}`}>
                  <TableCell className="font-semibold text-emerald-400">{item.symbol}</TableCell>
                  <TableCell className="font-mono text-xs">{item.timeframe}</TableCell>
                  <TableCell className="capitalize text-gray-300">{item.exchange}</TableCell>
                  <TableCell>
                    <Badge variant={item.instrument_type === 'futures' ? 'info' : 'secondary'}>
                      {item.instrument_type || 'spot'}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs text-gray-400">{formatDate(item.start_date)}</TableCell>
                  <TableCell className="text-xs text-gray-400">{formatDate(item.end_date)}</TableCell>
                  <TableCell className="text-right font-mono text-xs font-semibold text-gray-300">
                    {item.total_candles.toLocaleString()}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}
