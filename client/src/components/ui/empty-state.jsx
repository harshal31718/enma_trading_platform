import { Inbox } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * Shared empty-state primitive: icon + title + description + optional action.
 * Use for any "no rows yet" table/list body instead of bare centered text.
 *
 * Props:
 *  - icon: lucide-react icon component (defaults to Inbox)
 *  - title: short headline (e.g. "No backtests yet")
 *  - description: supporting copy (optional)
 *  - action: { label, onClick } | ReactNode (optional CTA)
 *  - className: optional wrapper class
 */
export function EmptyState({ icon: Icon = Inbox, title, description, action, className }) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center text-center gap-2 py-12 px-4',
        className
      )}
    >
      <Icon size={28} className="text-slate-600 mb-1" aria-hidden="true" />
      <p className="text-sm font-medium text-slate-300">{title}</p>
      {description && <p className="text-xs text-slate-400 max-w-sm">{description}</p>}
      {action &&
        (typeof action === 'object' && 'label' in action ? (
          <button
            type="button"
            onClick={action.onClick}
            className="mt-2 inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium px-3 py-1.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
          >
            {action.label}
          </button>
        ) : (
          <div className="mt-2">{action}</div>
        ))}
    </div>
  )
}

export default EmptyState
