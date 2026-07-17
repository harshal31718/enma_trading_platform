import { useState, useEffect, useRef } from 'react'
import { ChevronRight, ChevronLeft, AlertTriangle, X } from 'lucide-react'
import { useStrategies } from '../../hooks/useStrategies'
import { useSymbols } from '../../hooks/useCandles'
import { useStrategyParams, useStartSession, useLockedSymbols } from '../../hooks/useAlgoSessions'
import { useExchangeSettings } from '../../hooks/useExchangeSettings'
import ParamsForm from './ParamsForm'
import SymbolPicker from './SymbolPicker'
import RiskParamsFields, { RISK_DEFAULTS, riskDefaultsFromSettings, riskFieldsToPayload } from '../RiskParamsFields'

const TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d']

export default function NewSessionWizard({ onCancel, onSuccess }) {
  const [step, setStep] = useState(1) // 1-5
  const [selectedStrategy, setSelectedStrategy] = useState(null)
  const [params, setParams] = useState({})
  const [selectedSymbols, setSelectedSymbols] = useState([])
  const [timeframe, setTimeframe] = useState('1h')
  const [capital, setCapital] = useState('1000')
  const [leverage, setLeverage] = useState(1)
  const [risk, setRisk] = useState(RISK_DEFAULTS)
  const [error, setError] = useState(null)

  const { data: strategies = [], isLoading: loadingStrategies } = useStrategies()
  const { data: symbolData } = useSymbols()
  const { data: paramsSchema } = useStrategyParams(selectedStrategy?.id)
  const { data: lockedSymbols = {} } = useLockedSymbols()
  const startSession = useStartSession()

  // Pre-fill capital and leverage from bot defaults (fires once)
  const { data: exchangeSettings } = useExchangeSettings()
  const settingsApplied = useRef(false)
  useEffect(() => {
    if (exchangeSettings && !settingsApplied.current) {
      setCapital(String(exchangeSettings.defaultBotCapital ?? 1000))
      setLeverage(exchangeSettings.defaultBotLeverage ?? 1)
      setRisk(riskDefaultsFromSettings(exchangeSettings))
      settingsApplied.current = true
    }
  }, [exchangeSettings])

  const futuresSymbols = symbolData?.futures || []

  // Determine if params step should be skipped (no PARAMS)
  const hasParams = paramsSchema && Object.keys(paramsSchema).length > 0

  const totalSteps = hasParams ? 5 : 4
  const stepLabels = hasParams
    ? ['Strategy', 'Parameters', 'Symbols', 'Settings', 'Review']
    : ['Strategy', 'Symbols', 'Settings', 'Review']

  // Map visual step to logical step
  const getLogicalStep = (visual) => {
    if (!hasParams) {
      // Skip params step: 1=strategy, 2=symbols, 3=settings, 4=review
      if (visual >= 2) return visual + 1
    }
    return visual
  }

  const canProceed = () => {
    const logical = getLogicalStep(step)
    if (logical === 1) return !!selectedStrategy
    if (logical === 2) return true // params always valid (have defaults)
    if (logical === 3) return selectedSymbols.length > 0
    if (logical === 4) return parseFloat(capital) > 0 && leverage >= 1 && leverage <= 125
    return true
  }

  const handleNext = () => {
    setError(null)
    if (step < totalSteps) setStep(step + 1)
  }

  const handleBack = () => {
    setError(null)
    if (step > 1) setStep(step - 1)
  }

  const handleStart = async () => {
    setError(null)
    try {
      await startSession.mutateAsync({
        strategyId: selectedStrategy.id,
        symbols: selectedSymbols,
        timeframe,
        params: hasParams ? params : {},
        capital,
        leverage: Number(leverage),
        riskParams: riskFieldsToPayload(risk),
      })
      onSuccess()
    } catch (err) {
      setError(err.response?.data?.error?.message || err.message || 'Failed to start bot')
    }
  }

  const logical = getLogicalStep(step)

  return (
    <div className="flex flex-col min-h-0 h-[640px] max-h-[88vh] text-slate-200">
      {/* Row 1: title + close — pinned */}
      <div className="flex items-center justify-between px-6 pt-6 pb-4 shrink-0">
        <h2 className="text-lg font-semibold text-gray-100">New Bot</h2>
        <button
          onClick={onCancel}
          aria-label="Close"
          className="text-gray-400 hover:text-gray-200 transition-colors"
        >
          <X size={18} />
        </button>
      </div>

      {/* Row 2: Cancel/Prev · steps · Next/Submit — pinned */}
      <div className="flex items-center justify-between gap-4 px-6 pb-5 shrink-0 border-b border-slate-700/40">
        {/* Left: Cancel (step 1) / Back */}
        <button
          onClick={step === 1 ? onCancel : handleBack}
          className="flex items-center gap-1 px-4 py-2 text-sm bg-[#060a0f] border border-slate-700/50 rounded-lg text-yellow-400 hover:text-yellow-300 hover:border-slate-600 transition-colors shrink-0"
        >
          <ChevronLeft size={16} />
          {step === 1 ? 'Cancel' : 'Back'}
        </button>

        {/* Center: Steps */}
        <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-2 flex-1 min-w-0">
          {stepLabels.map((label, i) => (
            <div key={i} className="flex items-center gap-2">
              <div
                className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium ${
                  i + 1 < step
                    ? 'bg-emerald-600 text-white'
                    : i + 1 === step
                    ? 'bg-emerald-600/30 text-emerald-400 border border-emerald-500'
                    : 'bg-gray-800 text-gray-500'
                }`}
              >
                {i + 1}
              </div>
              <span className={`text-xs ${i + 1 === step ? 'text-gray-200' : 'text-gray-500'}`}>
                {label}
              </span>
              {i < stepLabels.length - 1 && <ChevronRight size={14} className="text-gray-600" />}
            </div>
          ))}
        </div>

        {/* Right: Next / Submit */}
        {step < totalSteps ? (
          <button
            onClick={handleNext}
            disabled={!canProceed()}
            className="flex items-center gap-1 px-4 py-2 text-sm bg-[#060a0f] border border-slate-700/50 rounded-lg text-emerald-400 hover:text-emerald-300 hover:border-slate-600 disabled:text-gray-600 disabled:border-slate-800 disabled:cursor-not-allowed transition-colors shrink-0"
          >
            Next
            <ChevronRight size={16} />
          </button>
        ) : (
          <button
            onClick={handleStart}
            disabled={startSession.isPending}
            className="px-6 py-2 text-sm bg-[#060a0f] border border-slate-700/50 rounded-lg text-emerald-400 hover:text-emerald-300 hover:border-slate-600 disabled:text-gray-600 disabled:border-slate-800 disabled:cursor-not-allowed transition-colors shrink-0"
          >
            {startSession.isPending ? 'Starting...' : 'Start Bot'}
          </button>
        )}
      </div>

      {/* Scrollable content region */}
      <div className="flex-1 min-h-0 overflow-y-auto px-6 py-5 space-y-4">
      {/* Step content */}
      <div className="bg-[#0a0d13] border border-slate-700/40 rounded-lg p-6">
        {/* Step 1: Pick Strategy */}
        {logical === 1 && (
          <div>
            <h3 className="text-sm font-medium text-gray-300 mb-4">Select Strategy</h3>
            {loadingStrategies ? (
              <div className="space-y-2">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-14 bg-slate-800/50 rounded animate-pulse" />
                ))}
              </div>
            ) : (
              <div className="space-y-2">
                {strategies.map((s) => (
                  <button
                    key={s.id}
                    onClick={() => {
                      setSelectedStrategy(s)
                      setParams({})
                    }}
                    className={`w-full text-left p-3 rounded border transition-colors ${
                      selectedStrategy?.id === s.id
                        ? 'bg-emerald-500/10 border-emerald-500 text-emerald-400'
                        : 'bg-gray-800 border-gray-700 text-gray-300 hover:border-gray-500'
                    }`}
                  >
                    <div className="font-medium text-sm">{s.name}</div>
                    <div className="text-xs text-gray-400 mt-0.5">{s.description}</div>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Step 2 (if hasParams): Configure Parameters */}
        {logical === 2 && hasParams && (
          <div>
            <h3 className="text-sm font-medium text-gray-300 mb-4">Strategy Parameters</h3>
            <ParamsForm
              params={paramsSchema}
              values={params}
              onChange={setParams}
            />
          </div>
        )}

        {/* Step 3: Select Symbols */}
        {logical === 3 && (
          <div>
            <h3 className="text-sm font-medium text-gray-300 mb-4">Select Symbols</h3>
            <SymbolPicker
              symbols={futuresSymbols}
              selected={selectedSymbols}
              lockedSymbols={lockedSymbols}
              onChange={setSelectedSymbols}
            />
          </div>
        )}

        {/* Step 4: Configure Session */}
        {logical === 4 && (
          <div className="space-y-4">
            <h3 className="text-sm font-medium text-gray-300 mb-4">Session Settings</h3>
            <div>
              <label className="block text-sm text-gray-300 mb-1">Timeframe</label>
              <select
                value={timeframe}
                onChange={(e) => setTimeframe(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-emerald-500"
              >
                {TIMEFRAMES.map((tf) => (
                  <option key={tf} value={tf}>{tf}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm text-gray-300 mb-1">Total Capital (USDT)</label>
              <input
                type="number"
                value={capital}
                min="1"
                step="100"
                onChange={(e) => setCapital(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-emerald-500"
              />
              <p className="text-xs text-gray-500 mt-1">
                Split equally: ~${(parseFloat(capital) / Math.max(selectedSymbols.length, 1)).toFixed(2)} per symbol
              </p>
            </div>
            <div>
              <label className="block text-sm text-gray-300 mb-1">Leverage (1–125)</label>
              <input
                type="number"
                value={leverage}
                min="1"
                max="125"
                onChange={(e) => setLeverage(parseInt(e.target.value, 10) || 1)}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-emerald-500"
              />
            </div>
            <div className="border-t border-gray-800 pt-4">
              <p className="text-sm font-medium text-gray-300 mb-3">Risk Management</p>
              <RiskParamsFields
                values={risk}
                onChange={setRisk}
                inputClassName="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-emerald-500"
                labelClassName="block text-xs text-gray-300 mb-1"
              />
            </div>
          </div>
        )}

        {/* Step 5: Review */}
        {logical === 5 && (
          <div>
            <h3 className="text-sm font-medium text-gray-300 mb-4">Review Bot</h3>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between py-2 border-b border-gray-800">
                <span className="text-gray-400">Strategy</span>
                <span className="text-gray-100">{selectedStrategy?.name}</span>
              </div>
              <div className="flex justify-between py-2 border-b border-gray-800">
                <span className="text-gray-400">Symbols</span>
                <span className="text-gray-100">{selectedSymbols.join(', ')}</span>
              </div>
              <div className="flex justify-between py-2 border-b border-gray-800">
                <span className="text-gray-400">Timeframe</span>
                <span className="text-gray-100">{timeframe}</span>
              </div>
              <div className="flex justify-between py-2 border-b border-gray-800">
                <span className="text-gray-400">Capital</span>
                <span className="text-gray-100">${parseFloat(capital).toLocaleString()}</span>
              </div>
              <div className="flex justify-between py-2 border-b border-gray-800">
                <span className="text-gray-400">Leverage</span>
                <span className="text-gray-100">{leverage}x</span>
              </div>
              <div className="flex justify-between py-2 border-b border-gray-800">
                <span className="text-gray-400">Risk & Cost</span>
                <span className="text-gray-100">
                  {risk.riskPct}% / trade · {risk.riskReward}:1 R:R · {risk.maxDrawdown}% max DD · {risk.minEdgeMult} edge mult
                </span>
              </div>
              <div className="flex justify-between py-2 border-b border-gray-800">
                <span className="text-gray-400">Mode</span>
                <span className="text-yellow-400">Binance Testnet</span>
              </div>
              {hasParams && Object.keys(params).length > 0 && (
                <div className="py-2 border-b border-gray-800">
                  <span className="text-gray-400">Parameters</span>
                  <div className="mt-1 flex flex-wrap gap-2">
                    {Object.entries(params).map(([k, v]) => (
                      <span key={k} className="text-xs bg-gray-800 text-gray-300 px-2 py-1 rounded">
                        {k}: {v}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

        {/* Error banner */}
        {error && (
          <div className="flex items-start gap-2 bg-red-950/20 border border-red-800/40 rounded-lg p-3 text-sm text-red-400">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}
      </div>
    </div>
  )
}
