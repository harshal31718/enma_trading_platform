// Plan 7 Step 7.4 (CLI-1): extracted out of Settings.jsx.
import { useState, useEffect } from 'react'
import { Zap } from 'lucide-react'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/button'
import { useExchangeSettings, useUpdateExchangeSettings } from '@/hooks/useExchangeSettings'
import { inputCls, labelCls, skeletonCls } from './styles'

export default function ChaosSettingsCard() {
  const [chaosMaxManualSymbols, setChaosMaxManualSymbols] = useState('5')
  const [chaosDefaultCapital, setChaosDefaultCapital] = useState('500')
  const [chaosDefaultLeverage, setChaosDefaultLeverage] = useState('50')
  const [chaosDefaultTimeframe, setChaosDefaultTimeframe] = useState('1m')
  const [chaosMaxTotalSymbols, setChaosMaxTotalSymbols] = useState('120')

  const { data: exchangeSettings, isLoading: settingsLoading } = useExchangeSettings()
  const updateMutation = useUpdateExchangeSettings()

  useEffect(() => {
    if (exchangeSettings) {
      setChaosMaxManualSymbols(String(exchangeSettings.chaosMaxManualSymbols ?? 5))
      setChaosDefaultCapital(String(exchangeSettings.chaosDefaultCapital ?? 500))
      setChaosDefaultLeverage(String(exchangeSettings.chaosDefaultLeverage ?? 50))
      setChaosDefaultTimeframe(exchangeSettings.chaosDefaultTimeframe ?? '1m')
      setChaosMaxTotalSymbols(String(exchangeSettings.chaosMaxTotalSymbols ?? 120))
    }
  }, [exchangeSettings])

  function handleChaosSubmit(e) {
    e.preventDefault()
    updateMutation.mutate(
      {
        chaosMaxManualSymbols: parseInt(chaosMaxManualSymbols, 10),
        chaosDefaultCapital:   parseFloat(chaosDefaultCapital),
        chaosDefaultLeverage:  parseInt(chaosDefaultLeverage, 10),
        chaosDefaultTimeframe,
        chaosMaxTotalSymbols:  parseInt(chaosMaxTotalSymbols, 10),
      },
      {
        onSuccess: () => {
          toast.success('Chaos settings saved successfully')
        },
        onError: (err) => {
          toast.error(err.response?.data?.error?.message || err.message || 'Failed to save settings')
        }
      }
    )
  }

  return (
    <div className="bg-title-bg border border-purple-700/30 rounded-xl p-6">
      {/* Header */}
      <div className="flex items-center justify-between -mx-6 -mt-6 px-6 py-4 mb-4 rounded-t-xl title-fade border-b border-slate-700/50">
        <h2 className="text-gray-100 text-sm font-medium flex items-center gap-2">
          <Zap size={15} className="text-purple-400" />
          Chaos Settings
        </h2>
        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold border bg-purple-500/10 text-purple-400 border-purple-500/20">
          <span className="h-1.5 w-1.5 rounded-full bg-purple-400 animate-pulse" />
          Stress Test
        </span>
      </div>

      {/* Chaos settings feedback is handled by toast notifications */}

      <form onSubmit={handleChaosSubmit} noValidate>
        {/* ── Caps ──────────────────────────────────────────────────────── */}
        <p className="text-gray-300 text-xs font-semibold mb-3">Caps</p>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>Max Manual Symbols per Strategy (0–20)</label>
            {settingsLoading
              ? <div className={skeletonCls} />
              : <input type="number" min="0" max="20" value={chaosMaxManualSymbols}
                  onChange={(e) => setChaosMaxManualSymbols(e.target.value)} className={inputCls} required />}
            <p className="text-slate-400 text-[10px] mt-1">0 = all auto; the rest are distributed from the pool</p>
          </div>
          <div>
            <label className={labelCls}>Max Total Symbols per Chaos Run (1–250)</label>
            {settingsLoading
              ? <div className={skeletonCls} />
              : <input type="number" min="1" max="250" value={chaosMaxTotalSymbols}
                  onChange={(e) => setChaosMaxTotalSymbols(e.target.value)} className={inputCls} required />}
            <p className="text-slate-400 text-[10px] mt-1">Ceiling on symbols across the whole run (all strategies combined)</p>
          </div>
        </div>
        <p className="text-slate-400 text-[10px] mt-3">
          How many strategies run is bounded by "Max Concurrent Bots" under Environment Configuration →
          Bot Session Limits — not configured here.
        </p>

        {/* ── Launch defaults ───────────────────────────────────────────── */}
        <div className="border-t border-slate-700/50 pt-5 mt-5">
          <p className="text-gray-300 text-xs font-semibold mb-3">Launch Defaults</p>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className={labelCls}>Capital / Strategy ($)</label>
              {settingsLoading
                ? <div className={skeletonCls} />
                : <input type="number" min="1" value={chaosDefaultCapital}
                    onChange={(e) => setChaosDefaultCapital(e.target.value)} className={inputCls} required />}
            </div>
            <div>
              <label className={labelCls}>Leverage (1–125)</label>
              {settingsLoading
                ? <div className={skeletonCls} />
                : <input type="number" min="1" max="125" value={chaosDefaultLeverage}
                    onChange={(e) => setChaosDefaultLeverage(e.target.value)} className={inputCls} required />}
            </div>
            <div>
              <label className={labelCls}>Timeframe</label>
              {settingsLoading
                ? <div className={skeletonCls} />
                : <select value={chaosDefaultTimeframe}
                    onChange={(e) => setChaosDefaultTimeframe(e.target.value)}
                    className={inputCls}>
                    {['1m','3m','5m','15m','30m','1h','2h','4h','6h','8h','12h','1d'].map((tf) => (
                      <option key={tf} value={tf}>{tf}</option>
                    ))}
                  </select>}
            </div>
          </div>
        </div>

        <div className="mt-6">
          <Button
            type="submit"
            disabled={updateMutation.isPending || settingsLoading}
            className="bg-purple-700 hover:bg-purple-800 text-white"
          >
            {updateMutation.isPending ? 'Saving…' : 'Save Chaos Settings'}
          </Button>
        </div>
      </form>
    </div>
  )
}
