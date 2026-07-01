import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../../components/ui/table'
import { Card, CardHeader, CardTitle, CardContent } from '../../components/ui/card'
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
                    <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
                      {item.instrument_type || 'spot'}
                    </span>
                  </TableCell>
                  <TableCell className="text-xs text-slate-500 font-mono">{formatDate(item.start_date)}</TableCell>
                  <TableCell className="text-xs text-slate-500 font-mono">{formatDate(item.end_date)}</TableCell>
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
