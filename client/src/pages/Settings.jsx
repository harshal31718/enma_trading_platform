import { useState, useEffect, useRef } from 'react'
import { Server, Zap, CheckCircle2, Clock, X, AlertTriangle, KeyRound } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import api from '../lib/axios'
import PageWrapper from '@/components/layout/PageWrapper'
import PageHeader from '@/components/ui/PageHeader'
import { useExchangeSettings, useUpdateExchangeSettings } from '../hooks/useExchangeSettings'
import RiskParamsFields, { RISK_DEFAULTS, riskDefaultsFromSettings, riskFieldsToPayload } from '../components/RiskParamsFields'

export default function Settings() {
  const queryClient = useQueryClient()
  const [showComingSoon, setShowComingSoon] = useState(false)
  const comingSoonTimerRef = useRef(null)

  // ── API Keys form state ───────────────────────────────────────────────────
  const [apiKey, setApiKey] = useState('')
  const [apiSecret, setApiSecret] = useState('')

  const { data: keysStatus } = useQuery({
    queryKey: ['trade', 'settings-keys'],
    queryFn: async () => {
      const res = await api.get('/api/v1/trade/settings/keys')
      return res.data.data
    },
  })

  const saveKeysMutation = useMutation({
    mutationFn: async (payload) => {
      const res = await api.post('/api/v1/trade/settings/keys', payload)
      return res.data.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trade', 'settings-keys'] })
      setApiKey('')
      setApiSecret('')
      toast.success('API keys saved successfully')
    },
    onError: (err) => {
      toast.error(err.response?.data?.error?.message || err.message || 'Failed to save API keys')
    }
  })

  function handleApiKeySubmit(e) {
    e.preventDefault()
    if (!apiKey && !apiSecret) return
    const payload = {}
    if (apiKey) payload.apiKey = apiKey
    if (apiSecret) payload.apiSecret = apiSecret
    saveKeysMutation.mutate(payload)
  }

  // ── Exchange settings form state ──────────────────────────────────────────
  const [takerFee, setTakerFee] = useState('')
  const [makerFee, setMakerFee] = useState('')
  const [defaultCapital, setDefaultCapital] = useState('')
  const [defaultLeverage, setDefaultLeverage] = useState('')
  const [defaultBotCapital, setDefaultBotCapital] = useState('')
  const [defaultBotLeverage, setDefaultBotLeverage] = useState('')
  const [slippagePct, setSlippagePct] = useState('')
  const [fundingEnabled, setFundingEnabled] = useState(false)
  const [fundingRate, setFundingRate] = useState('')
  const [risk, setRisk] = useState(RISK_DEFAULTS)

  // ── Chaos settings form state ─────────────────────────────────────────────
  const [chaosMaxStrategies, setChaosMaxStrategies] = useState('10')
  const [chaosMaxManualSymbols, setChaosMaxManualSymbols] = useState('5')
  const [chaosDefaultCapital, setChaosDefaultCapital] = useState('500')
  const [chaosDefaultLeverage, setChaosDefaultLeverage] = useState('50')
  const [chaosDefaultTimeframe, setChaosDefaultTimeframe] = useState('1m')

  const { data: exchangeSettings, isLoading: settingsLoading } = useExchangeSettings()
  const updateMutation = useUpdateExchangeSettings()

  useEffect(() => {
    return () => {
      if (comingSoonTimerRef.current) clearTimeout(comingSoonTimerRef.current)
    }
  }, [])

  useEffect(() => {
    if (exchangeSettings) {
      setTakerFee(String(((exchangeSettings.takerFee ?? 0.0005) * 100).toPrecision(4).replace(/\.?0+$/, '')))
      setMakerFee(String(((exchangeSettings.makerFee ?? 0.0002) * 100).toPrecision(4).replace(/\.?0+$/, '')))
      setDefaultCapital(String(exchangeSettings.defaultCapital ?? 10000))
      setDefaultLeverage(String(exchangeSettings.defaultLeverage ?? 1))
      setDefaultBotCapital(String(exchangeSettings.defaultBotCapital ?? 1000))
      setDefaultBotLeverage(String(exchangeSettings.defaultBotLeverage ?? 1))
      setSlippagePct(String(((exchangeSettings.slippagePct ?? 0.0005) * 100).toPrecision(4).replace(/\.?0+$/, '')))
      setFundingEnabled(exchangeSettings.fundingEnabled ?? false)
      setFundingRate(String(((exchangeSettings.fundingRate ?? 0.0001) * 100).toPrecision(4).replace(/\.?0+$/, '')))
      setRisk(riskDefaultsFromSettings(exchangeSettings))
      // Chaos defaults
      setChaosMaxStrategies(String(exchangeSettings.chaosMaxStrategies ?? 10))
      setChaosMaxManualSymbols(String(exchangeSettings.chaosMaxManualSymbols ?? 5))
      setChaosDefaultCapital(String(exchangeSettings.chaosDefaultCapital ?? 500))
      setChaosDefaultLeverage(String(exchangeSettings.chaosDefaultLeverage ?? 50))
      setChaosDefaultTimeframe(exchangeSettings.chaosDefaultTimeframe ?? '1m')
    }
  }, [exchangeSettings])

  function handleExchangeSubmit(e) {
    e.preventDefault()
    updateMutation.mutate(
      {
        takerFee:         parseFloat(takerFee) / 100,
        makerFee:         parseFloat(makerFee) / 100,
        defaultCapital:   parseFloat(defaultCapital),
        defaultLeverage:  parseInt(defaultLeverage, 10),
        defaultBotCapital:  parseFloat(defaultBotCapital),
        defaultBotLeverage: parseInt(defaultBotLeverage, 10),
        slippagePct:      parseFloat(slippagePct) / 100,
        fundingEnabled,
        fundingRate:      parseFloat(fundingRate) / 100,
        ...riskFieldsToPayload(risk),
      },
      {
        onSuccess: () => {
          toast.success('Exchange settings saved successfully')
        },
        onError: (err) => {
          toast.error(err.response?.data?.error?.message || err.message || 'Failed to save settings')
        }
      }
    )
  }

  function handleChaosSubmit(e) {
    e.preventDefault()
    updateMutation.mutate(
      {
        chaosMaxStrategies:    parseInt(chaosMaxStrategies, 10),
        chaosMaxManualSymbols: parseInt(chaosMaxManualSymbols, 10),
        chaosDefaultCapital:   parseFloat(chaosDefaultCapital),
        chaosDefaultLeverage:  parseInt(chaosDefaultLeverage, 10),
        chaosDefaultTimeframe,
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

  const inputCls =
    'h-10 w-full rounded-lg border border-slate-700/50 bg-[#0a0d13] px-3 text-sm text-gray-100 focus:outline-none focus:border-emerald-500 transition-colors'
  const labelCls = 'text-slate-400 text-xs font-medium'
  const skeletonCls = 'h-10 w-full bg-slate-800/50 rounded animate-pulse'

  function handleMainnetClick() {
    if (comingSoonTimerRef.current) clearTimeout(comingSoonTimerRef.current)
    setShowComingSoon(true)
    comingSoonTimerRef.current = setTimeout(() => setShowComingSoon(false), 4000)
  }

  return (
    <PageWrapper>
      <PageHeader title="Settings" />

      {/* Coming Soon Toast */}
      {showComingSoon && (
        <div
          className="fixed top-5 right-5 z-50 flex items-start gap-3 rounded-xl border border-amber-500/30 bg-amber-950/80 backdrop-blur-md px-5 py-4 shadow-2xl shadow-amber-900/30"
          style={{ animation: 'slideIn 0.25s ease-out' }}
        >
          <Clock size={18} className="text-amber-400 mt-0.5 shrink-0" />
          <div>
            <p className="text-amber-300 text-sm font-semibold">Mainnet — Coming Soon</p>
            <p className="text-amber-500/80 text-xs mt-0.5">Live trading with real funds is not yet available.</p>
          </div>
          <button
            onClick={() => setShowComingSoon(false)}
            className="ml-2 text-amber-600 hover:text-amber-400 transition-colors"
          >
            <X size={14} />
          </button>
        </div>
      )}

      <style>{`
        @keyframes slideIn {
          from { opacity: 0; transform: translateY(-10px) scale(0.97); }
          to   { opacity: 1; transform: translateY(0)     scale(1); }
        }
      `}</style>

      <div className="mx-auto max-w-6xl grid grid-cols-1 lg:grid-cols-2 gap-0 items-start">
        <div className="space-y-0">
          <div className="bg-title-bg border border-slate-700/50 rounded-xl p-6">
            {/* Header */}
            <div className="flex items-center justify-between -mx-6 -mt-6 px-6 py-4 mb-4 rounded-t-xl title-fade border-b border-slate-700/50">
              <h2 className="text-gray-100 text-sm font-medium">Environment Configuration</h2>
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold border bg-yellow-500/10 text-yellow-400 border-yellow-500/20">
                <span className="h-1.5 w-1.5 rounded-full bg-yellow-400 animate-pulse" />
                Testnet / Demo
              </span>
            </div>

            <div className="grid grid-cols-2 gap-3">
              {/* Testnet — active / locked on */}
              <button
                type="button"
                className="flex flex-col items-start gap-2 rounded-lg border p-4 text-left cursor-default border-yellow-500/40 bg-yellow-500/5"
              >
                <div className="flex items-center gap-2">
                  <Server size={15} className="text-yellow-400" />
                  <span className="text-sm font-medium text-yellow-400">Testnet / Demo</span>
                  <CheckCircle2 size={12} className="text-yellow-400 ml-auto" />
                </div>
                <p className="text-xs text-slate-400 leading-relaxed">
                  Paper trading on Binance Futures Demo. No real funds at risk. Set your API keys below.
                </p>
              </button>

              {/* Mainnet — disabled, shows coming soon */}
              <button
                type="button"
                onClick={handleMainnetClick}
                className="relative flex flex-col items-start gap-2 rounded-lg border p-4 text-left border-slate-700/50 bg-[#0a0d13] hover:border-slate-600 transition-colors group"
              >
                {/* Coming soon badge */}
                <span className="absolute top-2 right-2 text-[9px] font-bold uppercase tracking-wider text-amber-400 bg-amber-400/10 border border-amber-400/20 rounded-full px-2 py-0.5">
                  Soon
                </span>
                <div className="flex items-center gap-2">
                  <Zap size={15} className="text-slate-400 group-hover:text-slate-400 transition-colors" />
                  <span className="text-sm font-medium text-slate-400 group-hover:text-slate-400 transition-colors">
                    Live / Mainnet
                  </span>
                </div>
                <p className="text-xs text-slate-600 leading-relaxed">
                  Real trades on Binance Futures Mainnet. Requires{' '}
                  <code className="text-slate-400">BINANCE_MAINNET_API_KEY</code>.
                </p>
              </button>
            </div>

            {/* ── Binance API Keys ─────────────────────────────────────── */}
            <div className="mt-5 border-t border-slate-700/50 pt-5">
              <div className="flex items-center gap-2 mb-3">
                <KeyRound size={13} className="text-slate-400" />
                <p className="text-gray-300 text-xs font-semibold">Binance API Keys (Testnet)</p>
                <span className="ml-auto text-[10px] text-slate-400">
                  {keysStatus?.hasApiKey && keysStatus?.hasApiSecret
                    ? '● Keys saved'
                    : '○ Not configured'}
                </span>
              </div>

              {/* API Key feedback is handled by toast notifications */}

              <form onSubmit={handleApiKeySubmit} className="space-y-3">
                <div>
                  <label className={labelCls}>API Key</label>
                  <input
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder={keysStatus?.hasApiKey ? '••••••••  (leave blank to keep current)' : 'Paste your testnet API key'}
                    className={inputCls}
                    autoComplete="off"
                  />
                </div>
                <div>
                  <label className={labelCls}>API Secret</label>
                  <input
                    type="password"
                    value={apiSecret}
                    onChange={(e) => setApiSecret(e.target.value)}
                    placeholder={keysStatus?.hasApiSecret ? '••••••••  (leave blank to keep current)' : 'Paste your testnet API secret'}
                    className={inputCls}
                    autoComplete="off"
                  />
                </div>
                <button
                  type="submit"
                  disabled={saveKeysMutation.isPending || (!apiKey && !apiSecret)}
                  className="bg-slate-700 hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
                >
                  {saveKeysMutation.isPending ? 'Saving…' : 'Save API Keys'}
                </button>
              </form>
              <p className="mt-3 text-[11px] text-slate-600">
                Keys are encrypted (AES-256-GCM) before storage. They are never logged or sent to third parties.
              </p>
            </div>
          </div>

          {/* ── Chaos Setting (testnet) ─────────────────────────────────────────── */}
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
                  <label className={labelCls}>Max Strategies per Run (1–20)</label>
                  {settingsLoading
                    ? <div className={skeletonCls} />
                    : <input type="number" min="1" max="20" value={chaosMaxStrategies}
                        onChange={(e) => setChaosMaxStrategies(e.target.value)} className={inputCls} required />}
                  <p className="text-slate-400 text-[10px] mt-1">Hard cap; 0 selected → auto-pick up to this many</p>
                </div>
                <div>
                  <label className={labelCls}>Max Manual Symbols per Strategy (0–20)</label>
                  {settingsLoading
                    ? <div className={skeletonCls} />
                    : <input type="number" min="0" max="20" value={chaosMaxManualSymbols}
                        onChange={(e) => setChaosMaxManualSymbols(e.target.value)} className={inputCls} required />}
                  <p className="text-slate-400 text-[10px] mt-1">0 = all auto; the rest are distributed from the pool</p>
                </div>
              </div>

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
                <button
                  type="submit"
                  disabled={updateMutation.isPending || settingsLoading}
                  className="bg-purple-700 hover:bg-purple-800 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
                >
                  {updateMutation.isPending ? 'Saving…' : 'Save Chaos Settings'}
                </button>
              </div>
            </form>
          </div>
        </div>

        {/* ── Exchange Settings ─────────────────────────────────────────────── */}
        <div className="bg-title-bg border border-slate-700/50 rounded-xl p-6">
          <div className="flex items-center justify-between -mx-6 -mt-6 px-6 py-4 mb-4 rounded-t-xl title-fade border-b border-slate-700/50">
            <h2 className="text-gray-100 text-sm font-medium">Exchange Settings</h2>
          </div>

          {/* Exchange settings feedback is handled by toast notifications */}

          <form onSubmit={handleExchangeSubmit} noValidate>

            {/* ── Trading Fees ────────────────────────────────────────────── */}
            <p className="text-gray-300 text-xs font-semibold mb-3">Trading Fees</p>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>Taker Fee %</label>
                {settingsLoading
                  ? <div className={skeletonCls} />
                  : <input type="number" step="0.001" min="0" max="1" value={takerFee}
                      onChange={(e) => setTakerFee(e.target.value)} className={inputCls} required />}
                <p className="text-slate-400 text-[10px] mt-1">e.g. 0.05 = 0.05%</p>
              </div>
              <div>
                <label className={labelCls}>Maker Fee %</label>
                {settingsLoading
                  ? <div className={skeletonCls} />
                  : <input type="number" step="0.001" min="0" max="1" value={makerFee}
                      onChange={(e) => setMakerFee(e.target.value)} className={inputCls} required />}
                <p className="text-slate-400 text-[10px] mt-1">e.g. 0.02 = 0.02%</p>
              </div>
            </div>

            {/* ── Backtest Defaults ────────────────────────────────────────── */}
            <div className="border-t border-slate-700/50 pt-5 mt-5">
              <p className="text-gray-300 text-xs font-semibold mb-3">Backtest Defaults</p>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={labelCls}>Starting Capital ($)</label>
                  {settingsLoading
                    ? <div className={skeletonCls} />
                    : <input type="number" min="1" value={defaultCapital}
                        onChange={(e) => setDefaultCapital(e.target.value)} className={inputCls} required />}
                </div>
                <div>
                  <label className={labelCls}>Leverage (1–125)</label>
                  {settingsLoading
                    ? <div className={skeletonCls} />
                    : <input type="number" min="1" max="125" value={defaultLeverage}
                        onChange={(e) => setDefaultLeverage(e.target.value)} className={inputCls} required />}
                </div>
              </div>
            </div>

            {/* ── Bot Defaults ─────────────────────────────────────────────── */}
            <div className="border-t border-slate-700/50 pt-5 mt-5">
              <p className="text-gray-300 text-xs font-semibold mb-3">Bot Defaults</p>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={labelCls}>Bot Capital ($)</label>
                  {settingsLoading
                    ? <div className={skeletonCls} />
                    : <input type="number" min="1" value={defaultBotCapital}
                        onChange={(e) => setDefaultBotCapital(e.target.value)} className={inputCls} required />}
                </div>
                <div>
                  <label className={labelCls}>Bot Leverage (1–125)</label>
                  {settingsLoading
                    ? <div className={skeletonCls} />
                    : <input type="number" min="1" max="125" value={defaultBotLeverage}
                        onChange={(e) => setDefaultBotLeverage(e.target.value)} className={inputCls} required />}
                </div>
              </div>
            </div>

            {/* ── Risk Management Defaults ─────────────────────────────────── */}
            <div className="border-t border-slate-700/50 pt-5 mt-5">
              <p className="text-gray-300 text-xs font-semibold mb-3">Risk Management Defaults</p>
              {settingsLoading
                ? <div className="grid grid-cols-2 gap-3">{[0, 1, 2, 3].map((i) => <div key={i} className={skeletonCls} />)}</div>
                : <RiskParamsFields values={risk} onChange={setRisk} inputClassName={inputCls} labelClassName={labelCls} />}
              <p className="text-slate-400 text-[10px] mt-2">
                Pre-fills the backtest form and bot wizard. Each run can override these.
              </p>
            </div>

            {/* ── Simulation Realism ───────────────────────────────────────── */}
            <div className="border-t border-slate-700/50 pt-5 mt-5">
              <p className="text-gray-300 text-xs font-semibold mb-3">Simulation Realism</p>
              <div className="space-y-4">
                <div>
                  <label className={labelCls}>Slippage %</label>
                  {settingsLoading
                    ? <div className={skeletonCls} />
                    : <input type="number" step="0.001" min="0" max="5" value={slippagePct}
                        onChange={(e) => setSlippagePct(e.target.value)} className={inputCls} required />}
                  <p className="text-slate-400 text-[10px] mt-1">Adverse slippage applied to every market fill</p>
                </div>

                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    role="switch"
                    aria-checked={fundingEnabled}
                    onClick={() => setFundingEnabled((v) => !v)}
                    className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none ${
                      fundingEnabled ? 'bg-emerald-600' : 'bg-slate-700'
                    }`}
                  >
                    <span
                      className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform ${
                        fundingEnabled ? 'translate-x-4' : 'translate-x-0'
                      }`}
                    />
                  </button>
                  <span className={labelCls}>Funding Enabled</span>
                  <span className="text-slate-400 text-[10px]">Charge funding every 8h during simulation</span>
                </div>

                {fundingEnabled && (
                  <div>
                    <label className={labelCls}>Funding Rate %</label>
                    {settingsLoading
                      ? <div className={skeletonCls} />
                      : <input type="number" step="0.001" min="0" max="1" value={fundingRate}
                          onChange={(e) => setFundingRate(e.target.value)} className={inputCls} required />}
                    <p className="text-slate-400 text-[10px] mt-1">Per-8h rate, e.g. 0.01 = 0.01%</p>
                  </div>
                )}
              </div>
            </div>

            <div className="mt-6">
              <button
                type="submit"
                disabled={updateMutation.isPending || settingsLoading}
                className="bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
              >
                {updateMutation.isPending ? 'Saving…' : 'Save Exchange Settings'}
              </button>
            </div>
          </form>
        </div>
      </div>

    </PageWrapper>
  )
}
