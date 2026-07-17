import { useState, useEffect, useRef } from 'react'
import { ChevronRight, ChevronLeft, AlertTriangle, Calendar, X } from 'lucide-react'
import { useStrategies } from '../../hooks/useStrategies'
import { useSymbols } from '../../hooks/useCandles'
import { useStrategyParams } from '../../hooks/useAlgoSessions'
import { useExchangeSettings } from '../../hooks/useExchangeSettings'
import { formatIsoDate } from '../../utils/formatters'
import ParamsForm from '../../components/algo/ParamsForm'
import RiskParamsFields, { RISK_DEFAULTS, riskDefaultsFromSettings, riskFieldsToPayload } from '../../components/RiskParamsFields'

const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d']

const inputCls =
  'w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-emerald-500'

// Date picker that shows "29 Aug '25" but stores/emits a YYYY-MM-DD ISO string
function DateInput({ value, onChange, label }) {
  const hiddenRef = useRef(null)
  return (
    <div>
      <label className="block text-sm text-gray-300 mb-1">{label}</label>
      <button
        type="button"
        onClick={() => hiddenRef.current?.showPicker?.()}
        className="relative flex w-full items-center justify-between bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 hover:border-gray-500 focus:outline-none focus:border-emerald-500 transition-colors"
      >
        <span>{formatIsoDate(value)}</span>
        <Calendar size={14} className="text-gray-500 shrink-0" />
        <input
          ref={hiddenRef}
          type="date"
          value={value}
          onChange={onChange}
          className="absolute inset-0 opacity-0 cursor-pointer w-full"
          tabIndex={-1}
        />
      </button>
    </div>
  )
}

export default function NewBacktestWizard({ onCancel, onRun }) {
  const [step, setStep] = useState(1)
  const [selectedStrategy, setSelectedStrategy] = useState(null)
  const [params, setParams] = useState({})
  const [exchange, setExchange] = useState('Binance Futures')
  const [symbol, setSymbol] = useState('')
  const [timeframe, setTimeframe] = useState('1h')
  const [startDate, setStartDate] = useState('2023-01-01')
  const [endDate, setEndDate] = useState('2024-01-01')
  const [capital, setCapital] = useState('10000')
  const [leverage, setLeverage] = useState('1')
  const [feeRate, setFeeRate] = useState('0.001')
  const [risk, setRisk] = useState(RISK_DEFAULTS)
  const [error, setError] = useState(null)

  const { data: strategies = [], isLoading: loadingStrategies } = useStrategies()
  const { data: symbolData } = useSymbols()
  const { data: paramsSchema } = useStrategyParams(selectedStrategy?.id)

  // Pre-fill capital, leverage, fee, and risk from saved exchange settings (fires once)
  const { data: exchangeSettings } = useExchangeSettings()
  const settingsApplied = useRef(false)
  useEffect(() => {
    if (exchangeSettings && !settingsApplied.current) {
      setCapital(String(exchangeSettings.defaultCapital ?? 10000))
      setLeverage(String(exchangeSettings.defaultLeverage ?? 1))
      setFeeRate(String(exchangeSettings.takerFee ?? 0.001))
      setRisk(riskDefaultsFromSettings(exchangeSettings))
      settingsApplied.current = true
    }
  }, [exchangeSettings])

  // Engine only supports USD-M Futures — always use the futures symbol list
  const symbolList = symbolData?.futures || []

  // Default the symbol to the first available whenever the list/exchange changes
  // and the current pick is no longer valid.
  useEffect(() => {
    if (symbolList.length > 0 && !symbol) {
      setSymbol(symbolList[0])
    }
  }, [symbolList, symbol])

  const hasParams = paramsSchema && Object.keys(paramsSchema).length > 0

  const totalSteps = hasParams ? 5 : 4
  const stepLabels = hasParams
    ? ['Strategy', 'Parameters', 'Market', 'Settings', 'Review']
    : ['Strategy', 'Market', 'Settings', 'Review']

  // Map visual step to logical step (params step skipped when strategy has no PARAMS)
  const getLogicalStep = (visual) => {
    if (!hasParams && visual >= 2) return visual + 1
    return visual
  }

  const datesValid = new Date(endDate) > new Date(startDate)

  const canProceed = () => {
    const logical = getLogicalStep(step)
    if (logical === 1) return !!selectedStrategy
    if (logical === 2) return true // params always valid (have defaults)
    if (logical === 3) return !!symbol
    if (logical === 4) return parseFloat(capital) > 0 && Number(leverage) >= 1 && Number(leverage) <= 125 && datesValid
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

  const handleRun = () => {
    setError(null)
    if (!selectedStrategy || !symbol) {
      setError('Select a strategy and symbol before running.')
      return
    }
    if (!datesValid) {
      setError('End date must be after start date.')
      return
    }
    onRun({
      strategyId: selectedStrategy.id,
      exchange,
      symbol,
      timeframe,
      startDate,
      endDate,
      capital: parseFloat(capital),
      leverage: parseInt(leverage, 10),
      feeRate: parseFloat(feeRate),
      riskParams: riskFieldsToPayload(risk),
      alphaParams: hasParams ? params : {},
    })
  }

  const logical = getLogicalStep(step)

  return (
    <div className="flex flex-col min-h-0 h-[640px] max-h-[88vh] text-slate-200">
      {/* Row 1: title + close — pinned */}
      <div className="flex items-center justify-between px-6 pt-6 pb-4 shrink-0">
        <h2 className="text-lg font-semibold text-gray-100">Run Backtest</h2>
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
        <div className="flex-1 flex justify-center min-w-0">
          {/* Mobile step info */}
          <div className="flex sm:hidden flex-col items-center select-none font-mono">
            <span className="text-[10px] text-slate-500 uppercase tracking-widest leading-none mb-1">
              Step {step} of {totalSteps}
            </span>
            <span className="text-xs text-gray-200 font-semibold truncate leading-none">
              {stepLabels[step - 1]}
            </span>
          </div>

          {/* Desktop steps list */}
          <div className="hidden sm:flex flex-wrap items-center justify-center gap-x-4 gap-y-2">
            {stepLabels.map((label, i) => (
              <div key={i} className="flex items-center gap-2">
                <div
                  className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium ${
                    i + 1 < step
                      ? 'bg-emerald-600 text-white'
                      : i + 1 === step
                      ? 'bg-emerald-600/30 text-emerald-400 border border-emerald-500'
                      : 'bg-slate-800 text-gray-500'
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
        </div>

        {/* Right: Next / Run */}
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
            onClick={handleRun}
            className="px-6 py-2 text-sm bg-[#060a0f] border border-slate-700/50 rounded-lg text-emerald-400 hover:text-emerald-300 hover:border-slate-600 transition-colors shrink-0"
          >
            Run Backtest
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
            <ParamsForm params={paramsSchema} values={params} onChange={setParams} />
          </div>
        )}

        {/* Step 3: Market */}
        {logical === 3 && (
          <div className="space-y-4">
            <h3 className="text-sm font-medium text-gray-300 mb-4">Market</h3>
            <div>
              <label className="block text-sm text-gray-300 mb-1">Exchange</label>
              <select value={exchange} onChange={(e) => setExchange(e.target.value)} className={inputCls}>
                <option value="Binance Futures">Binance Futures (USD-M)</option>
                <option value="Binance Spot" disabled className="text-slate-400">Binance Spot (coming soon)</option>
              </select>
            </div>
            <div>
              <label className="block text-sm text-gray-300 mb-1">Symbol(s)</label>
              <input
                type="text"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                placeholder="e.g., BTCUSDT or BTCUSDT,ETHUSDT"
                className={inputCls}
              />
              <p className="text-xs text-gray-400 mt-1">
                Enter a single symbol or multiple comma-separated symbols.
              </p>
              {symbolList.length > 0 && (
                <div className="mt-3">
                  <label className="block text-xs text-gray-400 mb-1.5">Quick Select</label>
                  <div className="flex flex-wrap gap-1.5 max-h-36 overflow-y-auto border border-gray-800 p-2 rounded bg-gray-900/50">
                    {symbolList.map((sym) => {
                      const selectedList = symbol.split(',').map((s) => s.trim()).filter(Boolean)
                      const isSelected = selectedList.includes(sym)
                      return (
                        <button
                          key={sym}
                          type="button"
                          onClick={() => {
                            if (isSelected) {
                              const filtered = selectedList.filter((s) => s !== sym)
                              setSymbol(filtered.join(', '))
                            } else {
                              const updated = [...selectedList, sym]
                              setSymbol(updated.join(', '))
                            }
                          }}
                          className={`px-2.5 py-1 text-xs rounded border transition-colors ${
                            isSelected
                              ? 'bg-emerald-500/10 border-emerald-500 text-emerald-400'
                              : 'bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-600 hover:text-gray-200'
                          }`}
                        >
                          {sym}
                        </button>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
            <div>
              <label className="block text-sm text-gray-300 mb-1">Timeframe</label>
              <select value={timeframe} onChange={(e) => setTimeframe(e.target.value)} className={inputCls}>
                {TIMEFRAMES.map((tf) => (
                  <option key={tf} value={tf}>{tf}</option>
                ))}
              </select>
            </div>
          </div>
        )}

        {/* Step 4: Settings */}
        {logical === 4 && (
          <div className="space-y-4">
            <h3 className="text-sm font-medium text-gray-300 mb-4">Simulation Settings</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <DateInput label="Start Date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
              <DateInput label="End Date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
            </div>
            {!datesValid && (
              <p className="text-yellow-500 text-xs">End date must be after start date.</p>
            )}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm text-gray-300 mb-1">Starting Capital (USDT)</label>
                <input
                  type="number"
                  value={capital}
                  min="1"
                  step="100"
                  onChange={(e) => setCapital(e.target.value)}
                  className={inputCls}
                />
              </div>
              <div>
                <label className="block text-sm text-gray-300 mb-1">Leverage (1–125)</label>
                <input
                  type="number"
                  value={leverage}
                  min="1"
                  max="125"
                  onChange={(e) => setLeverage(e.target.value)}
                  className={inputCls}
                />
              </div>
            </div>
            <div>
              <label className="block text-sm text-gray-300 mb-1">Fee Rate</label>
              <input
                type="number"
                step="0.0001"
                value={feeRate}
                onChange={(e) => setFeeRate(e.target.value)}
                className={inputCls}
              />
            </div>
            <div className="border-t border-gray-800 pt-4">
              <p className="text-sm font-medium text-gray-300 mb-3">Risk Management</p>
              <RiskParamsFields
                values={risk}
                onChange={setRisk}
                inputClassName={inputCls}
                labelClassName="block text-xs text-gray-300 mb-1"
              />
            </div>
          </div>
        )}

        {/* Step 5: Review */}
        {logical === 5 && (
          <div>
            <h3 className="text-sm font-medium text-gray-300 mb-4">Review Backtest</h3>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between py-2 border-b border-gray-800">
                <span className="text-gray-400">Strategy</span>
                <span className="text-gray-100">{selectedStrategy?.name}</span>
              </div>
              <div className="flex justify-between py-2 border-b border-gray-800">
                <span className="text-gray-400">Symbol / Exchange</span>
                <span className="text-gray-100">{symbol} · {exchange}</span>
              </div>
              <div className="flex justify-between py-2 border-b border-gray-800">
                <span className="text-gray-400">Timeframe</span>
                <span className="text-gray-100">{timeframe}</span>
              </div>
              <div className="flex justify-between py-2 border-b border-gray-800">
                <span className="text-gray-400">Date Range</span>
                <span className="text-gray-100">{formatIsoDate(startDate)} → {formatIsoDate(endDate)}</span>
              </div>
              <div className="flex justify-between py-2 border-b border-gray-800">
                <span className="text-gray-400">Capital</span>
                <span className="text-gray-100">${parseFloat(capital || 0).toLocaleString()}</span>
              </div>
              <div className="flex justify-between py-2 border-b border-gray-800">
                <span className="text-gray-400">Leverage / Fee</span>
                <span className="text-gray-100">{leverage}x / {(parseFloat(feeRate || 0) * 100).toFixed(2)}%</span>
              </div>
              <div className="flex justify-between py-2 border-b border-gray-800">
                <span className="text-gray-400">Risk &amp; Cost</span>
                <span className="text-gray-100">
                  {risk.riskPct}% / trade · {risk.riskReward}:1 R:R · {risk.maxDrawdown}% max DD · {risk.minEdgeMult} edge mult
                </span>
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
