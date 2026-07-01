import React, { useState, useEffect, Suspense } from 'react'
import toast from 'react-hot-toast'
import { AlertTriangle, X } from 'lucide-react'
import { ConfirmDialog } from '../components/ui/confirm-dialog'
import PageWrapper from '@/components/layout/PageWrapper'
import PageHeader from '@/components/ui/PageHeader'
import {
  useRiskSettings,
  useUpdateRiskSettings,
  useLiveRiskMetrics
} from '../hooks/useRiskSettings'
import { useStrategies } from '../hooks/useStrategies'

const CorrelationHeatmap = React.lazy(() => import('../components/risk/CorrelationHeatmap'))
const AggregateMarginGauge = React.lazy(() => import('../components/risk/AggregateMarginGauge'))
const NetExposureBar = React.lazy(() => import('../components/risk/NetExposureBar'))
const SimulationResults = React.lazy(() => import('../components/risk/SimulationResults'))

function InlineError({ error, onClear }) {
  if (!error) return null
  return (
    <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-800/40 bg-red-950/20 px-3 py-2 text-sm text-red-400">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <span className="flex-1">{error}</span>
      <button onClick={onClear} aria-label="Dismiss error" className="shrink-0 hover:text-red-300">
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}

function useBannerError() {
  const [error, setError] = useState(null)
  const clearError = () => setError(null)
  const banner = <InlineError error={error} onClear={clearError} />
  return { error, setError, clearError, banner }
}

export default function RiskDashboard() {
  const { data: settings, isLoading: settingsLoading } = useRiskSettings()
  const updateSettingsMutation = useUpdateRiskSettings()

  // Live polling metrics (automatically refetches every 10s)
  const { data: liveMetrics, isLoading: liveLoading } = useLiveRiskMetrics()

  // Load known strategy names for dropdown validation
  const { data: strategies = [] } = useStrategies()

  // ── Global Hard Limits Form State ─────────────────────────────────────────
  const [maxLeverageAllowed, setMaxLeverageAllowed] = useState('50')
  const [maxSessionDrawdown, setMaxSessionDrawdown] = useState('30')
  const [maxRiskPctPerTrade, setMaxRiskPctPerTrade] = useState('5')
  const [cooldownPeriodHours, setCooldownPeriodHours] = useState('12')

  // ── Strategy Overrides Editor State ───────────────────────────────────────
  const [selectedStrategy, setSelectedStrategy] = useState('')
  const [stratRiskPct, setStratRiskPct] = useState('')
  const [stratRRR, setStratRRR] = useState('')
  const [stratMaxDrawdown, setStratMaxDrawdown] = useState('')
  const [stratLiqBuffer, setStratLiqBuffer] = useState('')
  const [stratMinEdge, setStratMinEdge] = useState('')
  const [stratCustomAtr, setStratCustomAtr] = useState('')

  // ── Symbol Overrides Editor State ─────────────────────────────────────────
  const [selectedSymbol, setSelectedSymbol] = useState('')
  const [symMaxLeverage, setSymMaxLeverage] = useState('')
  const [symVolMult, setSymVolMult] = useState('')
  const [symMaxExposure, setSymMaxExposure] = useState('')

  // Success Feedback is handled by toast notifications

  // ── Per-section error banners ─────────────────────────────────────────────
  const globalLimitsError = useBannerError()
  const stratOverrideError = useBannerError()
  const symOverrideError = useBannerError()

  // ── Confirm dialogs for destructive actions ───────────────────────────────
  const [confirmDeleteStrat, setConfirmDeleteStrat] = useState(null)
  const [confirmDeleteSym, setConfirmDeleteSym] = useState(null)

  useEffect(() => {
    if (settings) {
      const g = settings.globalHardLimits || {}
      setMaxLeverageAllowed(String(g.maxLeverageAllowed ?? 50))
      setMaxSessionDrawdown(String((g.maxSessionDrawdown ?? 0.30) * 100))
      setMaxRiskPctPerTrade(String((g.maxRiskPctPerTrade ?? 0.05) * 100))
      setCooldownPeriodHours(String(g.cooldownPeriodHours ?? 12))
    }
  }, [settings])

  const handleSaveGlobalHardLimits = async (e) => {
    e.preventDefault()
    if (!settings) return

    const payload = {
      globalHardLimits: {
        maxLeverageAllowed: Number(maxLeverageAllowed),
        maxSessionDrawdown: Number(maxSessionDrawdown) / 100,
        maxRiskPctPerTrade: Number(maxRiskPctPerTrade) / 100,
        cooldownPeriodHours: Number(cooldownPeriodHours)
      },
      strategyOverrides: settings.strategyOverrides || {},
      symbolOverrides: settings.symbolOverrides || {}
    }

    try {
      await updateSettingsMutation.mutateAsync(payload)
      toast.success('Global hard limits saved successfully')
    } catch (err) {
      globalLimitsError.setError(`Save failed: ${err.response?.data?.error?.message || err.message}`)
    }
  }

  const handleAddStrategyOverride = async (e) => {
    e.preventDefault()
    if (!selectedStrategy || !settings) return

    const rules = {}
    if (stratRiskPct) rules.riskPct = Number(stratRiskPct) / 100
    if (stratRRR) rules.riskRewardRatio = Number(stratRRR)
    if (stratMaxDrawdown) rules.maxSessionDrawdown = Number(stratMaxDrawdown) / 100
    if (stratLiqBuffer) rules.liqBufferPct = Number(stratLiqBuffer) / 100
    if (stratMinEdge) rules.minEdgeMult = Number(stratMinEdge)
    if (stratCustomAtr) rules.customAtrMult = Number(stratCustomAtr)

    const updatedOverrides = { ...settings.strategyOverrides }
    updatedOverrides[selectedStrategy] = rules

    const payload = {
      globalHardLimits: settings.globalHardLimits || {},
      strategyOverrides: updatedOverrides,
      symbolOverrides: settings.symbolOverrides || {}
    }

    try {
      await updateSettingsMutation.mutateAsync(payload)
      toast.success(`Strategy override added/saved for ${selectedStrategy}`)
      setSelectedStrategy('')
      setStratRiskPct('')
      setStratRRR('')
      setStratMaxDrawdown('')
      setStratLiqBuffer('')
      setStratMinEdge('')
      setStratCustomAtr('')
    } catch (err) {
      stratOverrideError.setError(`Add failed: ${err.response?.data?.error?.message || err.message}`)
    }
  }

  const handleRemoveStrategyOverride = async (stratName) => {
    if (!settings) return
    const updatedOverrides = { ...settings.strategyOverrides }
    delete updatedOverrides[stratName]

    const payload = {
      globalHardLimits: settings.globalHardLimits || {},
      strategyOverrides: updatedOverrides,
      symbolOverrides: settings.symbolOverrides || {}
    }

    try {
      await updateSettingsMutation.mutateAsync(payload)
      toast.success(`Strategy override removed for ${stratName}`)
    } catch (err) {
      stratOverrideError.setError(`Remove failed: ${err.response?.data?.error?.message || err.message}`)
    }
  }

  const handleAddSymbolOverride = async (e) => {
    e.preventDefault()
    if (!selectedSymbol || !settings) return

    const rules = {}
    if (symMaxLeverage) rules.maxLeverage = Number(symMaxLeverage)
    if (symVolMult) rules.volatilityMultiplier = Number(symVolMult)
    if (symMaxExposure) rules.maxExposureNotional = Number(symMaxExposure)

    const updatedOverrides = { ...settings.symbolOverrides }
    updatedOverrides[selectedSymbol.toUpperCase()] = rules

    const payload = {
      globalHardLimits: settings.globalHardLimits || {},
      strategyOverrides: settings.strategyOverrides || {},
      symbolOverrides: updatedOverrides
    }

    try {
      await updateSettingsMutation.mutateAsync(payload)
      toast.success(`Symbol override added/saved for ${selectedSymbol.toUpperCase()}`)
      setSelectedSymbol('')
      setSymMaxLeverage('')
      setSymVolMult('')
      setSymMaxExposure('')
    } catch (err) {
      symOverrideError.setError(`Add failed: ${err.response?.data?.error?.message || err.message}`)
    }
  }

  const handleRemoveSymbolOverride = async (symbol) => {
    if (!settings) return
    const updatedOverrides = { ...settings.symbolOverrides }
    delete updatedOverrides[symbol]

    const payload = {
      globalHardLimits: settings.globalHardLimits || {},
      strategyOverrides: settings.strategyOverrides || {},
      symbolOverrides: updatedOverrides
    }

    try {
      await updateSettingsMutation.mutateAsync(payload)
      toast.success(`Symbol override removed for ${symbol}`)
    } catch (err) {
      symOverrideError.setError(`Remove failed: ${err.response?.data?.error?.message || err.message}`)
    }
  }

  return (
    <PageWrapper>
      <PageHeader title="Risk Intelligence Dashboard" subtitle="Manage safety circuit breakers and trade risk profiles" />

      <ConfirmDialog
        open={!!confirmDeleteStrat}
        onOpenChange={(v) => { if (!v) setConfirmDeleteStrat(null) }}
        title={`Delete strategy override for ${confirmDeleteStrat}?`}
        description="The custom risk rules for this strategy will be removed."
        confirmLabel="Delete"
        onConfirm={() => { const s = confirmDeleteStrat; setConfirmDeleteStrat(null); handleRemoveStrategyOverride(s) }}
      />
      <ConfirmDialog
        open={!!confirmDeleteSym}
        onOpenChange={(v) => { if (!v) setConfirmDeleteSym(null) }}
        title={`Delete symbol override for ${confirmDeleteSym}?`}
        description="The custom risk rules for this symbol will be removed."
        confirmLabel="Delete"
        onConfirm={() => { const s = confirmDeleteSym; setConfirmDeleteSym(null); handleRemoveSymbolOverride(s) }}
      />

      {settingsLoading && (
        <div className="text-center font-mono py-12 text-xs text-slate-400 italic">
          Loading risk configurations...
        </div>
      )}

      {!settingsLoading && settings && (
        <div className="flex flex-col gap-6 select-none pb-12">
          
          {/* ────────────────── ZONE 1: REAL-TIME PORTFOLIO RISK ────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <Suspense fallback={<div className="h-44 bg-slate-950 border border-slate-850 animate-pulse rounded-lg" />}>
              <AggregateMarginGauge
                marginUsed={liveMetrics?.aggregateMarginUsed}
                walletBalance={liveMetrics?.aggregateWalletBalance}
                netLeverage={liveMetrics?.netLeverage}
              />
            </Suspense>
            <Suspense fallback={<div className="h-44 bg-slate-950 border border-slate-850 animate-pulse rounded-lg" />}>
              <NetExposureBar exposures={liveMetrics?.exposures} />
            </Suspense>
            <Suspense fallback={<div className="h-44 bg-slate-950 border border-slate-850 animate-pulse rounded-lg" />}>
              <CorrelationHeatmap matrix={liveMetrics?.correlationMatrix} />
            </Suspense>
          </div>

          {/* Live VaR Banner */}
          {liveMetrics && (
            <div className="bg-[#0b0f19] border border-slate-800 p-4 grid grid-cols-1 md:grid-cols-3 gap-4 font-mono text-center">
              <div>
                <span className="text-[9px] uppercase tracking-wider text-slate-400 block">Value-at-Risk (95% 1d)</span>
                <span className="text-sm font-semibold text-red-400">${parseFloat(liveMetrics.valueAtRisk.var95_1d).toFixed(2)}</span>
              </div>
              <div>
                <span className="text-[9px] uppercase tracking-wider text-slate-400 block">Value-at-Risk (99% 1d)</span>
                <span className="text-sm font-semibold text-red-400">${parseFloat(liveMetrics.valueAtRisk.var99_1d).toFixed(2)}</span>
              </div>
              <div>
                <span className="text-[9px] uppercase tracking-wider text-slate-400 block">Conditional VaR (95% 1d)</span>
                <span className="text-sm font-semibold text-red-400">${parseFloat(liveMetrics.valueAtRisk.cvar95_1d).toFixed(2)}</span>
              </div>
            </div>
          )}

          {/* ────────────────── ZONE 2: PARAMETER CONTROLS ────────────────── */}
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
            
            {/* Global Hard Limits Form */}
            <div className="bg-slate-950 border border-slate-800 p-5 shadow-2xl flex flex-col justify-between">
              <form onSubmit={handleSaveGlobalHardLimits}>
                <h3 className="text-[11px] font-semibold text-gray-300 uppercase tracking-wider mb-2">
                  Global Hard Limits
                </h3>
                <p className="text-xs text-slate-400 mb-4">Hard constraints acting as platform circuit breakers</p>

                <div className="flex flex-col gap-4 font-mono text-xs">
                  <div>
                    <label className="text-slate-200 font-semibold block mb-1 text-[10px] uppercase">Max Leverage Allowed</label>
                    <input
                      type="number"
                      className="bg-slate-900 border border-slate-800/80 w-full px-2.5 py-1.5 text-slate-200 outline-none focus:border-emerald-500 placeholder-slate-600"
                      value={maxLeverageAllowed}
                      onChange={(e) => setMaxLeverageAllowed(e.target.value)}
                      min="1"
                      max="125"
                      required
                    />
                  </div>
                  <div>
                    <label className="text-slate-200 font-semibold block mb-1 text-[10px] uppercase">Max Session Drawdown %</label>
                    <input
                      type="number"
                      className="bg-slate-900 border border-slate-800/80 w-full px-2.5 py-1.5 text-slate-200 outline-none focus:border-emerald-500 placeholder-slate-600"
                      value={maxSessionDrawdown}
                      onChange={(e) => setMaxSessionDrawdown(e.target.value)}
                      min="5"
                      max="90"
                      required
                    />
                  </div>
                  <div>
                    <label className="text-slate-200 font-semibold block mb-1 text-[10px] uppercase">Max Risk % Per Trade</label>
                    <input
                      type="number"
                      className="bg-slate-900 border border-slate-800/80 w-full px-2.5 py-1.5 text-slate-200 outline-none focus:border-emerald-500 placeholder-slate-600"
                      value={maxRiskPctPerTrade}
                      onChange={(e) => setMaxRiskPctPerTrade(e.target.value)}
                      min="0.1"
                      max="20"
                      step="0.1"
                      required
                    />
                  </div>
                  <div>
                    <label className="text-slate-200 font-semibold block mb-1 text-[10px] uppercase">Cooldown Period (Hours)</label>
                    <input
                      type="number"
                      className="bg-slate-900 border border-slate-800/80 w-full px-2.5 py-1.5 text-slate-200 outline-none focus:border-emerald-500 placeholder-slate-600"
                      value={cooldownPeriodHours}
                      onChange={(e) => setCooldownPeriodHours(e.target.value)}
                      min="1"
                      max="72"
                      required
                    />
                  </div>
                </div>

                <button
                  type="submit"
                  className="mt-6 w-full bg-slate-800 hover:bg-slate-750 active:bg-slate-700 text-slate-200 border border-slate-700 py-2 px-4 font-mono text-xs uppercase transition-colors"
                  disabled={updateSettingsMutation.isPending}
                >
                  {updateSettingsMutation.isPending ? 'Saving...' : 'Save Global Limits'}
                </button>
              </form>

              {globalLimitsError.banner}
            </div>

            {/* Strategy Overrides Editor */}
            <div className="bg-slate-950 border border-slate-800 p-5 shadow-2xl flex flex-col justify-between">
              <div>
                <h3 className="text-[11px] font-semibold text-gray-300 uppercase tracking-wider mb-2">
                  Strategy Overrides
                </h3>
                <p className="text-xs text-slate-400 mb-4">Set overrides specifically matching strategy classes</p>

                {/* Overrides Table */}
                <div className="border border-slate-850 max-h-40 overflow-y-auto mb-4 font-mono text-xs">
                  {Object.keys(settings.strategyOverrides || {}).length === 0 ? (
                    <p className="text-[10px] text-slate-600 italic text-center py-6">No custom strategy overrides configured.</p>
                  ) : (
                    <table className="w-full text-left">
                      <thead>
                        <tr className="border-b border-slate-800 bg-slate-900/40 text-[9px] uppercase text-slate-400 tracking-wider">
                          <th className="p-2">Strategy</th>
                          <th className="p-2">Risk/RR/Drawdown</th>
                          <th className="p-2 text-right">Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(settings.strategyOverrides || {}).map(([stratName, rules]) => (
                          <tr key={stratName} className="border-b border-slate-900/60 hover:bg-slate-900/20">
                            <td className="p-2 text-slate-200 font-bold">{stratName}</td>
                            <td className="p-2 text-slate-400 text-[10px]">
                              {rules.riskPct && `Risk: ${(rules.riskPct * 100).toFixed(2)}% `}
                              {rules.riskRewardRatio && `RR: ${rules.riskRewardRatio} `}
                              {rules.maxSessionDrawdown && `DD: ${(rules.maxSessionDrawdown * 100).toFixed(0)}%`}
                            </td>
                            <td className="p-2 text-right">
                              <button
                                onClick={() => setConfirmDeleteStrat(stratName)}
                                className="text-red-400 hover:text-red-300 text-[10px] font-bold uppercase"
                              >
                                Delete
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>

              {/* Add/Edit form */}
              <form onSubmit={handleAddStrategyOverride} className="border-t border-slate-800/60 pt-4">
                <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                  <div className="col-span-2">
                    <label className="text-[9px] uppercase text-slate-200 font-semibold tracking-wider block mb-0.5">Strategy Name</label>
                    <select
                      className="bg-slate-900 border border-slate-800 w-full px-2 py-1 outline-none focus:border-emerald-500 text-slate-200 text-xs"
                      value={selectedStrategy}
                      onChange={(e) => setSelectedStrategy(e.target.value)}
                      required
                    >
                      <option value="">Select Strategy</option>
                      {strategies.map((s) => (
                        <option key={s.name} value={s.name}>
                          {s.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="text-[9px] uppercase text-slate-200 font-semibold tracking-wider block mb-0.5">Risk %</label>
                    <input
                      type="number"
                      className="bg-slate-900 border border-slate-800 w-full px-2 py-1 outline-none focus:border-emerald-500 text-slate-200 placeholder-slate-600"
                      value={stratRiskPct}
                      onChange={(e) => setStratRiskPct(e.target.value)}
                      placeholder="e.g. 1.5"
                      min="0.01"
                      max="20"
                      step="0.01"
                    />
                  </div>
                  <div>
                    <label className="text-[9px] uppercase text-slate-200 font-semibold tracking-wider block mb-0.5">RR Ratio</label>
                    <input
                      type="number"
                      className="bg-slate-900 border border-slate-800 w-full px-2 py-1 outline-none focus:border-emerald-500 text-slate-200 placeholder-slate-600"
                      value={stratRRR}
                      onChange={(e) => setStratRRR(e.target.value)}
                      placeholder="e.g. 2.5"
                      min="0.1"
                      max="100"
                      step="0.1"
                    />
                  </div>
                  <div>
                    <label className="text-[9px] uppercase text-slate-200 font-semibold tracking-wider block mb-0.5">Max DD %</label>
                    <input
                      type="number"
                      className="bg-slate-900 border border-slate-800 w-full px-2 py-1 outline-none focus:border-emerald-500 text-slate-200 placeholder-slate-600"
                      value={stratMaxDrawdown}
                      onChange={(e) => setStratMaxDrawdown(e.target.value)}
                      placeholder="e.g. 15"
                      min="1"
                      max="90"
                    />
                  </div>
                  <div>
                    <label className="text-[9px] uppercase text-slate-200 font-semibold tracking-wider block mb-0.5">Custom Stop ATR</label>
                    <input
                      type="number"
                      className="bg-slate-900 border border-slate-800 w-full px-2 py-1 outline-none focus:border-emerald-500 text-slate-200 placeholder-slate-600"
                      value={stratCustomAtr}
                      onChange={(e) => setStratCustomAtr(e.target.value)}
                      placeholder="e.g. 2.5"
                      min="0.1"
                      max="10"
                      step="0.1"
                    />
                  </div>
                </div>

                <button
                  type="submit"
                  className="mt-4 w-full bg-slate-800 hover:bg-slate-750 active:bg-slate-700 text-slate-200 border border-slate-700 py-1.5 px-4 font-mono text-xs uppercase"
                  disabled={!selectedStrategy}
                >
                  Add / Save Override
                </button>
              </form>
              {stratOverrideError.banner}
            </div>

            {/* Symbol Overrides Editor */}
            <div className="bg-slate-950 border border-slate-800 p-5 shadow-2xl flex flex-col justify-between">
              <div>
                <h3 className="text-[11px] font-semibold text-gray-300 uppercase tracking-wider mb-2">
                  Symbol Overrides
                </h3>
                <p className="text-xs text-slate-400 mb-4">Set overrides specifically matching traded assets</p>

                {/* Overrides Table */}
                <div className="border border-slate-850 max-h-40 overflow-y-auto mb-4 font-mono text-xs">
                  {Object.keys(settings.symbolOverrides || {}).length === 0 ? (
                    <p className="text-[10px] text-slate-600 italic text-center py-6">No custom symbol overrides configured.</p>
                  ) : (
                    <table className="w-full text-left">
                      <thead>
                        <tr className="border-b border-slate-800 bg-slate-900/40 text-[9px] uppercase text-slate-400 tracking-wider">
                          <th className="p-2">Symbol</th>
                          <th className="p-2">Leverage/Vol/Exposure</th>
                          <th className="p-2 text-right">Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(settings.symbolOverrides || {}).map(([symbol, rules]) => (
                          <tr key={symbol} className="border-b border-slate-900/60 hover:bg-slate-900/20">
                            <td className="p-2 text-slate-200 font-bold">{symbol}</td>
                            <td className="p-2 text-slate-400 text-[10px]">
                              {rules.maxLeverage && `Lev: ${rules.maxLeverage}x `}
                              {rules.volatilityMultiplier && `Vol: ${rules.volatilityMultiplier}x `}
                              {rules.maxExposureNotional && `Exp: $${rules.maxExposureNotional}`}
                            </td>
                            <td className="p-2 text-right">
                              <button
                                onClick={() => setConfirmDeleteSym(symbol)}
                                className="text-red-400 hover:text-red-300 text-[10px] font-bold uppercase"
                              >
                                Delete
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>

              {/* Add/Edit form */}
              <form onSubmit={handleAddSymbolOverride} className="border-t border-slate-800/60 pt-4">
                <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                  <div className="col-span-2">
                    <label className="text-[9px] uppercase text-slate-200 font-semibold tracking-wider block mb-0.5">Symbol</label>
                    <input
                      type="text"
                      className="bg-slate-900 border border-slate-800 w-full px-2 py-1 outline-none focus:border-emerald-500 text-slate-200 uppercase placeholder-slate-600"
                      value={selectedSymbol}
                      onChange={(e) => setSelectedSymbol(e.target.value)}
                      placeholder="e.g. BTCUSDT"
                      required
                    />
                  </div>
                  <div>
                    <label className="text-[9px] uppercase text-slate-200 font-semibold tracking-wider block mb-0.5">Max Leverage</label>
                    <input
                      type="number"
                      className="bg-slate-900 border border-slate-800 w-full px-2 py-1 outline-none focus:border-emerald-500 text-slate-200 placeholder-slate-600"
                      value={symMaxLeverage}
                      onChange={(e) => setSymMaxLeverage(e.target.value)}
                      placeholder="e.g. 20"
                    />
                  </div>
                  <div>
                    <label className="text-[9px] uppercase text-slate-200 font-semibold tracking-wider block mb-0.5">Volatility Multiplier</label>
                    <input
                      type="number"
                      step="0.1"
                      className="bg-slate-900 border border-slate-800 w-full px-2 py-1 outline-none focus:border-emerald-500 text-slate-200 placeholder-slate-600"
                      value={symVolMult}
                      onChange={(e) => setSymVolMult(e.target.value)}
                      placeholder="e.g. 1.5"
                    />
                  </div>
                  <div className="col-span-2">
                    <label className="text-[9px] uppercase text-slate-200 font-semibold tracking-wider block mb-0.5">Max Exposure Notional ($)</label>
                    <input
                      type="number"
                      className="bg-slate-900 border border-slate-800 w-full px-2 py-1 outline-none focus:border-emerald-500 text-slate-200 placeholder-slate-600"
                      value={symMaxExposure}
                      onChange={(e) => setSymMaxExposure(e.target.value)}
                      placeholder="e.g. 5000"
                    />
                  </div>
                </div>
                <button
                  type="submit"
                  className="mt-4 w-full bg-slate-800 hover:bg-slate-750 active:bg-slate-700 text-slate-200 border border-slate-700 py-1.5 px-4 font-mono text-xs uppercase"
                  disabled={!selectedSymbol}
                >
                  Add / Save Override
                </button>
              </form>
              {symOverrideError.banner}
            </div>

          </div>

          {/* ────────────────── ZONE 3: HISTORICAL RISK PROFILER ────────────────── */}
          <div className="grid grid-cols-1 gap-6">
            <Suspense fallback={<div className="h-96 bg-slate-950 border border-slate-850 animate-pulse rounded-lg" />}>
              <SimulationResults />
            </Suspense>
          </div>

        </div>
      )}
    </PageWrapper>
  )
}