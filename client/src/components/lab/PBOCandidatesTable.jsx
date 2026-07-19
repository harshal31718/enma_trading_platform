import { useState, useMemo } from 'react'

// Plan 10 — PBO candidates table. Mirrors TrialsExplorer.jsx's TrialsTable shape (sortable,
// dynamic param columns) without the fold-switcher/heatmap — PBO has one flat candidate list,
// not per-fold trials.
export default function PBOCandidatesTable({ candidates }) {
  const [sortKey, setSortKey] = useState('rank')

  const paramKeys = useMemo(() => {
    const keys = new Set()
    candidates?.forEach((c) => Object.keys(c.params || {}).forEach((k) => keys.add(k)))
    return Array.from(keys)
  }, [candidates])

  const sorted = useMemo(() => {
    if (!candidates) return []
    return [...candidates].sort((a, b) => {
      const av = sortKey === 'rank' ? a.rank : a.metrics?.[sortKey]
      const bv = sortKey === 'rank' ? b.rank : b.metrics?.[sortKey]
      if (av === undefined || av === null) return 1
      if (bv === undefined || bv === null) return -1
      return Number(av) - Number(bv)
    })
  }, [candidates, sortKey])

  if (!candidates || candidates.length === 0) {
    return <p className="text-[10px] text-slate-600 font-mono italic">No candidates.</p>
  }

  const thCls = 'px-2 py-1.5 text-left text-[9px] uppercase tracking-wider text-slate-400 font-semibold cursor-pointer hover:text-slate-200'

  return (
    <div className="border border-slate-800 bg-slate-950 overflow-x-auto max-h-80 overflow-y-auto">
      <table className="w-full text-[10px] font-mono">
        <thead className="sticky top-0 bg-slate-950 border-b border-slate-800">
          <tr>
            <th className={thCls} onClick={() => setSortKey('rank')}>Rank</th>
            {paramKeys.map((k) => <th key={k} className={thCls}>{k}</th>)}
            <th className={thCls} onClick={() => setSortKey('sharpeRatio')}>Full-Range Sharpe</th>
            <th className={thCls} onClick={() => setSortKey('netProfitPct')}>Net Profit%</th>
            <th className={thCls}>Total Trades</th>
            <th className={thCls}>Unassigned</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((c) => (
            <tr key={c.rank} className="border-b border-slate-900 hover:bg-slate-900/40">
              <td className="px-2 py-1 text-slate-300">#{c.rank}</td>
              {paramKeys.map((k) => (
                <td key={k} className="px-2 py-1 text-slate-400">
                  {c.params?.[k] !== undefined ? String(c.params[k]) : '—'}
                </td>
              ))}
              <td className="px-2 py-1 text-slate-300">{c.metrics?.sharpeRatio ?? '—'}</td>
              <td className="px-2 py-1 text-slate-300">{c.metrics?.netProfitPct ?? '—'}</td>
              <td className="px-2 py-1 text-slate-300">{c.totalTrades ?? '—'}</td>
              <td className="px-2 py-1 text-slate-500">{c.unassignedTrades ?? 0}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
