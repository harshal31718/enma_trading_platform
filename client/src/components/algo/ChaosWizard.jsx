import { useState, useEffect, useRef, useMemo } from 'react'
import { ChevronRight, ChevronLeft, AlertTriangle, Zap, Play, X } from 'lucide-react'
import { useStrategies } from '../../hooks/useStrategies'
import { useStartChaos, useLockedSymbols, useChaosSymbols } from '../../hooks/useAlgoSessions'
import { useExchangeSettings } from '../../hooks/useExchangeSettings'
import { RISK_DEFAULTS, riskDefaultsFromSettings } from '../RiskParamsFields'
import Step1Strategies from './chaos/Step1Strategies'
import Step2Allocation from './chaos/Step2Allocation'
import Step3Parameters from './chaos/Step3Parameters'
import Step4Review from './chaos/Step4Review'

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

  // Chaos limits from settings. chaosMaxStrategies was removed server-side (2026-07-03) —
  // limits.testnet.maxConcurrentBots is now the one cap governing both manual bots and Chaos
  // Mode strategy count. maxSymbolsPerBot/chaosMaxTotalSymbols bound the allocation preview
  // below, mirroring server/src/utils/chaosAllocator.js exactly.
  const maxStrategies = exchangeSettings?.limits?.testnet?.maxConcurrentBots ?? 10
  const maxSymbolsPerBot = exchangeSettings?.limits?.testnet?.maxSymbolsPerBot ?? 15
  const chaosMaxTotalSymbols = exchangeSettings?.chaosMaxTotalSymbols ?? 120
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

    // 4. Distribute, bounded by maxSymbolsPerBot (per strategy) and chaosMaxTotalSymbols
    //    (run-wide) — mirrors server/src/utils/chaosAllocator.js's Step 4 exactly so this
    //    preview matches what the server will actually allocate.
    const assignments = {}
    const stats = {}
    let runningTotal = 0
    for (const strat of activeStrategies) {
      assignments[strat] = [...reservedMap[strat]]
      runningTotal += reservedMap[strat].size
      stats[strat] = {
        high: curatedSymbols.filter(s => s.tier === 'high' && reservedMap[strat].has(s.symbol)).length,
        mid: curatedSymbols.filter(s => s.tier === 'mid' && reservedMap[strat].has(s.symbol)).length,
        low: curatedSymbols.filter(s => s.tier === 'low' && reservedMap[strat].has(s.symbol)).length,
        total: reservedMap[strat].size
      }
    }

    const n = activeStrategies.length
    let dropped = 0

    for (const [tierBucket, tierKey] of [[high, 'high'], [mid, 'mid'], [low, 'low']]) {
      let i = 0
      for (const sym of tierBucket) {
        if (runningTotal >= chaosMaxTotalSymbols) {
          dropped++
          continue
        }

        let placed = false
        for (let tries = 0; tries < n; tries++) {
          const strat = activeStrategies[(i + tries) % n]
          if (assignments[strat].length < maxSymbolsPerBot) {
            assignments[strat].push(sym)
            stats[strat][tierKey]++
            stats[strat].total++
            runningTotal++
            placed = true
            i = i + tries + 1
            break
          }
        }
        if (!placed) {
          dropped++
          i++
        }
      }
    }

    return { assignments, stats, dropped }
  }, [activeStrategies, strategyToggles, manualPicks, curatedSymbols, lockedSymbols, maxSymbolsPerBot, chaosMaxTotalSymbols])

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
        <div className="flex-1 flex justify-center min-w-0">
          {/* Mobile step info */}
          <div className="flex sm:hidden flex-col items-center select-none font-mono">
            <span className="text-[10px] text-slate-500 uppercase tracking-widest leading-none mb-1">
              Step {step} of 4
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
                  className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold ${
                    i + 1 < step
                      ? 'bg-purple-600 text-white'
                      : i + 1 === step
                      ? 'bg-purple-600/30 text-purple-400 border border-purple-500'
                      : 'bg-slate-800 text-slate-400'
                  }`}
                >
                  {i + 1}
                </div>
                <span className={`text-xs ${i + 1 === step ? 'text-gray-200 font-medium' : 'text-slate-400'}`}>
                  {label}
                </span>
                {i < stepLabels.length - 1 && <ChevronRight size={14} className="text-slate-700" />}
              </div>
            ))}
          </div>
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
        {step === 1 && (
          <Step1Strategies
            strategies={strategies}
            selectedStrategyNames={selectedStrategyNames}
            maxStrategies={maxStrategies}
            onToggle={handleStrategyToggleSelect}
          />
        )}

        {step === 2 && (
          <Step2Allocation
            activeStrategies={activeStrategies}
            strategyToggles={strategyToggles}
            manualPicks={manualPicks}
            preview={preview}
            curatedSymbols={curatedSymbols}
            lockedSymbols={lockedSymbols}
            maxManualSymbols={maxManualSymbols}
            onModeToggle={handleModeToggle}
            onSymbolToggle={handleSymbolToggle}
            getGlobalClaimedByOthers={getGlobalClaimedByOthers}
          />
        )}

        {step === 3 && (
          <Step3Parameters
            timeframe={timeframe}
            setTimeframe={setTimeframe}
            capital={capital}
            setCapital={setCapital}
            leverage={leverage}
            setLeverage={setLeverage}
            risk={risk}
            setRisk={setRisk}
          />
        )}

        {step === 4 && (
          <Step4Review
            timeframe={timeframe}
            capital={capital}
            leverage={leverage}
            risk={risk}
            activeStrategies={activeStrategies}
            preview={preview}
            strategyToggles={strategyToggles}
          />
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
