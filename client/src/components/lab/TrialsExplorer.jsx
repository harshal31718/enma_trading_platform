// Plan 10 Phase 3d (remainder) — renders `fold.trials`, the real per-combo
// list every fold's train-window grid search actually scored (engine-side
// persistence shipped 2026-07-19). Deliberately NOT an "IS-vs-OOS scatter":
// only the winning combo per fold gets evaluated out-of-sample
// (`oosMetrics`), so every other trial here has IS-only metrics — plotting
// them against a nonexistent OOS value would fabricate data. What IS real
// and shown here: a sortable trials table, and — when the grid varies
// exactly two params — a loss heatmap over that 2D grid (both computed
// purely from each trial's own training-window numbers).
import { Fragment, useMemo, useState } from 'react'

function paramKeys(trials) {
  const keys = new Set()
  trials.forEach((t) => Object.keys(t.params || {}).forEach((k) => keys.add(k)))
  return Array.from(keys)
}

function TrialsTable({ trials }) {
  const [sortKey, setSortKey] = useState('rank')
  const keys = paramKeys(trials)
  // Plan 10 Phase 4b (risk_pct/leverage search) — extra columns only appear
  // when this run actually searched risk_pct/leverage (any trial carries a
  // non-empty `riskLeverage`); a run that didn't opt in renders identically
  // to before this feature existed.
  const hasRiskLeverage = trials.some((t) => t.riskLeverage && Object.keys(t.riskLeverage).length > 0)

  const sorted = useMemo(() => {
    const copy = [...trials]
    copy.sort((a, b) => {
      if (sortKey === 'rank') return (a.rank ?? Infinity) - (b.rank ?? Infinity)
      if (sortKey === 'loss') return (a.loss ?? Infinity) - (b.loss ?? Infinity)
      return 0
    })
    return copy
  }, [trials, sortKey])

  return (
    <div className="border border-slate-800 bg-slate-950 overflow-x-auto max-h-80 overflow-y-auto">
      <table className="w-full text-xs font-mono text-left min-w-[520px]">
        <thead className="sticky top-0 bg-slate-950">
          <tr className="border-b border-slate-800 text-[10px] text-slate-400 uppercase tracking-wider">
            <th className="p-2 cursor-pointer hover:text-slate-200" onClick={() => setSortKey('rank')}>Rank</th>
            {keys.map((k) => <th key={k} className="p-2">{k}</th>)}
            {hasRiskLeverage && <th className="p-2 text-right">Risk %</th>}
            {hasRiskLeverage && <th className="p-2 text-right">Leverage</th>}
            <th className="p-2 text-right">IS Sharpe</th>
            <th className="p-2 text-right">IS Net Profit%</th>
            <th className="p-2 text-right">IS Trades</th>
            <th className="p-2 text-right cursor-pointer hover:text-slate-200" onClick={() => setSortKey('loss')}>Loss</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((t, i) => (
            <tr key={i} className="border-b border-slate-900/60 hover:bg-slate-900/40">
              <td className="p-2 text-slate-300 font-bold">{t.rank ?? '—'}</td>
              {keys.map((k) => (
                <td key={k} className="p-2 text-slate-400">{t.params?.[k] ?? '—'}</td>
              ))}
              {hasRiskLeverage && (
                <td className="p-2 text-right text-slate-400">
                  {t.riskLeverage?.risk_pct != null ? `${(t.riskLeverage.risk_pct * 100).toFixed(2)}%` : '—'}
                </td>
              )}
              {hasRiskLeverage && (
                <td className="p-2 text-right text-slate-400">
                  {t.riskLeverage?.leverage != null ? `${t.riskLeverage.leverage}x` : '—'}
                </td>
              )}
              <td className="p-2 text-right text-slate-300">{t.metrics?.sharpeRatio ?? '—'}</td>
              <td className="p-2 text-right text-slate-300">{t.metrics?.netProfitPct ?? '—'}</td>
              <td className="p-2 text-right text-slate-400">{t.metrics?.totalTrades ?? '—'}</td>
              <td className="p-2 text-right text-slate-500">{Number.isFinite(t.loss) ? t.loss.toFixed(4) : t.error ? 'error' : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// Sequential single-hue ramp (emerald, matching this app's "better = more
// emerald" convention) over normalized rank — best trial full opacity,
// worst trial faint. Only rendered when the grid varies exactly 2 params,
// since a heatmap needs exactly 2 axes.
function ParamHeatmap({ trials, paramA, paramB }) {
  const valsA = [...new Set(trials.map((t) => t.params?.[paramA]))].sort((a, b) => a - b)
  const valsB = [...new Set(trials.map((t) => t.params?.[paramB]))].sort((a, b) => a - b)
  const maxRank = Math.max(...trials.map((t) => t.rank ?? 0), 1)

  const cellFor = (a, b) => trials.find((t) => t.params?.[paramA] === a && t.params?.[paramB] === b)

  return (
    <div className="border border-slate-800 bg-slate-950 p-3">
      <div className="text-[10px] text-slate-400 uppercase tracking-wider mb-2 font-mono">
        Loss landscape — {paramA} × {paramB} (train window, greener = better rank)
      </div>
      <div
        className="grid gap-0.5"
        style={{ gridTemplateColumns: `auto repeat(${valsB.length}, minmax(0, 1fr))` }}
      >
        <div />
        {valsB.map((b) => (
          <div key={b} className="text-[9px] font-mono text-slate-400 text-center p-1">{b}</div>
        ))}
        {valsA.map((a) => (
          <Fragment key={a}>
            <div className="text-[9px] font-mono text-slate-400 flex items-center p-1">{a}</div>
            {valsB.map((b) => {
              const cell = cellFor(a, b)
              const rank = cell?.rank ?? maxRank
              const opacity = Math.round((1 - (rank - 1) / Math.max(maxRank - 1, 1)) * 90)
              return (
                <div
                  key={`${a}-${b}`}
                  className="aspect-square flex items-center justify-center text-[9px] font-mono m-0.5 border border-slate-800/10 text-slate-950"
                  style={{ backgroundColor: cell ? `hsla(158, 70%, 45%, ${opacity / 100})` : 'transparent' }}
                  title={cell ? `${paramA}=${a}, ${paramB}=${b}: rank ${rank}, loss ${cell.loss?.toFixed(4)}` : 'no trial'}
                >
                  {cell ? `#${rank}` : '—'}
                </div>
              )
            })}
          </Fragment>
        ))}
      </div>
    </div>
  )
}

export default function TrialsExplorer({ folds }) {
  const eligibleFolds = (folds || []).filter((f) => (f.trials?.length ?? 0) > 0)
  const [foldIdx, setFoldIdx] = useState(0)

  if (eligibleFolds.length === 0) return null

  const fold = eligibleFolds[Math.min(foldIdx, eligibleFolds.length - 1)]
  const keys = paramKeys(fold.trials)

  return (
    <div className="border border-slate-800 bg-slate-950 p-3 space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-[10px] text-slate-400 uppercase tracking-wider font-mono">
          Trials — fold {fold.fold} ({fold.trials.length} combo{fold.trials.length === 1 ? '' : 's'} scored on the train window)
        </div>
        {eligibleFolds.length > 1 && (
          <div className="flex gap-1">
            {eligibleFolds.map((f, i) => (
              <button
                key={f.fold}
                onClick={() => setFoldIdx(i)}
                className={`px-2 py-0.5 text-[10px] font-mono border ${
                  i === foldIdx
                    ? 'border-emerald-500 text-emerald-400 bg-emerald-400/10'
                    : 'border-slate-700 text-slate-400 hover:border-slate-500'
                }`}
              >
                Fold {f.fold}
              </button>
            ))}
          </div>
        )}
      </div>
      <TrialsTable trials={fold.trials} />
      {keys.length === 2 && <ParamHeatmap trials={fold.trials} paramA={keys[0]} paramB={keys[1]} />}
    </div>
  )
}
