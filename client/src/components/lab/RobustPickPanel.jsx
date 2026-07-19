import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useStrategies } from '../../hooks/useStrategies'

// Plan 10 §2.3 — "the piece that makes the name 'Monte Carlo optimiser'
// accurate": instead of ranking a fold's winner by raw point-estimate loss
// alone, `_mc_score_fold` (engine, Phase 4a) OOS-evaluates the fold's top-K
// min-trades-eligible trials and re-ranks them by Monte Carlo p5 profit
// outcome. Only rendered when a run opted in (`config.mcScoring`) — off by
// default, so most runs won't show this panel at all.
//
// Phase 4b (§4.3 item 5, "Robust-pick card... copy-to-backtest action"):
// `config` (the optimization job's persisted `LabResult.config` — strategyFile/
// symbol/timeframe/exchange) is optional and additive. Without it the panel
// still renders exactly as before; with it, the robust pick gains a
// "Copy to Backtest" deep link. Resolves `config.strategyFile` (a filePath,
// e.g. "strategies/AdaptiveTrend" — what the engine/optimizer persists, NOT
// a Mongo strategyId) against `useStrategies()` client-side, same join key
// `NewBacktestWizard`/`Backtest.jsx` already use — no server change needed.
function formatParams(params) {
  return Object.entries(params || {}).map(([k, v]) => `${k}=${v}`).join(', ')
}

// Plan 10 Phase 4b (risk_pct/leverage search) — appended after the strategy
// params when a candidate carries a `riskLeverage` sub-object (only true for
// runs that opted into the search; every other run's candidates render
// exactly as before, since `riskLeverage` is `null`/absent there).
function formatRiskLeverage(riskLeverage) {
  if (!riskLeverage) return ''
  const parts = []
  if (riskLeverage.risk_pct != null) parts.push(`risk=${(riskLeverage.risk_pct * 100).toFixed(2)}%`)
  if (riskLeverage.leverage != null) parts.push(`lev=${riskLeverage.leverage}x`)
  return parts.length ? ` (${parts.join(', ')})` : ''
}

function CandidateRow({ candidate, isRobustPick, isRawPick }) {
  const p5 = candidate.mc?.p5ProfitPct
  const gap = candidate.fragilityGap
  return (
    <tr className={`border-b border-slate-900/60 ${isRobustPick ? 'bg-emerald-950/10' : ''}`}>
      <td className="p-2 text-slate-300 font-bold">
        #{candidate.rank}
        {isRawPick && <span className="ml-1 text-[9px] text-slate-500 uppercase">raw pick</span>}
        {isRobustPick && <span className="ml-1 text-[9px] text-emerald-400 uppercase">robust pick</span>}
      </td>
      <td className="p-2 text-slate-400">
        {formatParams(candidate.params)}
        <span className="text-slate-500">{formatRiskLeverage(candidate.riskLeverage)}</span>
      </td>
      <td className="p-2 text-right text-slate-300">{candidate.oosMetrics?.netProfitPct ?? '—'}%</td>
      <td className="p-2 text-right text-slate-400">{candidate.oosTradeCount}</td>
      <td className="p-2 text-right text-slate-300">
        {candidate.insufficientData ? '—' : `${p5?.toFixed(2)}%`}
      </td>
      <td className={`p-2 text-right font-bold ${gap == null ? 'text-slate-500' : gap > 5 ? 'text-amber-400' : 'text-slate-300'}`}>
        {candidate.insufficientData || gap == null ? '—' : `${gap >= 0 ? '+' : ''}${gap.toFixed(1)}pt`}
      </td>
    </tr>
  )
}

export default function RobustPickPanel({ folds, config }) {
  const eligibleFolds = (folds || []).filter((f) => f.mcScoring?.enabled)
  const [foldIdx, setFoldIdx] = useState(0)
  const navigate = useNavigate()
  const { data: strategies = [] } = useStrategies()

  if (eligibleFolds.length === 0) return null

  const fold = eligibleFolds[Math.min(foldIdx, eligibleFolds.length - 1)]
  const scoring = fold.mcScoring
  const robustRank = scoring.robustPick?.rank
  const rawRank = scoring.rawPick?.rank
  const picksDiffer = robustRank != null && rawRank != null && robustRank !== rawRank

  const matchedStrategy = config?.strategyFile
    ? strategies.find((s) => s.filePath === config.strategyFile)
    : null

  const handleCopyToBacktest = () => {
    if (!matchedStrategy || !scoring.robustPick) return
    // Prefixed `prefill*` names deliberately — Backtest.jsx's history-filter
    // UI already owns bare `symbol`/`timeframe` query params for list
    // filtering; reusing those names here would silently corrupt that filter
    // state instead of seeding the wizard.
    const qsFields = {
      prefillStrategyId: matchedStrategy.id,
      prefillSymbol: config.symbol || '',
      prefillTimeframe: config.timeframe || '',
      prefillExchange: config.exchange || '',
      prefillParams: JSON.stringify(scoring.robustPick.params),
    }
    // Phase 4b (risk_pct/leverage search): carry the robust pick's OWN
    // searched risk_pct/leverage forward too, when this run searched them —
    // otherwise a robust pick that won because of a specific leverage would
    // silently lose that half of its identity on the way to the backtest
    // wizard, which only ever seeds strategy params without this.
    const rl = scoring.robustPick.riskLeverage
    if (rl?.leverage != null) qsFields.prefillLeverage = String(rl.leverage)
    if (rl?.risk_pct != null) qsFields.prefillRiskPct = String(rl.risk_pct * 100) // wizard's risk field is a percentage

    const qs = new URLSearchParams(qsFields)
    navigate(`/backtest?${qs.toString()}`)
  }

  return (
    <div className="border border-slate-800 bg-slate-950 p-3 space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-[10px] text-slate-400 uppercase tracking-wider font-mono">
          MC-scored picks — fold {fold.fold} (top {scoring.topK} candidates, {scoring.runsPerCandidate.toLocaleString()} MC runs each)
        </div>
        <div className="flex items-center gap-2">
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
          {scoring.robustPick && (
            <button
              onClick={handleCopyToBacktest}
              disabled={!matchedStrategy}
              title={
                matchedStrategy
                  ? 'Open a new backtest pre-filled with the MC-robust pick\'s params'
                  : 'Strategy for this run could not be matched (renamed/removed?) — cannot pre-fill'
              }
              className="px-2 py-0.5 text-[10px] font-mono border border-emerald-700/60 text-emerald-400 hover:border-emerald-500 hover:bg-emerald-400/10 disabled:border-slate-800 disabled:text-slate-600 disabled:cursor-not-allowed transition-colors"
            >
              Copy robust pick → Backtest
            </button>
          )}
        </div>
      </div>

      {picksDiffer ? (
        <div className="border border-amber-800/40 bg-amber-950/10 px-3 py-2 text-xs font-mono text-slate-200">
          The MC-robust pick (#{robustRank}) differs from the raw point-estimate winner (#{rawRank}) —
          the raw winner's edge has a wider downside tail than a lower-ranked candidate's, a
          fragility gap a single loss/Sharpe number hides.
        </div>
      ) : (
        <div className="border border-slate-800 bg-slate-900/40 px-3 py-2 text-xs font-mono text-slate-400">
          The MC-robust pick agrees with the raw point-estimate winner for this fold — no fragility
          gap detected among the top {scoring.topK} candidates.
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-xs font-mono text-left min-w-[640px]">
          <thead>
            <tr className="border-b border-slate-800 text-[10px] text-slate-400 uppercase tracking-wider">
              <th className="p-2">Rank</th>
              <th className="p-2">Params</th>
              <th className="p-2 text-right">OOS net profit%</th>
              <th className="p-2 text-right">OOS trades</th>
              <th className="p-2 text-right" title="5th-percentile final-equity return from a block-bootstrap of this candidate's OOS trades">MC p5 profit%</th>
              <th className="p-2 text-right" title="Point-estimate OOS profit minus MC-p5 profit — the gap a raw metric hides">Fragility gap</th>
            </tr>
          </thead>
          <tbody>
            {scoring.candidates.map((c) => (
              <CandidateRow
                key={c.rank}
                candidate={c}
                isRawPick={c.rank === rawRank}
                isRobustPick={c.rank === robustRank}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
