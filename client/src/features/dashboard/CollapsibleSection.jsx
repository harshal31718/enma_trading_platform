import { useState } from 'react'
import { ChevronDown } from 'lucide-react'

// Demoted section wrapper — a toggle header over collapsible content. Default
// closed so operational tables (e.g. the TimescaleDB cache) don't crowd the
// trading-focused top of the dashboard. Design system: no rounded corners.
export default function CollapsibleSection({ title, meta, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="border-t border-slate-700/50">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="h-11 title-fade w-full px-4 flex items-center justify-between text-left hover:bg-slate-800/20 transition-colors"
      >
        <span className="text-gray-200 font-semibold text-sm">
          {title}
          {meta != null && <span className="text-slate-400 font-normal ml-2">· {meta}</span>}
        </span>
        <ChevronDown
          className={`size-4 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>
      {open && <div>{children}</div>}
    </div>
  )
}
