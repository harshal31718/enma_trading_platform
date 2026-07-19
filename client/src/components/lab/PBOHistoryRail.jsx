import { CheckCircle2, XCircle, Loader2, Clock } from 'lucide-react'
import { usePBOList } from '../../hooks/useLab'

const STATUS_ICON = {
  queued: <Clock size={12} className="text-slate-500" />,
  running: <Loader2 size={12} className="text-amber-400 animate-spin" />,
  completed: <CheckCircle2 size={12} className="text-emerald-400" />,
  failed: <XCircle size={12} className="text-red-400" />,
}

// Mirrors OptimizationHistoryRail.jsx exactly — PBO runs aren't scoped to a source backtest,
// lists the user's most recent runs globally.
export default function PBOHistoryRail({ selectedLabId, onSelect }) {
  const { data: labs, isLoading } = usePBOList()

  return (
    <div className="border border-slate-800 bg-slate-950 p-3">
      <h3 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">Run history</h3>
      {isLoading && <p className="text-[10px] text-slate-500 font-mono italic">Loading…</p>}
      {!isLoading && (!labs || labs.length === 0) && (
        <p className="text-[10px] text-slate-600 font-mono italic">No runs yet.</p>
      )}
      <div className="flex flex-col gap-1 max-h-72 overflow-y-auto">
        {labs?.map((l) => (
          <button
            key={l.labId}
            onClick={() => onSelect(l.labId)}
            className={`flex items-center gap-2 px-2 py-1.5 text-left text-[10px] font-mono border ${
              selectedLabId === l.labId ? 'border-emerald-700 bg-emerald-950/20' : 'border-transparent hover:bg-slate-900/60'
            }`}
          >
            {STATUS_ICON[l.status] || <Clock size={12} className="text-slate-500" />}
            <span className="text-slate-300 truncate flex-1">
              {l.config?.symbol || '—'} · {l.config?.nBlocks || '—'} blocks
            </span>
            <span className="text-slate-600">{new Date(l.createdAt).toLocaleTimeString()}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
