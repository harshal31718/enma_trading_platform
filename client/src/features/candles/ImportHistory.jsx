import { Download } from 'lucide-react'
import { useAvailableImports } from '@/hooks/useCandles'
import DataTable from '@/components/ui/DataTable'
import StatusBadge from '@/components/ui/StatusBadge'
import EmptyState from '@/components/ui/EmptyState'

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

const columns = [
  { key: 'symbol', header: 'Symbol' },
  { key: 'exchange', header: 'Exchange' },
  { key: 'timeframe', header: 'Timeframe' },
  { key: 'startDate', header: 'Start' },
  { key: 'endDate', header: 'End' },
  {
    key: 'candleCount',
    header: 'Candles',
    render: (val) => val?.toLocaleString() ?? '—',
  },
  {
    key: 'status',
    header: 'Status',
    render: (val) => <StatusBadge status={val} />,
  },
  {
    key: 'importedAt',
    header: 'Imported At',
    render: (val) => formatDate(val),
  },
]

export default function ImportHistory() {
  const { data: imports, isLoading } = useAvailableImports()

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-6">
      <h2 className="text-gray-100 font-medium mb-4">Import History</h2>
      <DataTable
        columns={columns}
        data={imports ?? []}
        loading={isLoading}
        emptyState={
          <EmptyState
            icon={Download}
            title="No imports yet"
            description="Use the form to import historical candle data from Binance."
          />
        }
      />
    </div>
  )
}
