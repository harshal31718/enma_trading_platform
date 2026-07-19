import { useState, useMemo } from 'react'
import { useStrategies } from '../../hooks/useStrategies'
import { useStrategyParams } from '../../hooks/useAlgoSessions'
import { useSymbols } from '../../hooks/useCandles'
import { useObjectives } from '../../hooks/useLab'
import ParamGridForm from './ParamGridForm'

const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d']

function _comboCount(paramGrid) {
  return Object.values(paramGrid || {}).reduce((acc, spec) => {
    let n
    if (spec.values) {
      n = Math.max(1, spec.values.length)
    } else if (spec.type === 'float') {
      n = Math.max(1, Math.round(spec.num || 1))
    } else {
      n = Math.max(1, Math.floor((spec.max - spec.min) / (spec.step || 1)) + 1)
    }
    return acc * n
  }, 1)
}

// Plan 10 — PBO (Probability of Backtest Overfitting) run wizard, the "Overfitting (PBO)" tab.
// Deliberately NOT a walk-forward wizard clone with fields removed — PBO runs ONE full-date-range
// optimization pass (same paramGrid/riskLeverageGrid/method shape as WalkForwardWizard, for a
// consistent mental model) and subsamples the result into CSCV blocks itself; there is no
// mode/nFolds/trainRatio here because PBO doesn't do walk-forward's sequential fold splitting at
// all (see `engine/services/pbo.py`'s own docstring for why).
export default function PBOWizard({ onRun, submitting }) {
  const { data: strategies = [], isLoading: loadingStrategies } = useStrategies()
  const { data: symbolData } = useSymbols()
  const symbolList = symbolData?.futures || []
  const { data: objectives = ['sharpe'] } = useObjectives()

  const [strategyId, setStrategyId] = useState('')
  const [exchange] = useState('Binance Futures')
  const [symbol, setSymbol] = useState('')
  const [timeframe, setTimeframe] = useState('1h')
  const [startDate, setStartDate] = useState('2023-01-01')
  const [endDate, setEndDate] = useState('2024-01-01')
  const [capital, setCapital] = useState('10000')
  const [leverage, setLeverage] = useState('10')
  const [objective, setObjective] = useState('sharpe')
  const [minTrades, setMinTrades] = useState(0)
  const [maxCombinations, setMaxCombinations] = useState(50)
  const [method, setMethod] = useState('grid')
  const [nTrials, setNTrials] = useState(50)
  const [nBlocks, setNBlocks] = useState(8)
  const [paramGrid, setParamGrid] = useState({})

  const [riskLeverageSearch, setRiskLeverageSearch] = useState(false)
  const [riskPctMin, setRiskPctMin] = useState('1')
  const [riskPctMax, setRiskPctMax] = useState('3')
  const [riskPctSteps, setRiskPctSteps] = useState('3')
  const [leverageMin, setLeverageMin] = useState('5')
  const [leverageMax, setLeverageMax] = useState('20')
  const [leverageStep, setLeverageStep] = useState('5')

  const { data: paramsSchema } = useStrategyParams(strategyId || null)

  const riskLeverageGrid = useMemo(() => {
    if (!riskLeverageSearch) return undefined
    return {
      risk_pct: { min: Number(riskPctMin) / 100, max: Number(riskPctMax) / 100, num: Math.max(1, Number(riskPctSteps) || 1), type: 'float' },
      leverage: { min: Number(leverageMin), max: Number(leverageMax), step: Math.max(1, Number(leverageStep) || 1), type: 'int' },
    }
  }, [riskLeverageSearch, riskPctMin, riskPctMax, riskPctSteps, leverageMin, leverageMax, leverageStep])

  const strategyGridCombos = useMemo(() => _comboCount(paramGrid), [paramGrid])
  const riskLeverageCombos = useMemo(() => (riskLeverageGrid ? _comboCount(riskLeverageGrid) : 1), [riskLeverageGrid])
  const totalCombos = strategyGridCombos * riskLeverageCombos
  const nCandidates = method === 'bayesian' ? Number(nTrials) || 1 : Math.min(totalCombos, Number(maxCombinations) || 1)
  const half = Math.floor(Number(nBlocks) / 2)
  // C(n,k) — small values only (nBlocks is capped at 12 server+engine-side), plain product/factorial-free formula
  const nCombinations = (() => {
    let result = 1
    for (let i = 0; i < half; i++) result = (result * (Number(nBlocks) - i)) / (i + 1)
    return Math.round(result)
  })()

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
      minTrades: Number(minTrades),
      maxCombinations: Number(maxCombinations),
      method,
      nTrials: method === 'bayesian' ? Number(nTrials) : undefined,
      nBlocks: Number(nBlocks),
      paramGrid,
      riskLeverageGrid,
    })
  }

  return (
    <form onSubmit={handleSubmit} className="border border-slate-800 bg-slate-950 p-4 space-y-3">
      <h3 className="text-[10px] font-bold uppercase tracking-wider text-slate-400">New PBO Run</h3>
      <p className="text-[9px] text-slate-500">
        One full-date-range optimization pass, then Combinatorially Symmetric Cross-Validation
        (CSCV) over the candidates' own trades — reports the probability that the in-sample-best
        candidate is just noise, not a genuine edge.
      </p>

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

      <div className="grid grid-cols-2 gap-2">
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
          <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block mb-1">Min trades</label>
          <input type="number" min={0} value={minTrades} onChange={(e) => setMinTrades(e.target.value)}
            className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200" />
        </div>
      </div>

      <div>
        <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block mb-1">Search method</label>
        <div className="flex gap-2 text-xs font-mono">
          <button type="button" onClick={() => setMethod('grid')}
            className={`flex-1 py-1.5 border ${method === 'grid' ? 'border-emerald-500 text-emerald-400 bg-emerald-950/20' : 'border-slate-700 text-slate-400'}`}>
            Grid
          </button>
          <button type="button" onClick={() => setMethod('bayesian')}
            className={`flex-1 py-1.5 border ${method === 'bayesian' ? 'border-emerald-500 text-emerald-400 bg-emerald-950/20' : 'border-slate-700 text-slate-400'}`}>
            Bayesian (TPE)
          </button>
        </div>
      </div>

      {method === 'grid' ? (
        <div>
          <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block mb-1">
            Max candidates (capped at 500 server-side)
          </label>
          <input type="number" min={2} max={500} value={maxCombinations} onChange={(e) => setMaxCombinations(e.target.value)}
            className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200" />
        </div>
      ) : (
        <div>
          <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block mb-1">
            Candidates / trials (capped at 500 server-side)
          </label>
          <input type="number" min={2} max={500} value={nTrials} onChange={(e) => setNTrials(e.target.value)}
            className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200" />
        </div>
      )}

      <div>
        <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block mb-1">
          CSCV blocks (even, capped at 12 server-side)
        </label>
        <input type="number" min={4} max={12} step={2} value={nBlocks} onChange={(e) => setNBlocks(e.target.value)}
          className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200" />
        <p className="text-[9px] text-slate-500 mt-1">
          The full date range is split into this many contiguous blocks; every {half}-vs-{half}{' '}
          train/test split ({nCombinations.toLocaleString()} combinations) is scored in-memory — no
          extra backtests beyond the {nCandidates.toLocaleString()} candidates above.
        </p>
      </div>

      <div className="border border-slate-800 p-2">
        <label className="flex items-center gap-2 text-xs font-mono text-slate-300">
          <input type="checkbox" checked={riskLeverageSearch} onChange={(e) => setRiskLeverageSearch(e.target.checked)} className="accent-emerald-500" />
          Search risk_pct / leverage too
        </label>
        <p className="text-[9px] text-slate-500 mt-1">
          Multiplies the param grid above by every risk_pct × leverage combination below — each
          candidate is backtested at its own searched risk_pct/leverage, not the fixed
          Capital/Leverage fields above (those still apply when this is off).
        </p>
        {riskLeverageSearch && (
          <div className="mt-2 space-y-2">
            <div>
              <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block mb-1">
                Risk % / trade — min / max / steps
              </label>
              <div className="grid grid-cols-3 gap-2">
                <input type="number" step="0.1" value={riskPctMin} onChange={(e) => setRiskPctMin(e.target.value)}
                  className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200" />
                <input type="number" step="0.1" value={riskPctMax} onChange={(e) => setRiskPctMax(e.target.value)}
                  className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200" />
                <input type="number" min={1} value={riskPctSteps} onChange={(e) => setRiskPctSteps(e.target.value)}
                  className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200" />
              </div>
            </div>
            <div>
              <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block mb-1">
                Leverage — min / max / step
              </label>
              <div className="grid grid-cols-3 gap-2">
                <input type="number" min={1} max={125} value={leverageMin} onChange={(e) => setLeverageMin(e.target.value)}
                  className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200" />
                <input type="number" min={1} max={125} value={leverageMax} onChange={(e) => setLeverageMax(e.target.value)}
                  className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200" />
                <input type="number" min={1} value={leverageStep} onChange={(e) => setLeverageStep(e.target.value)}
                  className="bg-slate-900 border border-slate-700 w-full px-2 py-1.5 outline-none focus:border-emerald-500 text-xs font-mono text-slate-200" />
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="bg-slate-900/50 border border-slate-800 p-2 text-[10px] font-mono text-slate-400">
        {method === 'grid' ? (
          <>Grid: {totalCombos.toLocaleString()} combos{totalCombos > nCandidates && <span className="text-amber-400"> (capped to {nCandidates})</span>}</>
        ) : (
          <>Bayesian: {nCandidates.toLocaleString()} TPE trials (of {totalCombos.toLocaleString()} possible combos)</>
        )}
        {' '}≈ <span className="text-slate-200 font-bold">{nCandidates.toLocaleString()} backtests</span> total —
        CSCV combinatorics ({nCombinations.toLocaleString()} splits) run entirely in-memory, no extra cost.
        {nCandidates > 200 && (
          <p className="text-amber-400 mt-1">⚠ Large run — this may take several minutes.</p>
        )}
      </div>

      <button
        type="submit"
        disabled={!strategyId || !symbol || Object.keys(paramGrid).length === 0 || submitting}
        className="w-full bg-emerald-900/30 hover:bg-emerald-900/50 active:bg-emerald-900/60 disabled:opacity-40 disabled:cursor-not-allowed text-emerald-400 border border-emerald-800 py-2 px-4 font-mono text-xs uppercase tracking-wider"
      >
        {submitting ? 'Queuing…' : 'Run PBO'}
      </button>
    </form>
  )
}
