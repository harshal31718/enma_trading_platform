// Plan 7 Step 7.4 (CLI-1): shared skeleton/empty/warning row helpers used by
// every Trade-page table (Positions, Open Orders, Assets, Order/Trade/
// Transaction History). Extracted out of Trade.jsx alongside the tables
// themselves.
import EmptyState from '@/components/ui/empty-state'

export function SkeletonRow({ cols }) {
  return (
    <tr>
      {cols.map((_, i) => (
        <td key={i} className={`py-2 pr-4 ${i === 0 ? 'pl-2' : ''}`}>
          <div className="h-3 bg-slate-800/50 rounded w-full animate-pulse" />
        </td>
      ))}
    </tr>
  )
}

export function EmptyRow({ message }) {
  return (
    <tr>
      <td colSpan={99} className="py-2 text-center text-slate-400 text-xs">
        <EmptyState
          title={message}
          className="py-4"
        />
      </td>
    </tr>
  )
}

export const SyncWarningBanner = () => (
  <div className="bg-yellow-950/20 border border-yellow-800/40 rounded px-3 py-1.5 text-[10px] text-yellow-400 mb-2 mt-1">
    Warning: Connection to the Strategy Engine failed. Displaying cached/offline data.
  </div>
)
