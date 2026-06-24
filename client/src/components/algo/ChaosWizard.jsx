import { useState, useEffect, useRef, useMemo } from 'react'
import { ChevronRight, ChevronLeft, AlertTriangle, Zap, Check, Play, Settings as SettingsIcon, X } from 'lucide-react'
import { useStrategies } from '../../hooks/useStrategies'
import { useSymbols } from '../../hooks/useCandles'
import { useStartChaos, useLockedSymbols, useChaosSymbols } from '../../hooks/useAlgoSessions'
import { useExchangeSettings } from '../../hooks/useExchangeSettings'
import RiskParamsFields, { RISK_DEFAULTS, riskDefaultsFromSettings, riskFieldsToPayload } from '../RiskParamsFields'

const TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d']

// Scoped Symbol Picker for Chaos Wizard (similar to SymbolPicker.jsx but customized for tiered lists & unique selection constraints)
function ScopedSymbolPicker({ symbols = [], selected = [], lockedSymbols = {}, globalClaimedByOthers = new Set(), onToggle, maxManualSymbols }) {
  const isAtCap = selected.length >= maxManualSymbols

  return (
    <div>
      <div className="flex justify-between items-center mb-2">
        <span className="text-xs text-slate-400">
          Selected: <strong className="text-slate-200">{selected.length} / {maxManualSymbols}</strong> max
        </span>
        {isAtCap && (
          <span className="text-[10px] text-amber-400 bg-amber-500/10 px-1.5 py-0.5 rounded border border-amber-500/20">
            Cap reached
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2 max-h-60 overflow-y-auto p-2 bg-[#0a0d13] rounded border border-slate-800">
        {symbols.map(({ symbol, tier }) => {
          const isLockedBySession = !!lockedSymbols?.[symbol]
          const isClaimedByOtherStrategy = globalClaimedByOthers.has(symbol)
          const isSelected = selected.includes(symbol)
          
          // Disable conditions: locked by live session, claimed by other strategy, or at manual cap (if not currently selected)
          const isDisabled = isLockedBySession || isClaimedByOtherStrategy || (isAtCap && !isSelected)
          
          let title = `Tier: ${tier.toUpperCase()}`
          if (isLockedBySession) title = `Locked: ${lockedSymbols[symbol].reason}`
          else if (isClaimedByOtherStrategy) title = 'Claimed by another strategy'
          else if (isAtCap && !isSelected) title = `Max manual cap (${maxManualSymbols}) reached`

          const tierBadgeCls = 
            tier === 'high' ? 'bg-purple-500/20 text-purple-400 border-purple-500/30' :
            tier === 'mid' ? 'bg-blue-500/20 text-blue-400 border-blue-500/30' :
            'bg-slate-700/30 text-slate-400 border-slate-700/40'

          return (
            <button
              key={symbol}
              type="button"
              onClick={() => onToggle(symbol)}
              disabled={isDisabled}
              title={title}
              className={[
                'relative px-3 py-2 text-xs rounded border transition-all text-left flex flex-col justify-between h-14',
                isDisabled
                  ? 'bg-slate-900/30 border-slate-900 text-slate-600 cursor-not-allowed opacity-50'
                  : isSelected
                  ? 'bg-purple-500/10 border-purple-500 text-purple-300 shadow-md shadow-purple-950/20'
                  : 'bg-slate-800/60 border-slate-700/50 text-gray-300 hover:border-slate-500 hover:bg-slate-800'
              ].join(' ')}
            >
              <span className="font-semibold">{symbol}</span>
              <div className="flex justify-between items-center w-full mt-1">
                <span className={`text-[9px] px-1 rounded border ${tierBadgeCls}`}>
                  {tier}
                </span>
                {isSelected && (
                  <Check size={10} className="text-purple-400" />
                )}
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

export default function ChaosWizard({ onCancel, onSuccess }) {
  const [step, setStep] = useState(1) // 1-4
  const [selectedStrategyNames, setSelectedStrategyNames] = useState([]) // names of selected strategies
  const [strategyToggles, setStrategyToggles] = useState({}) // { strategyName: 'auto' | 'manual' }
  const [manualPicks, setManualPicks] = useState({}) // { strategyName: [symbol, ...] }
  
  const [timeframe, setTimeframe] = useState('1m')
  const [capital, setCapital] = useState('500')
  const [leverage, setLeverage] = useState(50)
  const [risk, setRisk] = useState(RISK_DEFAULTS)
  const [error, setError] = useState(null)

  const { data: strategies = [], isLoading: loadingStrategies } = useStrategies()
  const { data: curatedSymbols = [], isLoading: loadingSymbols } = useChaosSymbols()
  const { data: lockedSymbols = {} } = useLockedSymbols()
  const startChaos = useStartChaos()

  // Load exchangeSettings to fetch Caps & Defaults
  const { data: exchangeSettings, isLoading: loadingSettings } = useExchangeSettings()
  const settingsApplied = useRef(false)

  // Chaos limits from settings
  const maxStrategies = exchangeSettings?.chaosMaxStrategies ?? 10
  const maxManualSymbols = exchangeSettings?.chaosMaxManualSymbols ?? 5

  useEffect(() => {
    if (exchangeSettings && !settingsApplied.current) {
      setCapital(String(exchangeSettings.chaosDefaultCapital ?? 500))
      setLeverage(exchangeSettings.chaosDefaultLeverage ?? 50)
      setTimeframe(exchangeSettings.chaosDefaultTimeframe ?? '1m')
      setRisk(riskDefaultsFromSettings(exchangeSettings))
      settingsApplied.current = true
    }
  }, [exchangeSettings])

  // Resolve active strategies in Step 2 / Preview
  const activeStrategies = useMemo(() => {
    if (selectedStrategyNames.length > 0) {
      return selectedStrategyNames
    }
    // Default fallback: most recent strategies up to maxStrategies
    return strategies.slice(0, maxStrategies).map(s => s.name)
  }, [selectedStrategyNames, strategies, maxStrategies])

  // Live Allocation Preview based on server logic (D1/D4)
  const preview = useMemo(() => {
    if (!activeStrategies.length || !curatedSymbols.length) {
      return { assignments: {}, stats: {} }
    }

    const lockedSet = new Set(Object.keys(lockedSymbols || {}))
    const curatedSet = new Set(curatedSymbols.map(s => s.symbol))
    const globalClaimed = new Set()
    const reservedMap = {}

    // 1. Manual picks
    for (const strat of activeStrategies) {
      reservedMap[strat] = new Set()
      const isManual = strategyToggles[strat] === 'manual'
      const picks = isManual ? (manualPicks[strat] || []) : []
      
      // Filter out invalid/locked manual picks
      for (const sym of picks) {
        if (curatedSet.has(sym) && !lockedSet.has(sym) && !globalClaimed.has(sym)) {
          reservedMap[strat].add(sym)
          globalClaimed.add(sym)
        }
      }
    }

    // 2. Free pool
    const pool = curatedSymbols.filter(s => !globalClaimed.has(s.symbol) && !lockedSet.has(s.symbol))

    // 3. Bucket free pool
    const high = pool.filter(s => s.tier === 'high').map(s => s.symbol)
    const mid = pool.filter(s => s.tier === 'mid').map(s => s.symbol)
    const low = pool.filter(s => s.tier === 'low').map(s => s.symbol)

    // 4. Distribute equally
    const assignments = {}
    const stats = {}
    for (const strat of activeStrategies) {
      assignments[strat] = [...reservedMap[strat]]
      stats[strat] = {
        high: curatedSymbols.filter(s => s.tier === 'high' && reservedMap[strat].has(s.symbol)).length,
        mid: curatedSymbols.filter(s => s.tier === 'mid' && reservedMap[strat].has(s.symbol)).length,
        low: curatedSymbols.filter(s => s.tier === 'low' && reservedMap[strat].has(s.symbol)).length,
        total: reservedMap[strat].size
      }
    }

    const n = activeStrategies.length
    let i = 0

    // High distribution
    for (const sym of high) {
      const strat = activeStrategies[i % n]
      assignments[strat].push(sym)
      stats[strat].high++
      stats[strat].total++
      i++
    }

    // Mid distribution
    for (const sym of mid) {
      const strat = activeStrategies[i % n]
      assignments[strat].push(sym)
      stats[strat].mid++
      stats[strat].total++
      i++
    }

    // Low distribution
    for (const sym of low) {
      const strat = activeStrategies[i % n]
      assignments[strat].push(sym)
      stats[strat].low++
      stats[strat].total++
      i++
    }

    return { assignments, stats }
  }, [activeStrategies, strategyToggles, manualPicks, curatedSymbols, lockedSymbols])

  // Flat set of all manual picks claimed by other strategies
  const getGlobalClaimedByOthers = (currentStrat) => {
    const claimed = new Set()
    for (const strat of activeStrategies) {
      if (strat === currentStrat) continue
      if (strategyToggles[strat] === 'manual') {
        const picks = manualPicks[strat] || []
        picks.forEach(p => claimed.add(p))
      }
    }
    return claimed
  }

  const handleStrategyToggleSelect = (name) => {
    setSelectedStrategyNames(prev => {
      if (prev.includes(name)) {
        return prev.filter(n => n !== name)
      } else {
        if (prev.length >= maxStrategies) return prev // limit
        return [...prev, name]
      }
    })
  }

  const handleModeToggle = (stratName, mode) => {
    setStrategyToggles(prev => ({
      ...prev,
      [stratName]: mode
    }))
  }

  const handleSymbolToggle = (stratName, symbol) => {
    setManualPicks(prev => {
      const current = prev[stratName] || []
      const next = current.includes(symbol)
        ? current.filter(s => s !== symbol)
        : [...current, symbol]
      return {
        ...prev,
        [stratName]: next
      }
    })
  }

  const canProceed = () => {
    if (step === 1) return true // 0 selected => recent strategies auto-run (valid)
    if (step === 3) {
      return parseFloat(capital) > 0 && leverage >= 1 && leverage <= 125
    }
    return true
  }

  const handleNext = () => {
    setError(null)
    if (step < 4) setStep(step + 1)
  }

  const handleBack = () => {
    setError(null)
    if (step > 1) setStep(step - 1)
  }

  const handleLaunch = async () => {
    setError(null)
    try {
      const formattedStrategies = activeStrategies.map(name => {
        const isManual = strategyToggles[name] === 'manual'
        const symbols = isManual ? (manualPicks[name] || []) : []
        return { name, symbols }
      })

      const payload = {
        timeframe,
        strategies: formattedStrategies,
        risk: {
          capital: capital,
          leverage: Number(leverage),
          riskReward: risk.riskReward,
          maxDrawdown: risk.maxDrawdown,
          riskPct: risk.riskPct,
          minEdgeMult: risk.minEdgeMult,
        }
      }

      const result = await startChaos.mutateAsync(payload)
      
      if (result.errors?.length && !result.launched?.length) {
        setError(`Chaos Mode launch failed: ${result.errors.map(e => e.error).join('; ')}`)
      } else {
        onSuccess()
      }
    } catch (err) {
      setError(err.response?.data?.error?.message || err.message || 'Failed to start Chaos Mode')
    }
  }

  const stepLabels = ['Strategies', 'Allocation', 'Parameters', 'Review']
  const isLoading = loadingStrategies || loadingSymbols || loadingSettings

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-[640px] max-h-[88vh]">
        <div className="w-8 h-8 rounded-full border-2 border-purple-500 border-t-transparent animate-spin mb-4" />
        <p className="text-sm text-slate-400">Loading Chaos configurations...</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col min-h-0 h-[640px] max-h-[88vh] text-slate-200">
      {/* Row 1: title + close — pinned */}
      <div className="flex items-center justify-between px-6 pt-6 pb-4 shrink-0">
        <div className="flex items-center gap-2">
          <Zap size={18} className="text-purple-400" />
          <h2 className="text-lg font-bold text-gray-100">Chaos Mode</h2>
          <span className="text-[10px] uppercase font-semibold border border-purple-500/30 bg-purple-500/10 text-purple-400 rounded-full px-2 py-0.5 animate-pulse">
            Testnet Only
          </span>
        </div>
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
          type="button"
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
                className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold ${
                  i + 1 < step
                    ? 'bg-purple-600 text-white'
                    : i + 1 === step
                    ? 'bg-purple-600/30 text-purple-400 border border-purple-500'
                    : 'bg-slate-800 text-slate-500'
                }`}
              >
                {i + 1}
              </div>
              <span className={`text-xs ${i + 1 === step ? 'text-gray-200 font-medium' : 'text-slate-500'}`}>
                {label}
              </span>
              {i < stepLabels.length - 1 && <ChevronRight size={14} className="text-slate-700" />}
            </div>
          ))}
        </div>

        {/* Right: Next / Activate */}
        {step < 4 ? (
          <button
            type="button"
            onClick={handleNext}
            disabled={!canProceed()}
            className="flex items-center gap-1 px-4 py-2 text-sm bg-[#060a0f] border border-slate-700/50 rounded-lg text-purple-400 hover:text-purple-300 hover:border-slate-600 disabled:text-gray-600 disabled:border-slate-800 disabled:cursor-not-allowed transition-colors shrink-0"
          >
            Next
            <ChevronRight size={16} />
          </button>
        ) : (
          <button
            type="button"
            onClick={handleLaunch}
            disabled={startChaos.isPending}
            className="flex items-center gap-2 px-5 py-2 text-sm bg-[#060a0f] border border-purple-500/40 rounded-lg text-purple-300 hover:text-purple-200 hover:border-purple-500/60 disabled:text-gray-600 disabled:border-slate-800 disabled:cursor-not-allowed transition-colors shrink-0"
          >
            <Play size={14} className="fill-current" />
            {startChaos.isPending ? 'Launching...' : 'Activate Chaos'}
          </button>
        )}
      </div>

      {/* Scrollable content region */}
      <div className="flex-1 min-h-0 overflow-y-auto px-6 py-5 space-y-4">
      {/* Step content */}
      <div className="bg-[#0a0d13] border border-slate-700/40 rounded-xl p-6 shadow-xl">
        {/* Step 1: Select Strategies */}
        {step === 1 && (
          <div>
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-sm font-semibold text-gray-300">Select Strategies</h3>
              <span className="text-xs text-slate-400">Cap: {maxStrategies}</span>
            </div>

            <div className="space-y-2">
              {strategies.map((s) => {
                const isSelected = selectedStrategyNames.includes(s.name)
                const isAtCap = selectedStrategyNames.length >= maxStrategies
                const isDisabled = isAtCap && !isSelected

                return (
                  <button
                    key={s.id}
                    type="button"
                    disabled={isDisabled}
                    onClick={() => handleStrategyToggleSelect(s.name)}
                    className={`w-full text-left p-4 rounded-lg border transition-all ${
                      isSelected
                        ? 'bg-purple-500/10 border-purple-500 text-purple-300 shadow-md shadow-purple-950/20'
                        : isDisabled
                        ? 'bg-slate-950/30 border-slate-900 text-slate-600 cursor-not-allowed opacity-50'
                        : 'bg-slate-850 border-slate-800 text-slate-300 hover:border-slate-650 hover:bg-slate-800'
                    }`}
                  >
                    <div className="flex justify-between items-center">
                      <div className="font-semibold text-sm">{s.name}</div>
                      <div className={`w-4 h-4 rounded border flex items-center justify-center transition-colors ${
                        isSelected ? 'bg-purple-500 border-purple-500 text-white' : 'border-slate-600 bg-slate-900'
                      }`}>
                        {isSelected && <Check size={10} />}
                      </div>
                    </div>
                    {s.description && (
                      <div className="text-xs text-slate-400 mt-1 whitespace-normal break-words">{s.description}</div>
                    )}
                  </button>
                )
              })}
            </div>
          </div>
        )}

        {/* Step 2: Symbol Allocation */}
        {step === 2 && (
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-gray-300 mb-4">Symbol Allocation</h3>

            <div className="space-y-4">
              {activeStrategies.map((stratName) => {
                const isManual = strategyToggles[stratName] === 'manual'
                const picks = manualPicks[stratName] || []
                const s = preview.stats[stratName] || { high: 0, mid: 0, low: 0, total: 0 }

                return (
                  <div key={stratName} className="border border-slate-800 rounded-lg bg-slate-950/40 p-4">
                    <div className="flex items-center gap-3 mb-3">
                      {/* Strategy name — fixed width so stats column aligns across rows */}
                      <span className="text-sm font-bold text-slate-200 w-44 shrink-0 truncate">{stratName}</span>

                      {/* Inline allocation preview — left-aligned, consistent start position */}
                      <div className="flex items-center gap-1.5 flex-1 min-w-0 justify-start">
                        <span className="text-[10px] bg-purple-500/10 text-purple-400 px-1.5 py-0.5 rounded border border-purple-500/20" title="High volume">
                          H: {s.high}
                        </span>
                        <span className="text-[10px] bg-blue-500/10 text-blue-400 px-1.5 py-0.5 rounded border border-blue-500/20" title="Mid volume">
                          M: {s.mid}
                        </span>
                        <span className="text-[10px] bg-slate-700/20 text-slate-400 px-1.5 py-0.5 rounded border border-slate-800" title="Low volume">
                          L: {s.low}
                        </span>
                        <span className="text-[10px] font-semibold text-slate-300 ml-1">
                          {s.total} symbols
                        </span>
                      </div>

                      {/* Auto / Manual toggle */}
                      <div className="inline-flex rounded-lg bg-slate-900 p-0.5 border border-slate-800 shrink-0">
                        <button
                          type="button"
                          onClick={() => handleModeToggle(stratName, 'auto')}
                          className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                            !isManual ? 'bg-purple-650 text-white shadow' : 'text-slate-400 hover:text-slate-250'
                          }`}
                        >
                          Auto
                        </button>
                        <button
                          type="button"
                          onClick={() => handleModeToggle(stratName, 'manual')}
                          className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                            isManual ? 'bg-purple-650 text-white shadow' : 'text-slate-400 hover:text-slate-250'
                          }`}
                        >
                          Manual
                        </button>
                      </div>
                    </div>

                    {isManual && (
                      <div className="pt-2 border-t border-slate-800/50">
                        <ScopedSymbolPicker
                          symbols={curatedSymbols}
                          selected={picks}
                          lockedSymbols={lockedSymbols}
                          globalClaimedByOthers={getGlobalClaimedByOthers(stratName)}
                          onToggle={(sym) => handleSymbolToggle(stratName, sym)}
                          maxManualSymbols={maxManualSymbols}
                        />
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* Step 3: Shared Risk & Params */}
        {step === 3 && (
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-gray-300 mb-3">Chaos Parameters</h3>
            
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-slate-400 font-medium mb-1">Timeframe</label>
                <select
                  value={timeframe}
                  onChange={(e) => setTimeframe(e.target.value)}
                  className="w-full h-10 rounded-lg border border-slate-700/50 bg-[#0a0d13] px-3 text-sm text-gray-100 focus:outline-none focus:border-purple-500 transition-colors"
                >
                  {TIMEFRAMES.map((tf) => (
                    <option key={tf} value={tf}>{tf}</option>
                  ))}
                </select>
              </div>
              
              <div>
                <label className="block text-xs text-slate-400 font-medium mb-1">Capital per Strategy (USDT)</label>
                <input
                  type="number"
                  value={capital}
                  min="1"
                  step="100"
                  onChange={(e) => setCapital(e.target.value)}
                  className="w-full h-10 rounded-lg border border-slate-700/50 bg-[#0a0d13] px-3 text-sm text-gray-100 focus:outline-none focus:border-purple-500 transition-colors"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs text-slate-400 font-medium mb-1">Leverage (1–125)</label>
              <input
                type="number"
                value={leverage}
                min="1"
                max="125"
                onChange={(e) => setLeverage(parseInt(e.target.value, 10) || 1)}
                className="w-full h-10 rounded-lg border border-slate-700/50 bg-[#0a0d13] px-3 text-sm text-gray-100 focus:outline-none focus:border-purple-500 transition-colors"
              />
              <p className="text-[10px] text-slate-500 mt-1">
                * Note: Server clamps leverage per-symbol based on Binance exchange caps.
              </p>
            </div>

            <div className="border-t border-slate-800 pt-4 mt-4">
              <p className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-1.5">
                <SettingsIcon size={14} className="text-purple-400" />
                Shared Risk Defaults
              </p>
              <RiskParamsFields
                values={risk}
                onChange={setRisk}
                inputClassName="w-full h-10 rounded-lg border border-slate-700/50 bg-[#0a0d13] px-3 text-sm text-gray-100 focus:outline-none focus:border-purple-500 transition-colors"
                labelClassName="block text-xs text-slate-400 font-medium mb-1"
              />
            </div>
          </div>
        )}

        {/* Step 4: Review and Deploy */}
        {step === 4 && (
          <div>
            <h3 className="text-sm font-semibold text-gray-300 mb-4">Review Chaos Run</h3>
            
            <div className="space-y-3 text-sm">
              <div className="flex justify-between py-2 border-b border-slate-800">
                <span className="text-slate-450">Active Timeframe</span>
                <span className="text-gray-100 font-medium">{timeframe}</span>
              </div>
              <div className="flex justify-between py-2 border-b border-slate-800">
                <span className="text-slate-450">Capital per Strategy</span>
                <span className="text-gray-100 font-medium">${parseFloat(capital).toLocaleString()}</span>
              </div>
              <div className="flex justify-between py-2 border-b border-slate-800">
                <span className="text-slate-450">Leverage</span>
                <span className="text-gray-100 font-medium">{leverage}x</span>
              </div>
              <div className="flex justify-between py-2 border-b border-slate-800">
                <span className="text-slate-450">Risk Constraints</span>
                <span className="text-gray-100 font-medium">
                  {risk.riskPct}% / trade · {risk.riskReward}:1 R:R · {risk.maxDrawdown}% max DD · {risk.minEdgeMult} edge mult
                </span>
              </div>
              <div className="flex justify-between py-2 border-b border-slate-800">
                <span className="text-slate-450">Target Environment</span>
                <span className="text-yellow-400 font-semibold flex items-center gap-1">
                  Binance Testnet (Paper)
                </span>
              </div>
              
              <div className="py-3 border-b border-slate-800">
                <span className="text-slate-450 block mb-2">Strategy Deployments ({activeStrategies.length})</span>
                <div className="space-y-2">
                  {activeStrategies.map(name => {
                    const s = preview.stats[name] || { total: 0 }
                    const isManual = strategyToggles[name] === 'manual'
                    return (
                      <div key={name} className="flex justify-between items-center text-xs bg-slate-950/50 px-3 py-2 rounded border border-slate-900">
                        <span className="text-slate-300 font-medium">{name}</span>
                        <span className="text-slate-400">
                          {isManual ? 'manual picks' : 'auto'} · <strong className="text-purple-400 font-semibold">{s.total}</strong> symbols
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>

            {/* Testnet alert warning */}
            <div className="mt-5 flex items-start gap-3 bg-amber-950/20 border border-amber-800/40 rounded-lg p-4">
              <AlertTriangle size={18} className="text-amber-400 shrink-0 mt-0.5" />
              <div>
                <p className="text-amber-350 text-xs font-semibold">Stress Test Invariant</p>
                <p className="text-slate-500 text-[11px] mt-1 leading-relaxed">
                  Chaos Mode launches multiple concurrent trading loops. Selected symbols will be locked in Redis, blocking manual entry on those markets until stopped. Ensure your Binance Testnet balance has sufficient funds to afford the initial margin.
                </p>
              </div>
            </div>
          </div>
        )}
      </div>

        {error && (
          <div className="flex items-start gap-2 bg-red-950/20 border border-red-800/40 rounded-lg p-4 text-sm text-red-400 shadow-lg">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" />
            <div className="flex-1">
              <span className="font-semibold block mb-0.5">Launch Error</span>
              <span className="text-xs leading-relaxed">{error}</span>
            </div>
            <button onClick={() => setError(null)} className="text-red-400/50 hover:text-red-400 font-bold text-xs ml-2">✕</button>
          </div>
        )}
      </div>
    </div>
  )
}
