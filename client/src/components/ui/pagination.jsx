import { useState } from 'react'
import { ChevronsLeft, ChevronLeft, ChevronRight, ChevronsRight } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * Shared pagination control: First / Prev / page numbers (with ellipsis) / jump-to-page / Next / Last.
 * Fully keyboard/screen-reader accessible (aria-current, aria-label per control).
 *
 * Props:
 *  - page: current 1-indexed page
 *  - totalPages: total page count
 *  - onPageChange: (nextPage: number) => void
 *  - className: optional wrapper class
 */
export function Pagination({ page, totalPages, onPageChange, className }) {
  const [jumpValue, setJumpValue] = useState('')

  if (!totalPages || totalPages <= 1) return null

  const goTo = (p) => {
    const clamped = Math.min(Math.max(1, p), totalPages)
    if (clamped !== page) onPageChange(clamped)
  }

  function handleJumpSubmit(e) {
    e.preventDefault()
    const n = parseInt(jumpValue, 10)
    if (Number.isFinite(n)) goTo(n)
    setJumpValue('')
  }

  // Build a compact page list with ellipsis: first, last, current +-1
  const pages = []
  const addPage = (p) => pages.push(p)
  const windowStart = Math.max(2, page - 1)
  const windowEnd = Math.min(totalPages - 1, page + 1)

  addPage(1)
  if (windowStart > 2) pages.push('ellipsis-start')
  for (let p = windowStart; p <= windowEnd; p++) addPage(p)
  if (windowEnd < totalPages - 1) pages.push('ellipsis-end')
  if (totalPages > 1) addPage(totalPages)

  const iconBtnClass =
    'inline-flex items-center justify-center min-h-[36px] min-w-[36px] rounded-lg text-slate-400 hover:text-gray-100 hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500'

  return (
    <nav
      role="navigation"
      aria-label={`Page ${page} of ${totalPages}`}
      className={cn('flex items-center gap-1', className)}
    >
      <button
        type="button"
        onClick={() => goTo(1)}
        disabled={page <= 1}
        aria-label="First page"
        className={iconBtnClass}
      >
        <ChevronsLeft size={16} />
      </button>
      <button
        type="button"
        onClick={() => goTo(page - 1)}
        disabled={page <= 1}
        aria-label="Previous page"
        className={iconBtnClass}
      >
        <ChevronLeft size={16} />
      </button>

      <div className="flex items-center gap-1 mx-1">
        {pages.map((p, i) =>
          typeof p === 'number' ? (
            <button
              key={p}
              type="button"
              onClick={() => goTo(p)}
              aria-current={p === page ? 'page' : undefined}
              aria-label={`Page ${p}`}
              className={cn(
                'min-h-[36px] min-w-[36px] px-2 rounded-lg text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500',
                p === page
                  ? 'bg-emerald-400/10 text-emerald-400 border border-emerald-500/30'
                  : 'text-slate-400 hover:text-gray-100 hover:bg-slate-800'
              )}
            >
              {p}
            </button>
          ) : (
            <span key={`${p}-${i}`} className="px-1 text-slate-500" aria-hidden="true">
              &hellip;
            </span>
          )
        )}
      </div>

      <button
        type="button"
        onClick={() => goTo(page + 1)}
        disabled={page >= totalPages}
        aria-label="Next page"
        className={iconBtnClass}
      >
        <ChevronRight size={16} />
      </button>
      <button
        type="button"
        onClick={() => goTo(totalPages)}
        disabled={page >= totalPages}
        aria-label="Last page"
        className={iconBtnClass}
      >
        <ChevronsRight size={16} />
      </button>

      <form onSubmit={handleJumpSubmit} className="flex items-center gap-1 ml-2">
        <label htmlFor="pagination-jump" className="text-xs text-slate-400">
          Go to
        </label>
        <input
          id="pagination-jump"
          type="number"
          min={1}
          max={totalPages}
          value={jumpValue}
          onChange={(e) => setJumpValue(e.target.value)}
          placeholder={String(page)}
          aria-label="Jump to page"
          className="w-14 min-h-[36px] bg-[#0a0d13] border border-slate-700/50 rounded-lg px-2 text-sm text-gray-100 text-center focus:outline-none focus:border-emerald-500 transition-colors"
        />
      </form>
    </nav>
  )
}

export default Pagination
