import { useState, useEffect } from 'react'
import { RefreshCw, Loader2, Filter, X, GitCompareArrows, CheckSquare, Square } from 'lucide-react'
import { Card, CardHeader, CardTitle, CardContent } from '../../components/ui/card'
import { Badge } from '../../components/ui/badge'
import { Input } from '../../components/ui/input'
import { Select } from '../../components/ui/select'
import { Button } from '../../components/ui/button'
import { cn } from '../../lib/utils'

const formatTime = (dateStr) => {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const STATUS_CONFIG = {
  completed: { label: 'Done', cls: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30' },
  running:   { label: 'Running', cls: 'bg-blue-500/15 text-blue-400 border-blue-500/30 animate-pulse' },
  queued:    { label: 'Queued', cls: 'bg-gray-500/15 text-gray-400 border-gray-500/30' },
  failed:    { label: 'Failed', cls: 'bg-red-500/15 text-red-400 border-red-500/30' },
  cancelled: { label: 'Cancelled', cls: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30' },
}

export default function BacktestHistory({
  data,
  selectedId,
  onSelect,
  onRefresh,
  isLoading,
  filters,
  onApplyFilters,
  onClearFilters,
  comparisonIds = [],
  onToggleComparison,
}) {
  const [draftFilters, setDraftFilters] = useState(filters)
  const [filtersOpen, setFiltersOpen] = useState(false)

  useEffect(() => {
    setDraftFilters(filters)
  }, [filters])

  const hasActiveFilters = Object.values(filters).some(Boolean)
  const compareCount = comparisonIds.length

  return (
    <Card className="flex flex-col overflow-hidden">
      {/* ── Header ── */}
      <CardHeader className="pb-2 shrink-0">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-sm font-semibold">Run History</CardTitle>
            <p className="text-xs text-gray-500 mt-0.5">
              {data?.length ?? 0} result{data?.length !== 1 ? 's' : ''}
              {hasActiveFilters && ' · filtered'}
            </p>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setFiltersOpen((v) => !v)}
              className={cn(
                'p-1.5 rounded transition-colors',
                filtersOpen || hasActiveFilters
                  ? 'text-emerald-400 bg-emerald-500/10'
                  : 'text-gray-500 hover:text-gray-300'
              )}
              title="Filters"
            >
              <Filter className="size-3.5" />
            </button>
            <button
              onClick={onRefresh}
              className="p-1.5 rounded text-gray-500 hover:text-emerald-400 transition-colors"
              title="Refresh"
            >
              <RefreshCw className="size-3.5" />
            </button>
          </div>
        </div>

        {/* Compare counter pill */}
        {compareCount > 0 && (
          <div className="flex items-center gap-2 mt-2 px-2.5 py-1.5 rounded-md bg-emerald-500/10 border border-emerald-500/20">
            <GitCompareArrows className="size-3.5 text-emerald-400 shrink-0" />
            <span className="text-xs text-emerald-400 font-medium flex-1">
              {compareCount} run{compareCount > 1 ? 's' : ''} selected for comparison
            </span>
            <span className="text-[10px] text-emerald-600 font-mono">{compareCount}/4</span>
          </div>
        )}

        {/* Collapsible Filters */}
        {filtersOpen && (
          <div className="mt-2 space-y-2 rounded-lg border border-gray-800 bg-gray-950/60 p-3">
            <div className="grid grid-cols-2 gap-2">
              <Input
                value={draftFilters.strategyName || ''}
                onChange={(e) => setDraftFilters((prev) => ({ ...prev, strategyName: e.target.value }))}
                placeholder="Strategy"
              />
              <Input
                value={draftFilters.symbol || ''}
                onChange={(e) => setDraftFilters((prev) => ({ ...prev, symbol: e.target.value.toUpperCase() }))}
                placeholder="Symbol"
              />
              <Input
                value={draftFilters.timeframe || ''}
                onChange={(e) => setDraftFilters((prev) => ({ ...prev, timeframe: e.target.value }))}
                placeholder="Timeframe"
              />
              <Select
                value={draftFilters.status || ''}
                onChange={(e) => setDraftFilters((prev) => ({ ...prev, status: e.target.value }))}
              >
                <option value="">All Statuses</option>
                <option value="queued">Queued</option>
                <option value="running">Running</option>
                <option value="completed">Completed</option>
                <option value="failed">Failed</option>
                <option value="cancelled">Cancelled</option>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Input
                type="date"
                value={draftFilters.createdAfter || ''}
                onChange={(e) => setDraftFilters((prev) => ({ ...prev, createdAfter: e.target.value }))}
              />
              <Input
                type="date"
                value={draftFilters.createdBefore || ''}
                onChange={(e) => setDraftFilters((prev) => ({ ...prev, createdBefore: e.target.value }))}
              />
            </div>
            <div className="flex gap-2">
              <Button
                size="sm"
                className="bg-emerald-600 hover:bg-emerald-700 text-white flex-1 text-xs h-7"
                onClick={() => { onApplyFilters(draftFilters); setFiltersOpen(false) }}
              >
                Apply
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="flex-1 border-gray-700 text-gray-400 hover:text-white text-xs h-7"
                onClick={() => {
                  const cleared = { strategyName: '', symbol: '', timeframe: '', status: '', createdAfter: '', createdBefore: '' }
                  setDraftFilters(cleared)
                  onClearFilters(cleared)
                }}
              >
                <X className="size-3 mr-1" />
                Clear
              </Button>
            </div>
          </div>
        )}
      </CardHeader>

      {/* ── List ── */}
      <CardContent className="overflow-y-auto px-3 pb-3 max-h-[520px] space-y-1">
        {isLoading ? (
          <div className="flex justify-center p-6">
            <Loader2 className="size-5 animate-spin text-gray-600" />
          </div>
        ) : !data || data.length === 0 ? (
          <p className="text-gray-500 text-xs text-center py-8">No backtest runs yet.</p>
        ) : (
          data.map((b) => {
            const isSelected = selectedId === b.jobId
            const isCompared = comparisonIds.includes(b.jobId)
            const isCompleted = b.status === 'completed'
            const statusCfg = STATUS_CONFIG[b.status] ?? STATUS_CONFIG.queued

            return (
              <div
                key={b.jobId}
                className={cn(
                  'group relative rounded-lg border transition-all duration-150',
                  isSelected
                    ? 'border-emerald-500/50 bg-emerald-500/8 shadow-[0_0_0_1px_rgba(16,185,129,0.15)]'
                    : isCompared
                    ? 'border-emerald-900/60 bg-gray-900/60'
                    : 'border-gray-800/60 bg-gray-900/30 hover:border-gray-700 hover:bg-gray-800/40'
                )}
              >
                {/* Clickable main area */}
                <button
                  onClick={() => onSelect(b.jobId)}
                  className="w-full text-left p-3 pr-10"
                >
                  {/* Strategy name */}
                  <div className={cn(
                    'text-xs font-semibold truncate leading-tight',
                    isSelected ? 'text-emerald-300' : 'text-gray-200'
                  )}>
                    {b.strategyName}
                  </div>

                  {/* Meta row */}
                  <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
                    <span className="text-[10px] font-mono text-gray-400 bg-gray-800 px-1.5 py-0.5 rounded">
                      {b.symbol}
                    </span>
                    <span className="text-[10px] font-mono text-gray-500 bg-gray-800/60 px-1.5 py-0.5 rounded">
                      {b.timeframe}
                    </span>
                    <span className={cn(
                      'text-[10px] px-1.5 py-0.5 rounded border font-medium',
                      statusCfg.cls
                    )}>
                      {statusCfg.label}
                    </span>
                  </div>

                  {/* Timestamp */}
                  {b.createdAt && (
                    <div className="text-[10px] text-gray-600 mt-1.5">
                      {formatTime(b.createdAt)}
                    </div>
                  )}
                </button>

                {/* Compare toggle — absolute top-right */}
                {isCompleted && (
                  <button
                    onClick={(e) => { e.stopPropagation(); onToggleComparison?.(b.jobId) }}
                    title={isCompared ? 'Remove from comparison' : 'Add to comparison'}
                    className={cn(
                      'absolute top-2.5 right-2.5 p-1 rounded transition-all',
                      isCompared
                        ? 'text-emerald-400 bg-emerald-500/15 hover:bg-emerald-500/25'
                        : 'text-gray-600 hover:text-gray-400 bg-transparent hover:bg-gray-700/50 opacity-0 group-hover:opacity-100'
                    )}
                  >
                    {isCompared
                      ? <CheckSquare className="size-3.5" />
                      : <Square className="size-3.5" />
                    }
                  </button>
                )}
              </div>
            )
          })
        )}
      </CardContent>
    </Card>
  )
}
