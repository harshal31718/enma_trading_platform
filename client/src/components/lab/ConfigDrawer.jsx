import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

// Plan 10 Phase 2 §4.2.7 — read-only config drawer for a done run: every
// knob + seed + engineVersion, so any result is independently reproducible.
export default function ConfigDrawer({ config, meta, labId, sourceJobId }) {
  const [open, setOpen] = useState(false)

  const rows = [
    ['labId', labId],
    ['sourceJobId', sourceJobId],
    ['mode', config?.mode],
    ['runs', config?.runs],
    ['blockLen', config?.blockLen ?? (meta?.blockLength ?? 'auto (√N)')],
    ['ruinThresholdPct', config?.ruinThresholdPct],
    ['seed', config?.seed ?? meta?.seed],
    ['nTrades', meta?.nTrades],
    ['scaleOutLegsExcluded', meta?.scaleOutLegsExcluded],
  ]

  return (
    <div className="border border-slate-800 bg-slate-950">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-2 text-[10px] font-bold uppercase tracking-wider text-slate-400 hover:text-slate-200"
      >
        <span>Run config (reproducibility)</span>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </button>
      {open && (
        <div className="px-4 pb-3 grid grid-cols-2 gap-x-4 gap-y-1 text-[10px] font-mono">
          {rows.map(([k, v]) => (
            <div key={k} className="flex justify-between border-b border-slate-900/60 py-0.5">
              <span className="text-slate-500">{k}</span>
              <span className="text-slate-300">{v ?? '—'}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
