import { useState, useMemo } from 'react'
import { useStrategies } from '../../hooks/useStrategies'
import { useStrategyParams } from '../../hooks/useAlgoSessions'
import { useSymbols } from '../../hooks/useCandles'
import { useObjectives } from '../../hooks/useLab'
import ParamGridForm from './ParamGridForm'

const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d']

function _perFoldComboCount(paramGrid) {
  return Object.values(paramGrid || {}).reduce((acc, spec) => {
    let n
    if (spec.type === 'float') {
      n = Math.max(1, Math.round(spec.num || 1))
    } else {
      n = Math.max(1, Math.floor((spec.max - spec.min) / (spec.step || 1)) + 1)
    }
    return acc * n
  }, 1)
}

// Plan 10 Phase 3c §4.3.7 — walk-forward run wizard (Optimizer tab, "New
// Run ▸"). Strategy/symbol/TF/range mirrors NewBacktestWizard's own fields;
// the param grid is the new piece (ParamGridForm, auto-rendered from the
// PARAMS schema per the plan's own recommendation).
export default function WalkForwardWizard({ onRun, submitting }) {
  const { data: strategies = [], isLoading: loadingStrategies } = useStrategies()
  const { data: symbolData } = useSymbols()
  const symbolList = symbolData?.futures || []
  const { data: objectives = ['sharpe'] } = useObjectives()

  const [strategyId, setStrategyId] = useState('')
  const [exchange] = useState('Binance Futures') // only exchange currently supported (matches NewBacktestWizard's default)
  const [symbol, setSymbol] = useState('')
  const [timeframe, setTimeframe] = useState('1h')
  const [startDate, setStartDate] = useState('2023-01-01')
  const [endDate, setEndDate] = useState('2024-01-01')
  const [capital, setCapital] = useState('10000')
  const [leverage, setLeverage] = useState('10')
  const [objective, setObjective] = useState('sharpe')
  const [mode, setMode] = useState('rolling')
  const [nFolds, setNFolds] = useState(4)
  const [trainRatio, setTrainRatio] = useState(0.7)
  const [minTrades, setMinTrades] = useState(0)
  const [maxCombinations, setMaxCombinations] = useState(50)
  const [paramGrid, setParamGrid] = useState({})

  const { data: paramsSchema } = useStrategyParams(strategyId || null)

  const perFoldCombos = useMemo(() => _perFoldComboCount(paramGrid), [paramGrid])
  const cappedPerFold = Math.min(perFoldCombos, Number(maxCombinations) || 1)
  const estimatedBacktests = cappedPerFold * Number(nFolds) + Number(nFolds) // + 1 test backtest per fold

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!strategyId || !symbol || Object.keys(paramGrid).length === 0) return
    onRun({
      strategyId,
      exchange,
      symbol,
      timeframe,
      startDate,
      endDate,
      capital: Number(capital),
      leverage: Number(leverage),
      objective,
      mode,
      nFolds: Number(nFolds),
      trainRatio: Number(trainRatio),
      minTrades: Number(minTrades),
      maxCombinations: Number(maxCombinations),
      paramGrid,
    })
  }

  return (
    <form onSubmit={handleSubmit} className="border border-slate-800 bg-slate-950 p-4 space-y-3">
      <h3 className="text-[10px] font-bold uppercase tracking-wider text-slate-400">New Walk-Forward Run</h3>

      <div>
        <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block mb-1">Strategy</label>
        <select
          className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200"
          value={strategyId}
          onChange={(e) => setStrategyId(e.target.value)}
          disabled={loadingStrategies}
        >
          <option value="">-- Select strategy --</option>
          {strategies.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block mb-1">Symbol</label>
          <select
            className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
          >
            <option value="">--</option>
            {symbolList.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block mb-1">Timeframe</label>
          <select
            className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200"
            value={timeframe}
            onChange={(e) => setTimeframe(e.target.value)}
          >
            {TIMEFRAMES.map((tf) => <option key={tf} value={tf}>{tf}</option>)}
          </select>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block mb-1">Start date</label>
          <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)}
            className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200" />
        </div>
        <div>
          <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block mb-1">End date</label>
          <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)}
            className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200" />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block mb-1">Capital</label>
          <input type="number" value={capital} onChange={(e) => setCapital(e.target.value)}
            className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200" />
        </div>
        <div>
          <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block mb-1">Leverage</label>
          <input type="number" value={leverage} onChange={(e) => setLeverage(e.target.value)}
            className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200" />
        </div>
      </div>

      {strategyId && <ParamGridForm schema={paramsSchema} value={paramGrid} onChange={setParamGrid} />}

      <div>
        <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block mb-1">Objective</label>
        <select
          className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200"
          value={objective}
          onChange={(e) => setObjective(e.target.value)}
        >
          {objectives.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </div>

      <div>
        <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block mb-1">Fold mode</label>
        <div className="flex gap-2 text-xs font-mono">
          <button type="button" onClick={() => setMode('rolling')}
            className={`flex-1 py-1.5 border ${mode === 'rolling' ? 'border-emerald-500 text-emerald-400 bg-emerald-950/20' : 'border-slate-700 text-slate-400'}`}>
            Rolling
          </button>
          <button type="button" onClick={() => setMode('anchored')}
            className={`flex-1 py-1.5 border ${mode === 'anchored' ? 'border-emerald-500 text-emerald-400 bg-emerald-950/20' : 'border-slate-700 text-slate-400'}`}>
            Anchored
          </button>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <div>
          <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block mb-1">Folds</label>
          <input type="number" min={2} max={12} value={nFolds} onChange={(e) => setNFolds(e.target.value)}
            className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200" />
        </div>
        <div>
          <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block mb-1">Train ratio</label>
          <input type="number" min={0.1} max={0.9} step={0.05} value={trainRatio} onChange={(e) => setTrainRatio(e.target.value)}
            className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200" />
        </div>
        <div>
          <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block mb-1">Min trades</label>
          <input type="number" min={0} value={minTrades} onChange={(e) => setMinTrades(e.target.value)}
            className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200" />
        </div>
      </div>

      <div>
        <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block mb-1">
          Max combinations per fold (capped at 500 server-side)
        </label>
        <input type="number" min={1} max={500} value={maxCombinations} onChange={(e) => setMaxCombinations(e.target.value)}
          className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200" />
      </div>

      <div className="bg-slate-900/50 border border-slate-800 p-2 text-[10px] font-mono text-slate-400">
        Grid: {perFoldCombos.toLocaleString()} combos/fold
        {perFoldCombos > cappedPerFold && <span className="text-amber-400"> (capped to {cappedPerFold})</span>}
        {' '}× {nFolds} folds ≈ <span className="text-slate-200 font-bold">{estimatedBacktests.toLocaleString()} backtests</span> total.
        {estimatedBacktests > 1000 && (
          <p className="text-amber-400 mt-1">⚠ Large run — this may take several minutes.</p>
        )}
      </div>

      <button
        type="submit"
        disabled={!strategyId || !symbol || Object.keys(paramGrid).length === 0 || submitting}
        className="w-full bg-emerald-900/30 hover:bg-emerald-900/50 active:bg-emerald-900/60 disabled:opacity-40 disabled:cursor-not-allowed text-emerald-400 border border-emerald-800 py-2 px-4 font-mono text-xs uppercase tracking-wider"
      >
        {submitting ? 'Queuing…' : 'Run Walk-Forward Optimization'}
      </button>
    </form>
  )
}
