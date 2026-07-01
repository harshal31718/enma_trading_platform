import { ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react'
import { cn } from '@/lib/utils'

export function Table({ className, wrapperClassName, ...props }) {
  return (
    <div className={cn("relative w-full overflow-auto", wrapperClassName)}>
      <table
        className={cn('w-full caption-bottom text-sm text-gray-100', className)}
        {...props}
      />
    </div>
  )
}

export function TableHeader({ className, ...props }) {
  return <thead className={cn('[&_tr]:border-b border-slate-700/50', className)} {...props} />
}

export function TableBody({ className, ...props }) {
  return (
    <tbody
      className={cn('[&_tr:last-child]:border-0', className)}
      {...props}
    />
  )
}

export function TableRow({ className, ...props }) {
  return (
    <tr
      className={cn(
        'h-11 border-b border-slate-700/30 transition-colors hover:bg-slate-800/20 data-[state=selected]:bg-slate-800/40',
        className
      )}
      {...props}
    />
  )
}

export function TableHead({ className, ...props }) {
  return (
    <th
      className={cn(
        'h-11 px-4 text-left align-middle text-[10px] font-semibold uppercase tracking-wider text-gray-400 [&:has([role=checkbox])]:pr-0 [&>[role=checkbox]]:translate-y-[2px]',
        className
      )}
      {...props}
    />
  )
}

/**
 * TableHead variant that toggles sort direction and exposes aria-sort.
 * sortKey: the field name this header controls
 * sortState: { key, dir: 'asc'|'desc' } | null -- the table's current sort
 * onSort: (key) => void -- caller flips asc/desc/none for that key
 */
export function SortableHeader({ className, children, sortKey, sortState, onSort, ...props }) {
  const active = sortState?.key === sortKey
  const dir = active ? sortState.dir : 'none'
  const ariaSort = active ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'
  const Icon = active ? (dir === 'asc' ? ChevronUp : ChevronDown) : ChevronsUpDown

  return (
    <TableHead aria-sort={ariaSort} className={className} {...props}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={cn(
          'inline-flex items-center gap-1 uppercase tracking-wider text-[10px] font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 rounded',
          active ? 'text-emerald-400' : 'text-gray-400 hover:text-gray-200'
        )}
        aria-label={`Sort by ${typeof children === 'string' ? children : sortKey}${active ? `, currently ${dir === 'asc' ? 'ascending' : 'descending'}` : ''}`}
      >
        {children}
        <Icon size={12} className="shrink-0" aria-hidden="true" />
      </button>
    </TableHead>
  )
}

export function TableCell({ className, ...props }) {
  return (
    <td
      className={cn(
        'px-4 py-2 align-middle [&:has([role=checkbox])]:pr-0 [&>[role=checkbox]]:translate-y-[2px]',
        className
      )}
      {...props}
    />
  )
}
