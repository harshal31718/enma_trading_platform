import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../../components/ui/table'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/card'
import { formatPrice, formatPct } from '../../utils/formatters'

export default function StrategyLeaderboard({ data }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Strategy Leaderboard</CardTitle>
        <CardDescription>Aggregated performance per strategy (completed runs)</CardDescription>
      </CardHeader>
      <CardContent>
        {!data || data.length === 0 ? (
          <p className="text-gray-500 text-sm text-center py-6">No performance statistics available.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Strategy</TableHead>
                <TableHead className="text-center">Runs</TableHead>
                <TableHead className="text-right">Avg Win Rate</TableHead>
                <TableHead className="text-right">Avg Net Profit</TableHead>
                <TableHead className="text-right">Avg Sharpe</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((item, idx) => {
                const avgProfit = parseFloat(item.averageNetProfit)
                return (
                  <TableRow key={item.strategyName}>
                    <TableCell className="font-semibold text-gray-200">
                      <span className={`mr-2 text-xs font-bold ${
                        idx === 0 ? 'text-emerald-400' :
                        idx === 1 ? 'text-gray-300' :
                        idx === 2 ? 'text-gray-400' :
                        'text-gray-600'
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
      </CardContent>
    </Card>
  )
}
