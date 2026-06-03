import { RefreshCw, Loader2, ChevronRight } from 'lucide-react'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/card'
import { Badge } from '../../components/ui/badge'

const formatTime = (dateStr) => {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export default function BacktestHistory({ data, selectedId, onSelect, onRefresh, isLoading }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <div>
          <CardTitle>History</CardTitle>
          <CardDescription>Previous simulation runs</CardDescription>
        </div>
        <button
          onClick={onRefresh}
          className="text-gray-400 hover:text-emerald-400 transition-colors p-1"
          title="Refresh history"
        >
          <RefreshCw className="size-4" />
        </button>
      </CardHeader>
      <CardContent className="overflow-y-auto pr-1 max-h-[400px]">
        {isLoading ? (
          <div className="flex justify-center p-4">
            <Loader2 className="size-5 animate-spin text-gray-600" />
          </div>
        ) : !data || data.length === 0 ? (
          <p className="text-gray-500 text-sm text-center py-4">No backtests run yet.</p>
        ) : (
          <div className="space-y-2">
            {data.map((b) => (
              <button
                key={b.jobId}
                onClick={() => onSelect(b.jobId)}
                className={`w-full text-left p-3 rounded border-l-2 text-sm transition-all flex items-center justify-between group ${
                  selectedId === b.jobId
                    ? 'border-emerald-500 bg-emerald-500/10 text-emerald-400'
                    : 'border-transparent bg-gray-950/40 text-gray-300 hover:bg-gray-800/40'
                }`}
              >
                <div className="truncate pr-2">
                  <div className="font-medium truncate">{b.strategyName}</div>
                  <div className="text-gray-500 text-xs flex items-center gap-1.5 mt-1">
                    <span>{b.symbol}</span>
                    <span>•</span>
                    <span>{b.timeframe}</span>
                    {b.createdAt && (
                      <>
                        <span>•</span>
                        <span className="text-gray-400">{formatTime(b.createdAt)}</span>
                      </>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {b.status === 'completed' && (
                    <Badge variant="default" className="text-[10px] px-1 py-0">Done</Badge>
                  )}
                  {b.status === 'failed' && (
                    <Badge variant="danger" className="text-[10px] px-1 py-0">Fail</Badge>
                  )}
                  {b.status === 'running' && (
                    <Badge variant="info" className="text-[10px] px-1 py-0 animate-pulse">Run</Badge>
                  )}
                  <ChevronRight className="size-4 text-gray-600 group-hover:text-emerald-400 transition-colors" />
                </div>
              </button>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
