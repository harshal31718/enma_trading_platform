import { useState } from 'react'
import { AlertTriangle, ChevronLeft, ChevronRight } from 'lucide-react'
import PageWrapper from '@/components/layout/PageWrapper'
import PageHeader from '@/components/ui/PageHeader'
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from '@/components/ui/table'
import { useOrderHistory } from '@/hooks/useOrderHistory'
import { formatPrice, formatPnl, formatIsoDate } from '@/utils/formatters'

const LIMIT = 50

function SideBadge({ side }) {
  return (
    <span
      className={
        side === 'long'
          ? 'inline-flex items-center rounded px-2 py-0.5 text-xs font-medium bg-emerald-400/10 text-emerald-400'
          : 'inline-flex items-center rounded px-2 py-0.5 text-xs font-medium bg-red-400/10 text-red-400'
      }
    >
      {side === 'long' ? 'Long' : 'Short'}
    </span>
  )
}

function PnlCell({ value }) {
  const { value: formatted, isPositive } = formatPnl(value)
  return (
    <span className={isPositive ? 'text-emerald-400' : 'text-red-400'}>
      {formatted}
    </span>
  )
}

function NullablePrice({ value }) {
  if (value == null || value === '') return <span className="text-gray-600">—</span>
  return <>{formatPrice(value)}</>
}

export default function OrderHistory() {
  const [page, setPage] = useState(1)
  const [filters, setFilters] = useState({ symbol: '', side: '' })

  const { data, isLoading, isError, error } = useOrderHistory({
    page,
    limit: LIMIT,
    filters: Object.fromEntries(
      Object.entries(filters).filter(([, v]) => v !== '')
    ),
  })

  const records = data?.records ?? []
  const pagination = data?.pagination ?? { page: 1, totalPages: 1, total: 0 }

  function handleFilterChange(e) {
    const { name, value } = e.target
    setFilters((prev) => ({ ...prev, [name]: value }))
    setPage(1)
  }

  return (
    <PageWrapper>
      <PageHeader
        title="Order History"
        description="Completed round-trip trades from bot sessions"
        actions={
          <div className="flex items-center gap-3">
            <input
              name="symbol"
              value={filters.symbol}
              onChange={handleFilterChange}
              placeholder="Symbol (e.g. BTCUSDT)"
              className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-gray-600 w-44"
            />
            <select
              name="side"
              value={filters.side}
              onChange={handleFilterChange}
              className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-100 focus:outline-none focus:border-gray-600"
            >
              <option value="">All sides</option>
              <option value="long">Long</option>
              <option value="short">Short</option>
            </select>
          </div>
        }
      />

      {isError && (
        <div className="flex items-center gap-3 bg-red-950/20 border border-red-800/40 rounded-lg p-4 mb-4 text-red-400">
          <AlertTriangle size={16} className="shrink-0" />
          <span className="text-sm">
            {error?.response?.data?.message ?? error?.message ?? 'Failed to load order history'}
          </span>
        </div>
      )}

      <div className="bg-gray-900 border border-gray-800 rounded-lg">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>ID</TableHead>
              <TableHead>Symbol</TableHead>
              <TableHead>Side</TableHead>
              <TableHead>Executed By</TableHead>
              <TableHead>Entry</TableHead>
              <TableHead>SL</TableHead>
              <TableHead>TP</TableHead>
              <TableHead>Exit</TableHead>
              <TableHead>Margin</TableHead>
              <TableHead>Liq. Price</TableHead>
              <TableHead>Net P&L</TableHead>
              <TableHead className="text-right">Time</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading &&
              Array.from({ length: 8 }).map((_, i) => (
                <TableRow key={i}>
                  {Array.from({ length: 12 }).map((__, j) => (
                    <TableCell key={j}>
                      <div className="h-4 bg-gray-800 rounded animate-pulse w-20" />
                    </TableCell>
                  ))}
                </TableRow>
              ))}

            {!isLoading && records.length === 0 && (
              <TableRow>
                <TableCell colSpan={12} className="text-center text-gray-500 py-16">
                  No trades recorded yet.
                </TableCell>
              </TableRow>
            )}

            {!isLoading &&
              records.map((r) => (
                <TableRow key={r.tradeId}>
                  <TableCell className="font-mono text-xs text-gray-500">
                    {r.tradeId.replace('trade_', '')}
                  </TableCell>
                  <TableCell className="font-medium text-gray-100">{r.symbol}</TableCell>
                  <TableCell>
                    <SideBadge side={r.side} />
                  </TableCell>
                  <TableCell className="text-gray-300">{r.executedBy}</TableCell>
                  <TableCell>{formatPrice(r.entryPrice)}</TableCell>
                  <TableCell className="text-red-400/80">
                    <NullablePrice value={r.slOrderPrice} />
                  </TableCell>
                  <TableCell className="text-emerald-400/80">
                    <NullablePrice value={r.tpOrderPrice} />
                  </TableCell>
                  <TableCell>{formatPrice(r.exitPrice)}</TableCell>
                  <TableCell className="text-gray-300">
                    <NullablePrice value={r.margin} />
                  </TableCell>
                  <TableCell className="text-yellow-400/80">
                    <NullablePrice value={r.liquidationPrice} />
                  </TableCell>
                  <TableCell>
                    <PnlCell value={r.netPnl} />
                  </TableCell>
                  <TableCell className="text-right text-gray-500 text-xs">
                    {formatIsoDate(r.exitTime)}
                  </TableCell>
                </TableRow>
              ))}
          </TableBody>
        </Table>

        {!isLoading && pagination.totalPages > 1 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-gray-800">
            <span className="text-sm text-gray-500">
              {pagination.total} trades · page {pagination.page} of {pagination.totalPages}
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="p-1.5 rounded text-gray-400 hover:text-gray-100 hover:bg-gray-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                <ChevronLeft size={16} />
              </button>
              <button
                onClick={() => setPage((p) => Math.min(pagination.totalPages, p + 1))}
                disabled={page >= pagination.totalPages}
                className="p-1.5 rounded text-gray-400 hover:text-gray-100 hover:bg-gray-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                <ChevronRight size={16} />
              </button>
            </div>
          </div>
        )}
      </div>
    </PageWrapper>
  )
}
