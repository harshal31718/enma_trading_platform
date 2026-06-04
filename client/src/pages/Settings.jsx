import { useState, useEffect } from 'react'
import { AlertTriangle, Eye, EyeOff, Loader2 } from 'lucide-react'
import PageWrapper from '@/components/layout/PageWrapper'
import PageHeader from '@/components/ui/PageHeader'
import api from '@/lib/axios'
import { useTradeSettings, useSaveTradeSettings } from '@/hooks/useTrade'

const API_KEY_PATTERN = /^[a-zA-Z0-9-]+$/
const API_KEY_MIN_LEN = 16
const SECRET_MIN_LEN = 32

function validateApiKey(value) {
  if (!value) return 'API key is required'
  if (!API_KEY_PATTERN.test(value)) return 'Only alphanumeric characters and hyphens allowed'
  if (value.length < API_KEY_MIN_LEN) return `Must be at least ${API_KEY_MIN_LEN} characters`
  return null
}

function validateSecret(value) {
  if (!value) return 'Secret key is required'
  if (value.length < SECRET_MIN_LEN) return `Must be at least ${SECRET_MIN_LEN} characters`
  return null
}

export default function Settings() {
  const { data, isLoading } = useTradeSettings()
  const mutation = useSaveTradeSettings()

  const [apiKey, setApiKey] = useState('')
  const [apiSecret, setApiSecret] = useState('')
  const [paperTrading, setPaperTrading] = useState(true)
  const [showSecret, setShowSecret] = useState(false)
  const [errorMessage, setErrorMessage] = useState(null)
  const [verifyBanner, setVerifyBanner] = useState(null) // { ok: bool, message: str }
  const [saved, setSaved] = useState(false)
  const [isVerifying, setIsVerifying] = useState(false)

  // Per-field validation errors — only shown after the user has touched the field
  const [apiKeyTouched, setApiKeyTouched] = useState(false)
  const [secretTouched, setSecretTouched] = useState(false)

  useEffect(() => {
    if (data) {
      setApiKey(data.binanceApiKey ?? '')
      setPaperTrading(data.paperTrading ?? true)
    }
  }, [data])

  // Keys are considered "new" if they don't contain the masked placeholder (*) character
  const isNewApiKey = apiKey && !apiKey.includes('*')
  const isNewSecret = !!apiSecret

  // Validate only when new values are being submitted
  const apiKeyError = isNewApiKey ? validateApiKey(apiKey) : null
  const secretError = isNewSecret ? validateSecret(apiSecret) : null

  // The submit button is disabled when:
  // — there is a pending request, or
  // — the user is entering a new API key but it fails validation, or
  // — the user is entering a new secret but it fails validation
  const submitDisabled =
    mutation.isPending ||
    isVerifying ||
    isLoading ||
    (isNewApiKey && !!apiKeyError) ||
    (isNewSecret && !!secretError)

  async function handleSubmit(e) {
    e.preventDefault()
    setErrorMessage(null)
    setSaved(false)
    setVerifyBanner(null)

    // Touch both fields so errors show on submit attempt
    if (isNewApiKey) setApiKeyTouched(true)
    if (isNewSecret) setSecretTouched(true)

    // Block if front-end validation fails
    if ((isNewApiKey && apiKeyError) || (isNewSecret && secretError)) return

    const body = { paperTrading }
    if (isNewApiKey) body.binanceApiKey = apiKey
    if (isNewSecret) body.binanceApiSecret = apiSecret

    try {
      await mutation.mutateAsync(body)
      setSaved(true)
      setApiSecret('')
      setSecretTouched(false)

      // After a successful save, call the verify endpoint
      setIsVerifying(true)
      try {
        await api.post('/api/v1/trade/settings/verify')
        setVerifyBanner({ ok: true, message: 'Keys verified successfully against Binance Testnet.' })
      } catch (verifyErr) {
        const msg =
          verifyErr.response?.data?.error?.message ||
          verifyErr.response?.data?.message ||
          'Keys saved but verification failed — check your credentials.'
        setVerifyBanner({ ok: false, message: msg })
      } finally {
        setIsVerifying(false)
      }
    } catch (err) {
      const msg =
        err.response?.data?.error?.message ||
        err.response?.data?.message ||
        'Failed to save settings'
      setErrorMessage(msg)
    }
  }

  const isBusy = mutation.isPending || isVerifying

  return (
    <PageWrapper>
      <PageHeader
        title="Settings"
        description="Configure exchange API keys and account preferences"
      />

      <div className="max-w-lg">
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-6">
          <div className="flex items-center justify-between mb-1">
            <h2 className="text-gray-100 text-sm font-medium">Binance Testnet API Keys</h2>
            {data?.binanceApiKey ? (
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                Active
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-gray-800 text-gray-500 border border-gray-700/50">
                <span className="h-1.5 w-1.5 rounded-full bg-gray-600" />
                Not Configured
              </span>
            )}
          </div>
          <p className="text-gray-500 text-xs mb-5">
            Keys are verified against Binance Futures Testnet before saving.
          </p>

          {errorMessage && (
            <div className="flex items-start gap-3 bg-red-950/20 border border-red-800/40 rounded-lg p-4 mb-5">
              <AlertTriangle size={16} className="text-red-400 mt-0.5 shrink-0" />
              <p className="text-red-400 text-sm">{errorMessage}</p>
            </div>
          )}

          {saved && !verifyBanner && (
            <div className="bg-emerald-950/20 border border-emerald-800/40 rounded-lg p-4 mb-5">
              <p className="text-emerald-400 text-sm">Settings saved.</p>
            </div>
          )}

          {verifyBanner && (
            <div
              className={[
                'rounded-lg p-4 mb-5',
                verifyBanner.ok
                  ? 'bg-emerald-950/20 border border-emerald-800/40'
                  : 'bg-red-900/20 border border-red-800/40',
              ].join(' ')}
            >
              <p className={verifyBanner.ok ? 'text-emerald-400 text-sm' : 'text-red-400 text-sm'}>
                {verifyBanner.message}
              </p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-gray-400 text-xs">Binance Testnet API Key</label>
              <input
                type="password"
                value={apiKey}
                onChange={(e) => {
                  setApiKey(e.target.value)
                  setApiKeyTouched(true)
                  setErrorMessage(null)
                  setSaved(false)
                  setVerifyBanner(null)
                }}
                placeholder={isLoading ? 'Loading…' : 'Paste your testnet API key'}
                disabled={isLoading}
                className="bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-emerald-600 disabled:opacity-50"
              />
              {apiKeyTouched && isNewApiKey && apiKeyError && (
                <p className="text-red-400 text-xs mt-1">{apiKeyError}</p>
              )}
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-gray-400 text-xs">Binance Testnet Secret Key</label>
              <div className="relative">
                <input
                  type={showSecret ? 'text' : 'password'}
                  value={apiSecret}
                  onChange={(e) => {
                    setApiSecret(e.target.value)
                    setSecretTouched(true)
                    setErrorMessage(null)
                    setSaved(false)
                    setVerifyBanner(null)
                  }}
                  placeholder={data?.binanceApiKey ? '••••••••••••••••••••••••' : 'Paste your testnet secret key'}
                  disabled={isLoading}
                  className="w-full bg-gray-800 border border-gray-700 rounded-md px-3 py-2 pr-10 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-emerald-600 disabled:opacity-50"
                />
                <button
                  type="button"
                  onClick={() => setShowSecret((v) => !v)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
                  tabIndex={-1}
                >
                  {showSecret ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
              </div>
              {secretTouched && isNewSecret && secretError && (
                <p className="text-red-400 text-xs mt-1">{secretError}</p>
              )}
            </div>

            <div className="flex items-center justify-between py-1">
              <div>
                <p className="text-gray-300 text-sm">Paper Trading Mode</p>
                <p className="text-gray-600 text-xs mt-0.5">
                  When enabled, orders are simulated and not sent to the exchange.
                </p>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={paperTrading}
                onClick={() => setPaperTrading((v) => !v)}
                className={[
                  'relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors',
                  paperTrading ? 'bg-emerald-600' : 'bg-gray-700',
                ].join(' ')}
              >
                <span
                  className={[
                    'pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow transform transition-transform',
                    paperTrading ? 'translate-x-5' : 'translate-x-0',
                  ].join(' ')}
                />
              </button>
            </div>

            <button
              type="submit"
              disabled={submitDisabled}
              className="mt-2 flex items-center justify-center gap-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-md px-4 py-2 transition-colors"
            >
              {isBusy && <Loader2 size={14} className="animate-spin" />}
              {mutation.isPending ? 'Saving…' : isVerifying ? 'Verifying…' : 'Save & Verify'}
            </button>
          </form>
        </div>
      </div>
    </PageWrapper>
  )
}
