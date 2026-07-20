// Plan 7 Step 7.4 (CLI-1): extracted out of Settings.jsx. Kept as one card
// (matches the original single visual card boundary exactly — env toggle +
// testnet keys + mainnet keys + bot session limits were always one
// `bg-title-bg` box) rather than split further, to avoid changing layout.
import { useState, useEffect } from 'react'
import { Server, Zap, CheckCircle2, AlertTriangle, KeyRound } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import api from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { useExchangeSettings, useUpdateExchangeSettings } from '@/hooks/useExchangeSettings'
import { inputCls, labelCls, skeletonCls } from './styles'

export default function EnvironmentConfigCard() {
  const queryClient = useQueryClient()

  // ── API Keys form state ───────────────────────────────────────────────────
  const [apiKey, setApiKey] = useState('')
  const [apiSecret, setApiSecret] = useState('')
  const [mainnetApiKey, setMainnetApiKey] = useState('')
  const [mainnetApiSecret, setMainnetApiSecret] = useState('')

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
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['trade', 'settings-keys'] })
      if (data?.env === 'mainnet') {
        setMainnetApiKey('')
        setMainnetApiSecret('')
        toast.success('Mainnet keys verified and saved')
      } else {
        setApiKey('')
        setApiSecret('')
        toast.success('Testnet API keys saved successfully')
      }
    },
    onError: (err) => {
      toast.error(err.response?.data?.error?.message || err.message || 'Failed to save API keys')
    }
  })

  function handleApiKeySubmit(e) {
    e.preventDefault()
    if (!apiKey && !apiSecret) return
    const payload = { env: 'testnet' }
    if (apiKey) payload.apiKey = apiKey
    if (apiSecret) payload.apiSecret = apiSecret
    saveKeysMutation.mutate(payload)
  }

  function handleMainnetKeySubmit(e) {
    e.preventDefault()
    if (!mainnetApiKey || !mainnetApiSecret) return
    saveKeysMutation.mutate({ env: 'mainnet', apiKey: mainnetApiKey, apiSecret: mainnetApiSecret })
  }

  // ── Bot Session Limits form state (Settings.limits.*) ─────────────────────
  const [maxSymbolsPerBotTestnet, setMaxSymbolsPerBotTestnet] = useState('15')
  const [maxConcurrentBotsTestnet, setMaxConcurrentBotsTestnet] = useState('10')
  const [maxSymbolsPerBotMainnet, setMaxSymbolsPerBotMainnet] = useState('15')
  const [maxConcurrentBotsMainnet, setMaxConcurrentBotsMainnet] = useState('10')

  const { data: exchangeSettings, isLoading: settingsLoading } = useExchangeSettings()
  const updateMutation = useUpdateExchangeSettings()

  useEffect(() => {
    if (exchangeSettings) {
      setMaxSymbolsPerBotTestnet(String(exchangeSettings.limits?.testnet?.maxSymbolsPerBot ?? 15))
      setMaxConcurrentBotsTestnet(String(exchangeSettings.limits?.testnet?.maxConcurrentBots ?? 10))
      setMaxSymbolsPerBotMainnet(String(exchangeSettings.limits?.mainnet?.maxSymbolsPerBot ?? 15))
      setMaxConcurrentBotsMainnet(String(exchangeSettings.limits?.mainnet?.maxConcurrentBots ?? 10))
    }
  }, [exchangeSettings])

  function handleLimitsSubmit(e) {
    e.preventDefault()
    updateMutation.mutate(
      {
        limits: {
          testnet: {
            maxSymbolsPerBot:  parseInt(maxSymbolsPerBotTestnet, 10),
            maxConcurrentBots: parseInt(maxConcurrentBotsTestnet, 10),
          },
          mainnet: {
            maxSymbolsPerBot:  parseInt(maxSymbolsPerBotMainnet, 10),
            maxConcurrentBots: parseInt(maxConcurrentBotsMainnet, 10),
          },
        },
      },
      {
        onSuccess: () => {
          toast.success('Bot session limits saved successfully')
        },
        onError: (err) => {
          toast.error(err.response?.data?.error?.message || err.message || 'Failed to save limits')
        }
      }
    )
  }

  const testnetSaved = keysStatus?.hasApiKey && keysStatus?.hasApiSecret
  const mainnetSaved = keysStatus?.hasMainnetApiKey && keysStatus?.hasMainnetApiSecret

  return (
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

        {/* Mainnet — read-only balance monitoring (not tradable) */}
        <div className="relative flex flex-col items-start gap-2 rounded-lg border p-4 text-left border-slate-700/50 bg-[#0a0d13]">
          <span className="absolute top-2 right-2 text-[9px] font-bold uppercase tracking-wider text-emerald-400 bg-emerald-400/10 border border-emerald-400/20 rounded-full px-2 py-0.5">
            Read-Only
          </span>
          <div className="flex items-center gap-2">
            <Zap size={15} className="text-slate-400" />
            <span className="text-sm font-medium text-slate-400">Live / Mainnet</span>
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            Balance monitoring only (read-only keys). Live trading remains disabled — all orders execute on testnet.
          </p>
        </div>
      </div>

      {/* ── Binance API Keys (Testnet — Trading) ──────────────────── */}
      <div className="mt-5 border-t border-slate-700/50 pt-5">
        <div className="flex items-center gap-2 mb-3">
          <KeyRound size={13} className="text-slate-400" />
          <p className="text-gray-300 text-xs font-semibold">Binance API Keys (Testnet — Trading)</p>
          <span className="ml-auto text-[10px] text-slate-400">
            {testnetSaved ? '● Keys saved' : '○ Not configured'}
          </span>
        </div>

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
          <Button
            type="submit"
            disabled={saveKeysMutation.isPending || (!apiKey && !apiSecret)}
            variant="secondary"
          >
            {saveKeysMutation.isPending ? 'Saving…' : 'Save Testnet Keys'}
          </Button>
        </form>
      </div>

      {/* ── Binance API Keys (Mainnet — Read-Only) ────────────────── */}
      <div className="mt-5 border-t border-slate-700/50 pt-5">
        <div className="flex items-center gap-2 mb-3">
          <KeyRound size={13} className="text-emerald-400" />
          <p className="text-gray-300 text-xs font-semibold">Binance API Keys (Mainnet — Read-Only)</p>
          <span className="ml-auto text-[10px] text-slate-400">
            {mainnetSaved ? '● Keys saved' : '○ Not configured'}
          </span>
        </div>

        <div className="mb-3 flex items-start gap-2 rounded-lg border border-amber-400/20 bg-amber-400/10 px-3 py-2.5">
          <AlertTriangle size={14} className="text-amber-400 mt-0.5 shrink-0" />
          <p className="text-[11px] text-amber-400 leading-relaxed">
            Create these keys on Binance with <span className="font-semibold">Read Only</span> permission — do not
            enable Futures trading. Enma uses them exclusively to display your mainnet balance; all trading happens
            on testnet. Keys are verified against Binance before being saved.
          </p>
        </div>

        <form onSubmit={handleMainnetKeySubmit} className="space-y-3">
          <div>
            <label className={labelCls}>API Key</label>
            <input
              type="password"
              value={mainnetApiKey}
              onChange={(e) => setMainnetApiKey(e.target.value)}
              placeholder={keysStatus?.hasMainnetApiKey ? '••••••••  (enter both to replace)' : 'Paste your mainnet read-only API key'}
              className={inputCls}
              autoComplete="off"
            />
          </div>
          <div>
            <label className={labelCls}>API Secret</label>
            <input
              type="password"
              value={mainnetApiSecret}
              onChange={(e) => setMainnetApiSecret(e.target.value)}
              placeholder={keysStatus?.hasMainnetApiSecret ? '••••••••  (enter both to replace)' : 'Paste your mainnet read-only API secret'}
              className={inputCls}
              autoComplete="off"
            />
          </div>
          <Button
            type="submit"
            disabled={saveKeysMutation.isPending || !mainnetApiKey || !mainnetApiSecret}
            variant="secondary"
          >
            {saveKeysMutation.isPending ? 'Verifying…' : 'Verify & Save Mainnet Keys'}
          </Button>
        </form>
        <p className="mt-3 text-[11px] text-slate-600">
          All keys are encrypted (AES-256-GCM) before storage. They are never logged or sent to third parties.
        </p>
      </div>

      {/* ── Bot Session Limits ─────────────────────────────────────── */}
      <div className="mt-5 border-t border-slate-700/50 pt-5">
        <p className="text-gray-300 text-xs font-semibold mb-3">Bot Session Limits</p>
        <form onSubmit={handleLimitsSubmit} className="grid grid-cols-2 gap-3">
          {/* Testnet — active */}
          <div className="rounded-lg border p-4 border-yellow-500/40 bg-yellow-500/5 space-y-3">
            <p className="text-xs font-medium text-yellow-400">Testnet</p>
            <div>
              <label className={labelCls}>Max Symbols per Bot (1–30)</label>
              {settingsLoading
                ? <div className={skeletonCls} />
                : <input type="number" min="1" max="30" value={maxSymbolsPerBotTestnet}
                    onChange={(e) => setMaxSymbolsPerBotTestnet(e.target.value)} className={inputCls} required />}
            </div>
            <div>
              <label className={labelCls}>Max Concurrent Bots (1–20)</label>
              {settingsLoading
                ? <div className={skeletonCls} />
                : <input type="number" min="1" max="20" value={maxConcurrentBotsTestnet}
                    onChange={(e) => setMaxConcurrentBotsTestnet(e.target.value)} className={inputCls} required />}
              <p className="text-slate-400 text-[10px] mt-1">Applies to both manual bots and Chaos Mode strategies</p>
            </div>
          </div>

          {/* Mainnet — future-proofing, no enforcement path exists yet */}
          <div className="relative rounded-lg border p-4 border-slate-700/50 bg-[#0a0d13] space-y-3">
            <span className="absolute top-2 right-2 text-[9px] font-bold uppercase tracking-wider text-slate-500 bg-slate-500/10 border border-slate-500/20 rounded-full px-2 py-0.5">
              Future
            </span>
            <p className="text-xs font-medium text-slate-400">Mainnet</p>
            <div>
              <label className={labelCls}>Max Symbols per Bot (1–30)</label>
              {settingsLoading
                ? <div className={skeletonCls} />
                : <input type="number" min="1" max="30" value={maxSymbolsPerBotMainnet}
                    onChange={(e) => setMaxSymbolsPerBotMainnet(e.target.value)} className={inputCls} required />}
            </div>
            <div>
              <label className={labelCls}>Max Concurrent Bots (1–20)</label>
              {settingsLoading
                ? <div className={skeletonCls} />
                : <input type="number" min="1" max="20" value={maxConcurrentBotsMainnet}
                    onChange={(e) => setMaxConcurrentBotsMainnet(e.target.value)} className={inputCls} required />}
              <p className="text-slate-400 text-[10px] mt-1">Inert until mainnet trading ships — all trading remains testnet-only</p>
            </div>
          </div>

          <div className="col-span-2">
            <Button
              type="submit"
              disabled={updateMutation.isPending || settingsLoading}
              variant="secondary"
            >
              {updateMutation.isPending ? 'Saving…' : 'Save Bot Session Limits'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
