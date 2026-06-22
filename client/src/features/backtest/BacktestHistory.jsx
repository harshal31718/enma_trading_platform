import { useState, useEffect } from 'react'
import { RefreshCw, Loader2, Filter, X, GitCompareArrows, CheckSquare, Square, ChevronLeft, ChevronRight } from 'lucide-react'
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
  const [histPage, setHistPage] = useState(1)
  const HIST_PER_PAGE = 20

  useEffect(() => {
    setDraftFilters(filters)
    setHistPage(1)
  }, [filters])

  useEffect(() => {
    setHistPage(1)
  }, [data])

  const hasActiveFilters = Object.values(filters).some(Boolean)
  const compareCount = comparisonIds.length

  const totalItems = data?.length ?? 0
  const totalHistPages = Math.max(1, Math.ceil(totalItems / HIST_PER_PAGE))
  const pagedData = data?.slice((histPage - 1) * HIST_PER_PAGE, histPage * HIST_PER_PAGE) ?? []

  return (
    <div className="flex flex-col h-full">
      {/* ── Header ── */}
      <div className="shrink-0 border-b border-slate-700/50">
        <div className="h-11 bg-title-bg title-fade flex items-center justify-between px-4">
          <div>
            <span className="text-sm font-semibold text-gray-100">Backtest History</span>
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
      </div>

      {/* ── List ── */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex justify-center p-6">
            <Loader2 className="size-5 animate-spin text-gray-600" />
          </div>
        ) : !data || data.length === 0 ? (
          <p className="text-gray-500 text-xs text-center py-8">No backtest runs yet.</p>
        ) : (
          pagedData.map((b) => {
            const isSelected = selectedId === b.jobId
            const isCompared = comparisonIds.includes(b.jobId)
            const isCompleted = b.status === 'completed'
            const statusCfg = STATUS_CONFIG[b.status] ?? STATUS_CONFIG.queued

            return (
              <div
                key={b.jobId}
                className={cn(
                  'group relative border h-11 transition-all duration-150',
                  isSelected
                    ? 'border-emerald-500/50 bg-emerald-500/8'
                    : isCompared
                    ? 'border-transparent border-b-emerald-900/60 bg-gray-900/60'
                    : 'border-transparent border-b-slate-700/50 bg-transparent hover:bg-slate-800/20'
                )}
              >
                {/* Clickable main area */}
                <button
                  onClick={() => onSelect(b.jobId)}
                  className="w-full h-full text-left px-3 pr-8 flex flex-col justify-center"
                >
                  <div className="flex items-center justify-between w-full">
                    {/* Strategy name */}
                    <div className={cn(
                      'text-xs font-semibold truncate leading-none',
                      isSelected ? 'text-emerald-300' : 'text-gray-200'
                    )}>
                      {b.strategyName}
                    </div>
                    {/* Timestamp */}
                    {b.createdAt && (
                      <div className="text-[9px] text-gray-500 leading-none">
                        {formatTime(b.createdAt)}
                      </div>
                    )}
                  </div>

                  {/* Meta row */}
                  <div className="flex items-center gap-1.5 mt-1.5">
                    <span className="text-[9px] font-mono text-gray-400 bg-gray-800 px-1 py-[1px] rounded leading-none">
                      {b.symbol}
                    </span>
                    <span className="text-[9px] font-mono text-gray-500 bg-gray-800/60 px-1 py-[1px] rounded leading-none">
                      {b.timeframe}
                    </span>
                    <span className={cn(
                      'text-[9px] px-1 py-[1px] rounded border font-medium leading-none',
                      statusCfg.cls
                    )}>
                      {statusCfg.label}
                    </span>
                  </div>
                </button>

                {/* Compare toggle — absolute top-right */}
                {isCompleted && (
                  <button
                    onClick={(e) => { e.stopPropagation(); onToggleComparison?.(b.jobId) }}
                    title={isCompared ? 'Remove from comparison' : 'Add to comparison'}
                    className={cn(
                      'absolute right-1 top-1/2 -translate-y-1/2 p-1.5 rounded transition-colors',
                      isCompared
                        ? 'text-emerald-400 hover:bg-emerald-500/10'
                        : 'text-gray-600 hover:text-gray-300 hover:bg-gray-800 opacity-0 group-hover:opacity-100'
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
      </div>

      {/* ── Pagination footer ── */}
      <div className="shrink-0 border-t border-slate-700/50 px-3 py-2 flex items-center justify-between">
        <span className="text-[10px] text-gray-500 font-mono">
          {totalItems === 0 ? 0 : (histPage - 1) * HIST_PER_PAGE + 1}–{Math.min(histPage * HIST_PER_PAGE, totalItems)} of {totalItems}
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setHistPage((p) => Math.max(1, p - 1))}
            disabled={histPage === 1}
            className="p-1 rounded text-gray-500 hover:text-gray-300 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            <ChevronLeft className="size-3.5" />
          </button>
          <span className="text-[10px] text-gray-500 font-mono min-w-[32px] text-center">
            {histPage}/{totalHistPages}
          </span>
          <button
            onClick={() => setHistPage((p) => Math.min(totalHistPages, p + 1))}
            disabled={histPage >= totalHistPages}
            className="p-1 rounded text-gray-500 hover:text-gray-300 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            <ChevronRight className="size-3.5" />
          </button>
        </div>
      </div>
    </div>
  )
}
