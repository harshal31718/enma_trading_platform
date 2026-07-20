// Plan 7 Step 7.4 (CLI-1): extracted out of Settings.jsx.
import { useState, useEffect } from 'react'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/button'
import { useExchangeSettings, useUpdateExchangeSettings } from '@/hooks/useExchangeSettings'
import RiskParamsFields, { RISK_DEFAULTS, riskDefaultsFromSettings, riskFieldsToPayload } from '@/components/RiskParamsFields'
import { inputCls, labelCls, skeletonCls } from './styles'

export default function ExchangeSettingsCard() {
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
      setRisk(riskDefaultsFromSettings(exchangeSettings))
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

  return (
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
          <Button
            type="submit"
            disabled={updateMutation.isPending || settingsLoading}
          >
            {updateMutation.isPending ? 'Saving…' : 'Save Exchange Settings'}
          </Button>
        </div>
      </form>
    </div>
  )
}
