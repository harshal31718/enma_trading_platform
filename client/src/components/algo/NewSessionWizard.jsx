import { useState, useEffect, useRef } from 'react'
import { ChevronRight, ChevronLeft, AlertTriangle } from 'lucide-react'
import { useStrategies } from '../../hooks/useStrategies'
import { useSymbols } from '../../hooks/useCandles'
import { useStrategyParams, useStartSession, useLockedSymbols } from '../../hooks/useAlgoSessions'
import { useExchangeSettings } from '../../hooks/useExchangeSettings'
import ParamsForm from './ParamsForm'
import SymbolPicker from './SymbolPicker'

const TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d']

export default function NewSessionWizard({ onCancel, onSuccess }) {
  const [step, setStep] = useState(1) // 1-5
  const [selectedStrategy, setSelectedStrategy] = useState(null)
  const [params, setParams] = useState({})
  const [selectedSymbols, setSelectedSymbols] = useState([])
  const [timeframe, setTimeframe] = useState('1h')
  const [capital, setCapital] = useState('1000')
  const [leverage, setLeverage] = useState(1)
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
      })
      onSuccess()
    } catch (err) {
      setError(err.response?.data?.error?.message || err.message || 'Failed to start bot')
    }
  }

  const logical = getLogicalStep(step)

  return (
    <div className="max-w-2xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-lg font-semibold text-gray-100">New Bot Session</h2>
        <button onClick={onCancel} className="text-sm text-gray-400 hover:text-gray-200">
          Cancel
        </button>
      </div>

      {/* Step indicator */}
      <div className="flex items-center gap-2 mb-6">
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

      {/* Step content */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-6 mb-4">
        {/* Step 1: Pick Strategy */}
        {logical === 1 && (
          <div>
            <h3 className="text-sm font-medium text-gray-300 mb-3">Select a strategy</h3>
            {loadingStrategies ? (
              <div className="space-y-2">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-14 bg-gray-800 rounded animate-pulse" />
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
            <h3 className="text-sm font-medium text-gray-300 mb-3">Strategy parameters</h3>
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
            <h3 className="text-sm font-medium text-gray-300 mb-3">
              Select symbols ({selectedSymbols.length} selected)
            </h3>
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
            <h3 className="text-sm font-medium text-gray-300 mb-3">Session settings</h3>
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
          </div>
        )}

        {/* Step 5: Review */}
        {logical === 5 && (
          <div>
            <h3 className="text-sm font-medium text-gray-300 mb-4">Review & Start</h3>
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
        <div className="flex items-start gap-2 bg-red-950/20 border border-red-800/40 rounded-lg p-3 mb-4 text-sm text-red-400">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Navigation buttons */}
      <div className="flex items-center justify-between">
        <button
          onClick={step === 1 ? onCancel : handleBack}
          className="flex items-center gap-1 px-4 py-2 text-sm text-gray-400 hover:text-gray-200 transition-colors"
        >
          <ChevronLeft size={16} />
          {step === 1 ? 'Cancel' : 'Back'}
        </button>

        {step < totalSteps ? (
          <button
            onClick={handleNext}
            disabled={!canProceed()}
            className="flex items-center gap-1 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm rounded-lg transition-colors"
          >
            Next
            <ChevronRight size={16} />
          </button>
        ) : (
          <button
            onClick={handleStart}
            disabled={startSession.isPending}
            className="px-6 py-2 bg-emerald-600 hover:bg-emerald-700 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm rounded-lg transition-colors"
          >
            {startSession.isPending ? 'Starting...' : 'Start Bot'}
          </button>
        )}
      </div>
    </div>
  )
}
