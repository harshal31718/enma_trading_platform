import { useSearchParams } from 'react-router-dom'
import { AlertTriangle, History } from 'lucide-react'
import PageWrapper from '@/components/layout/PageWrapper'
import PageHeader from '@/components/ui/PageHeader'
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  SortableHeader,
  TableCell,
} from '@/components/ui/table'
import { Pagination } from '@/components/ui/pagination'
import { EmptyState } from '@/components/ui/empty-state'
import { useOrderHistory } from '@/hooks/useOrderHistory'
import { formatPrice, formatPnl, formatDateTime } from '@/utils/formatters'

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

// Query-param state lives entirely in the URL (per §3.4): ?symbol=&side=&page=&sort=&order=
// so filters/sort/page survive refresh and are shareable/back-button-able.
export default function OrderHistory() {
  const [searchParams, setSearchParams] = useSearchParams()

  const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10) || 1)
  const symbol = searchParams.get('symbol') || ''
  const side = searchParams.get('side') || ''
  const sort = searchParams.get('sort') || 'exitTime'
  const order = searchParams.get('order') || 'desc'
  const sortState = { key: sort, dir: order }

  const { data, isLoading, isError, error } = useOrderHistory({
    page,
    limit: LIMIT,
    filters: { symbol, side },
    sort,
    order,
  })

  const records = data?.records ?? []
  const pagination = data?.pagination ?? { page: 1, totalPages: 1, total: 0 }

  function updateParams(patch) {
    const next = new URLSearchParams(searchParams)
    Object.entries(patch).forEach(([key, value]) => {
      if (value === undefined || value === null || value === '') next.delete(key)
      else next.set(key, String(value))
    })
    setSearchParams(next)
  }

  function handleFilterChange(e) {
    const { name, value } = e.target
    updateParams({ [name]: value, page: 1 })
  }

  function handleSort(key) {
    if (sort === key) {
      updateParams({ order: order === 'asc' ? 'desc' : 'asc', page: 1 })
    } else {
      updateParams({ sort: key, order: 'asc', page: 1 })
    }
  }

  return (
    <PageWrapper>
      <PageHeader
        title="Order History"
        actions={
          <div className="flex items-center gap-3">
            <label htmlFor="oh-symbol-filter" className="sr-only">
              Filter by symbol
            </label>
            <input
              id="oh-symbol-filter"
              name="symbol"
              value={symbol}
              onChange={handleFilterChange}
              placeholder="Symbol (e.g. BTCUSDT)"
              className="bg-[#0a0d13] border border-slate-700/50 rounded-lg px-3 py-1.5 text-sm text-gray-100 placeholder-slate-600 focus:outline-none focus:border-emerald-500 w-44 transition-colors"
            />
            <label htmlFor="oh-side-filter" className="sr-only">
              Filter by side
            </label>
            <select
              id="oh-side-filter"
              name="side"
              value={side}
              onChange={handleFilterChange}
              className="bg-[#0a0d13] border border-slate-700/50 rounded-lg px-3 py-1.5 text-sm text-gray-100 focus:outline-none focus:border-emerald-500 transition-colors"
            >
              <option value="">All sides</option>
              <option value="long">Long</option>
              <option value="short">Short</option>
            </select>
          </div>
        }
      />

      {isError && (
        <div role="alert" className="flex items-center gap-3 bg-red-950/20 border border-red-800/40 rounded-lg p-4 mb-4 text-red-400">
          <AlertTriangle size={16} className="shrink-0" />
          <span className="text-sm">
            {error?.response?.data?.message ?? error?.message ?? 'Failed to load order history'}
          </span>
        </div>
      )}

      <div className="bg-title-bg border border-slate-700/50 rounded-xl overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>ID</TableHead>
              <SortableHeader sortKey="symbol" sortState={sortState} onSort={handleSort}>
                Symbol
              </SortableHeader>
              <SortableHeader sortKey="side" sortState={sortState} onSort={handleSort}>
                Side
              </SortableHeader>
              <TableHead>Executed By</TableHead>
              <TableHead>Entry</TableHead>
              <TableHead>SL</TableHead>
              <TableHead>TP</TableHead>
              <TableHead>Exit</TableHead>
              <SortableHeader sortKey="margin" sortState={sortState} onSort={handleSort}>
                Margin
              </SortableHeader>
              <TableHead>Liq. Price</TableHead>
              <SortableHeader sortKey="netPnl" sortState={sortState} onSort={handleSort}>
                Net P&amp;L
              </SortableHeader>
              <SortableHeader sortKey="exitTime" sortState={sortState} onSort={handleSort} className="text-right">
                Time (UTC)
              </SortableHeader>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading &&
              Array.from({ length: 8 }).map((_, i) => (
                <TableRow key={i}>
                  {Array.from({ length: 12 }).map((__, j) => (
                    <TableCell key={j}>
                      <div className="h-4 bg-slate-800/50 rounded animate-pulse w-20" />
                    </TableCell>
                  ))}
                </TableRow>
              ))}

            {!isLoading && records.length === 0 && (
              <TableRow>
                <TableCell colSpan={12} className="p-0">
                  <EmptyState
                    icon={History}
                    title="No trades recorded yet"
                    description="Completed bot and manual round-trip trades will show up here once you close a position."
                  />
                </TableCell>
              </TableRow>
            )}

            {!isLoading &&
              records.map((r) => (
                <TableRow key={r.tradeId}>
                  <TableCell className="font-mono tabular-nums text-xs text-slate-400">
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
                  <TableCell className="text-right text-slate-400 text-xs font-mono tabular-nums">
                    {formatDateTime(r.exitTime)}
                  </TableCell>
                </TableRow>
              ))}
          </TableBody>
        </Table>

        {!isLoading && pagination.totalPages > 1 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-slate-700/50">
            <span className="text-sm text-slate-400">
              {pagination.total} trades &middot; page {pagination.page} of {pagination.totalPages}
            </span>
            <Pagination
              page={pagination.page}
              totalPages={pagination.totalPages}
              onPageChange={(p) => updateParams({ page: p })}
            />
          </div>
        )}
      </div>
    </PageWrapper>
  )
}
