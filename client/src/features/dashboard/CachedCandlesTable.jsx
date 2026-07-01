import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell, SortableHeader } from '../../components/ui/table'
import { Card, CardHeader, CardTitle, CardContent } from '../../components/ui/card'
import { Badge } from '../../components/ui/badge'
import { useTableSort } from '../../hooks/useTableSort'

function formatDate(dateStr) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

export default function CachedCandlesTable({ data }) {
  const { sortedRows, sortState, onSort } = useTableSort(data, {
    getValue: (row, key) => {
      if (key === 'candles') return row.total_candles
      return row[key]
    }
  })

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
                <SortableHeader sortKey="symbol" sortState={sortState} onSort={onSort}>Symbol</SortableHeader>
                <SortableHeader sortKey="timeframe" sortState={sortState} onSort={onSort}>Timeframe</SortableHeader>
                <SortableHeader sortKey="exchange" sortState={sortState} onSort={onSort}>Exchange</SortableHeader>
                <SortableHeader sortKey="instrument_type" sortState={sortState} onSort={onSort}>Type</SortableHeader>
                <SortableHeader sortKey="start_date" sortState={sortState} onSort={onSort}>Start Date</SortableHeader>
                <SortableHeader sortKey="end_date" sortState={sortState} onSort={onSort}>End Date</SortableHeader>
                <SortableHeader sortKey="candles" sortState={sortState} onSort={onSort} className="text-right">Total Candles</SortableHeader>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedRows.map((item, idx) => (
                <TableRow key={`${item.symbol}-${item.timeframe}-${idx}`}>
                  <TableCell className="font-semibold text-emerald-400">{item.symbol}</TableCell>
                  <TableCell className="font-mono text-xs">{item.timeframe}</TableCell>
                  <TableCell className="capitalize text-gray-300">{item.exchange}</TableCell>
                  <TableCell>
                    <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                      {item.instrument_type || 'spot'}
                    </span>
                  </TableCell>
                  <TableCell className="text-xs text-slate-400 font-mono">{formatDate(item.start_date)}</TableCell>
                  <TableCell className="text-xs text-slate-400 font-mono">{formatDate(item.end_date)}</TableCell>
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
