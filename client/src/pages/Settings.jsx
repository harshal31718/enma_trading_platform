import { useState, useEffect, useRef } from 'react'
import { Server, Zap, CheckCircle2, Clock, X, AlertTriangle } from 'lucide-react'
import PageWrapper from '@/components/layout/PageWrapper'
import PageHeader from '@/components/ui/PageHeader'
import { useExchangeSettings, useUpdateExchangeSettings } from '../hooks/useExchangeSettings'

export default function Settings() {
  const [showComingSoon, setShowComingSoon] = useState(false)

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
  const [saveSuccess, setSaveSuccess] = useState(false)
  const successTimerRef = useRef(null)

  const { data: exchangeSettings, isLoading: settingsLoading } = useExchangeSettings()
  const updateMutation = useUpdateExchangeSettings()

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
    }
  }, [exchangeSettings])

  function handleExchangeSubmit(e) {
    e.preventDefault()
    setSaveSuccess(false)
    if (successTimerRef.current) clearTimeout(successTimerRef.current)
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
      },
      {
        onSuccess: () => {
          setSaveSuccess(true)
          successTimerRef.current = setTimeout(() => setSaveSuccess(false), 3000)
        },
      }
    )
  }

  const inputCls =
    'h-10 w-full rounded border border-gray-800 bg-gray-950 px-3 text-sm text-gray-100 focus:outline-none focus:border-emerald-500 transition-colors'
  const labelCls = 'text-gray-400 text-xs font-medium'
  const skeletonCls = 'h-10 w-full bg-gray-800 rounded animate-pulse'

  function handleMainnetClick() {
    setShowComingSoon(true)
    setTimeout(() => setShowComingSoon(false), 4000)
  }

  return (
    <PageWrapper>
      <PageHeader
        title="Settings"
        description="Configure the active trading environment"
      />

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

      <div className="max-w-lg">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
          {/* Header */}
          <div className="flex items-center justify-between mb-1">
            <h2 className="text-gray-100 text-sm font-medium">Environment Configuration</h2>
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold border bg-yellow-500/10 text-yellow-400 border-yellow-500/20">
              <span className="h-1.5 w-1.5 rounded-full bg-yellow-400 animate-pulse" />
              Testnet / Demo
            </span>
          </div>
          <p className="text-gray-500 text-xs mb-6">
            Select the active Binance environment. Credentials are configured in{' '}
            <code className="text-gray-400 bg-gray-800 px-1 rounded">server/.env</code>.
          </p>

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
              <p className="text-xs text-gray-500 leading-relaxed">
                Paper trading on Binance Futures Demo. No real funds at risk. Uses{' '}
                <code className="text-gray-400">BINANCE_TESTNET_API_KEY</code>.
              </p>
            </button>

            {/* Mainnet — disabled, shows coming soon */}
            <button
              type="button"
              onClick={handleMainnetClick}
              className="relative flex flex-col items-start gap-2 rounded-lg border p-4 text-left border-gray-700 bg-gray-800/30 hover:border-gray-600 transition-colors group"
            >
              {/* Coming soon badge */}
              <span className="absolute top-2 right-2 text-[9px] font-bold uppercase tracking-wider text-amber-400 bg-amber-400/10 border border-amber-400/20 rounded-full px-2 py-0.5">
                Soon
              </span>
              <div className="flex items-center gap-2">
                <Zap size={15} className="text-gray-500 group-hover:text-gray-400 transition-colors" />
                <span className="text-sm font-medium text-gray-500 group-hover:text-gray-400 transition-colors">
                  Live / Mainnet
                </span>
              </div>
              <p className="text-xs text-gray-600 leading-relaxed">
                Real trades on Binance Futures Mainnet. Requires{' '}
                <code className="text-gray-500">BINANCE_MAINNET_API_KEY</code>.
              </p>
            </button>
          </div>

          <p className="mt-5 text-[11px] text-gray-600">
            Binance API keys are read from <code className="text-gray-500">server/.env</code> and are never stored in the database.
          </p>
        </div>
      </div>

      {/* ── Exchange Settings ─────────────────────────────────────────────── */}
      <div className="max-w-lg mt-6">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
          <h2 className="text-gray-100 text-sm font-medium mb-1">Exchange Settings</h2>
          <p className="text-gray-500 text-xs mb-6">
            Trading fees, simulation parameters, and default form values. All values are stored as variables — no hardcoded numbers.
          </p>

          {updateMutation.isError && (
            <div className="flex items-start gap-2 bg-red-950/20 border border-red-800/40 rounded-lg p-3 mb-4">
              <AlertTriangle size={14} className="text-red-400 mt-0.5 shrink-0" />
              <p className="text-red-400 text-xs">
                {updateMutation.error?.response?.data?.message ?? updateMutation.error?.message ?? 'Failed to save settings.'}
              </p>
            </div>
          )}

          {saveSuccess && (
            <div className="bg-emerald-950/20 border border-emerald-800/40 rounded-lg p-3 mb-4">
              <p className="text-emerald-400 text-xs">Exchange settings saved.</p>
            </div>
          )}

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
                <p className="text-gray-600 text-[10px] mt-1">e.g. 0.05 = 0.05%</p>
              </div>
              <div>
                <label className={labelCls}>Maker Fee %</label>
                {settingsLoading
                  ? <div className={skeletonCls} />
                  : <input type="number" step="0.001" min="0" max="1" value={makerFee}
                      onChange={(e) => setMakerFee(e.target.value)} className={inputCls} required />}
                <p className="text-gray-600 text-[10px] mt-1">e.g. 0.02 = 0.02%</p>
              </div>
            </div>

            {/* ── Backtest Defaults ────────────────────────────────────────── */}
            <div className="border-t border-gray-800 pt-5 mt-5">
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
            <div className="border-t border-gray-800 pt-5 mt-5">
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

            {/* ── Simulation Realism ───────────────────────────────────────── */}
            <div className="border-t border-gray-800 pt-5 mt-5">
              <p className="text-gray-300 text-xs font-semibold mb-3">Simulation Realism</p>
              <div className="space-y-4">
                <div>
                  <label className={labelCls}>Slippage %</label>
                  {settingsLoading
                    ? <div className={skeletonCls} />
                    : <input type="number" step="0.001" min="0" max="5" value={slippagePct}
                        onChange={(e) => setSlippagePct(e.target.value)} className={inputCls} required />}
                  <p className="text-gray-600 text-[10px] mt-1">Adverse slippage applied to every market fill</p>
                </div>

                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    role="switch"
                    aria-checked={fundingEnabled}
                    onClick={() => setFundingEnabled((v) => !v)}
                    className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none ${
                      fundingEnabled ? 'bg-emerald-600' : 'bg-gray-700'
                    }`}
                  >
                    <span
                      className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform ${
                        fundingEnabled ? 'translate-x-4' : 'translate-x-0'
                      }`}
                    />
                  </button>
                  <span className={labelCls}>Funding Enabled</span>
                  <span className="text-gray-600 text-[10px]">Charge funding every 8h during simulation</span>
                </div>

                {fundingEnabled && (
                  <div>
                    <label className={labelCls}>Funding Rate %</label>
                    {settingsLoading
                      ? <div className={skeletonCls} />
                      : <input type="number" step="0.001" min="0" max="1" value={fundingRate}
                          onChange={(e) => setFundingRate(e.target.value)} className={inputCls} required />}
                    <p className="text-gray-600 text-[10px] mt-1">Per-8h rate, e.g. 0.01 = 0.01%</p>
                  </div>
                )}
              </div>
            </div>

            <div className="mt-6">
              <button
                type="submit"
                disabled={updateMutation.isPending || settingsLoading}
                className="bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium px-4 py-2 rounded transition-colors"
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
