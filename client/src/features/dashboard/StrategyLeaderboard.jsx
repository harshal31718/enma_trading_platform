import { Table, TableHeader, TableBody, TableRow, TableCell, SortableHeader } from '../../components/ui/table'
import { useTableSort } from '../../hooks/useTableSort'
import { formatPrice, formatPct } from '../../utils/formatters'

export default function StrategyLeaderboard({ data }) {
  const { sortedRows, sortState, onSort } = useTableSort(data, {
    getValue: (row, key) => {
      if (key === 'avgProfit') return parseFloat(row.averageNetProfit)
      if (key === 'avgWinRate') return parseFloat(row.averageWinRate)
      if (key === 'avgSharpe') return parseFloat(row.averageSharpe)
      return row[key]
    }
  })

  return (
    <div className="w-full">
      {!data || data.length === 0 ? (
        <p className="text-slate-400 text-sm text-center py-6">No performance statistics available.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <SortableHeader sortKey="strategyName" sortState={sortState} onSort={onSort}>Strategy</SortableHeader>
              <SortableHeader sortKey="runs" sortState={sortState} onSort={onSort} className="text-center">Runs</SortableHeader>
              <SortableHeader sortKey="avgWinRate" sortState={sortState} onSort={onSort} className="text-right">Avg Win Rate</SortableHeader>
              <SortableHeader sortKey="avgProfit" sortState={sortState} onSort={onSort} className="text-right">Avg Net Profit</SortableHeader>
              <SortableHeader sortKey="avgSharpe" sortState={sortState} onSort={onSort} className="text-right">Avg Sharpe</SortableHeader>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sortedRows.map((item, idx) => {
              const avgProfit = parseFloat(item.averageNetProfit)
              return (
                <TableRow key={item.strategyName}>
                  <TableCell className="font-semibold text-gray-200">
                    <span className={`mr-2 text-xs font-bold ${
                      idx === 0 ? 'text-emerald-400' :
                      idx === 1 ? 'text-gray-300' :
                      idx === 2 ? 'text-gray-400' :
                      'text-slate-600'
                    }`}>#{idx + 1}</span>
                    {item.strategyName}
                  </TableCell>
                  <TableCell className="text-center font-semibold text-gray-300">{item.runs}</TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    {formatPct(parseFloat(item.averageWinRate) * 100)}
                  </TableCell>
                  <TableCell className={`text-right font-mono text-xs font-semibold ${avgProfit >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {avgProfit >= 0 ? '+' : ''}{formatPrice(avgProfit)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs text-gray-200 font-semibold">
                    {parseFloat(item.averageSharpe).toFixed(2)}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
