// Plan 7 Step 7.4 (CLI-1): extracted out of Settings.jsx.
import { useState, useEffect } from 'react'
import { Bell } from 'lucide-react'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/button'
import { useExchangeSettings, useUpdateExchangeSettings, useTestWebhook } from '@/hooks/useExchangeSettings'
import { inputCls, labelCls, skeletonCls } from './styles'

const WEBHOOK_EVENT_OPTIONS = [
  { value: 'entry_fill', label: 'Entry filled' },
  { value: 'exit_fill', label: 'Exit filled' },
  { value: 'liquidation', label: 'Liquidation' },
  { value: 'session_start', label: 'Bot started' },
  { value: 'session_stop', label: 'Bot stopped' },
  { value: 'session_error', label: 'Bot error' },
]

export default function NotificationsCard() {
  // Webhook Notifications form state (Settings.webhook.*, Plan 14 / F3)
  const [webhookEnabled, setWebhookEnabled] = useState(false)
  const [webhookUrl, setWebhookUrl] = useState('')
  const [webhookFormat, setWebhookFormat] = useState('json')
  const [webhookEvents, setWebhookEvents] = useState(['exit_fill', 'liquidation', 'session_error'])
  const [webhookRetries, setWebhookRetries] = useState('2')
  const [webhookTimeoutMs, setWebhookTimeoutMs] = useState('5000')

  const { data: exchangeSettings, isLoading: settingsLoading } = useExchangeSettings()
  const updateMutation = useUpdateExchangeSettings()
  const testWebhookMutation = useTestWebhook()

  useEffect(() => {
    if (exchangeSettings) {
      setWebhookEnabled(exchangeSettings.webhook?.enabled ?? false)
      setWebhookUrl(exchangeSettings.webhook?.url ?? '')
      setWebhookFormat(exchangeSettings.webhook?.format ?? 'json')
      setWebhookEvents(exchangeSettings.webhook?.events ?? ['exit_fill', 'liquidation', 'session_error'])
      setWebhookRetries(String(exchangeSettings.webhook?.retries ?? 2))
      setWebhookTimeoutMs(String(exchangeSettings.webhook?.timeoutMs ?? 5000))
    }
  }, [exchangeSettings])

  function toggleWebhookEvent(value) {
    setWebhookEvents((prev) =>
      prev.includes(value) ? prev.filter((e) => e !== value) : [...prev, value]
    )
  }

  function handleWebhookSubmit(e) {
    e.preventDefault()
    updateMutation.mutate(
      {
        webhook: {
          enabled: webhookEnabled,
          url: webhookUrl,
          format: webhookFormat,
          events: webhookEvents,
          retries: parseInt(webhookRetries, 10),
          timeoutMs: parseInt(webhookTimeoutMs, 10),
        },
      },
      {
        onSuccess: () => toast.success('Notification settings saved'),
        onError: (err) => toast.error(err.response?.data?.error?.message || err.message || 'Failed to save notification settings'),
      }
    )
  }

  function handleSendTestWebhook() {
    if (!webhookUrl) {
      toast.error('Enter a webhook URL first')
      return
    }
    testWebhookMutation.mutate(
      { url: webhookUrl, format: webhookFormat, timeoutMs: parseInt(webhookTimeoutMs, 10) || 5000 },
      {
        onSuccess: () => toast.success('Test webhook delivered successfully'),
        onError: (err) => toast.error(err.response?.data?.error?.message || err.message || 'Test webhook delivery failed'),
      }
    )
  }

  return (
    <div className="bg-title-bg border border-slate-700/50 rounded-xl p-6 mt-6">
      <div className="flex items-center justify-between -mx-6 -mt-6 px-6 py-4 mb-4 rounded-t-xl title-fade border-b border-slate-700/50">
        <h2 className="text-gray-100 text-sm font-medium flex items-center gap-2">
          <Bell size={15} className="text-emerald-400" />
          Notifications
        </h2>
        <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold border ${
          webhookEnabled
            ? 'bg-emerald-400/10 text-emerald-400 border-emerald-500/20'
            : 'bg-slate-500/10 text-slate-400 border-slate-500/20'
        }`}>
          {webhookEnabled ? 'Enabled' : 'Disabled'}
        </span>
      </div>

      <p className="text-xs text-slate-400 mb-4">
        POST a JSON (or form) payload to a URL on trade lifecycle events — point it at
        Discord, Slack, or IFTTT. A slow or dead endpoint never blocks trading.
      </p>

      <form onSubmit={handleWebhookSubmit} noValidate className="space-y-4">
        <div className="flex items-center gap-3">
          <button
            type="button"
            role="switch"
            aria-checked={webhookEnabled}
            onClick={() => setWebhookEnabled((v) => !v)}
            className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none ${
              webhookEnabled ? 'bg-emerald-600' : 'bg-slate-700'
            }`}
          >
            <span
              className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform ${
                webhookEnabled ? 'translate-x-4' : 'translate-x-0'
              }`}
            />
          </button>
          <span className={labelCls}>Enable webhook notifications</span>
        </div>

        <div>
          <label className={labelCls}>Webhook URL</label>
          {settingsLoading
            ? <div className={skeletonCls} />
            : <input type="url" value={webhookUrl}
                onChange={(e) => setWebhookUrl(e.target.value)}
                placeholder="https://discord.com/api/webhooks/..."
                className={inputCls} />}
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className={labelCls}>Format</label>
            {settingsLoading
              ? <div className={skeletonCls} />
              : <select value={webhookFormat} onChange={(e) => setWebhookFormat(e.target.value)} className={inputCls}>
                  <option value="json">JSON</option>
                  <option value="form">Form-encoded</option>
                </select>}
          </div>
          <div>
            <label className={labelCls}>Retries (0–5)</label>
            {settingsLoading
              ? <div className={skeletonCls} />
              : <input type="number" min="0" max="5" value={webhookRetries}
                  onChange={(e) => setWebhookRetries(e.target.value)} className={inputCls} />}
          </div>
          <div>
            <label className={labelCls}>Timeout (ms)</label>
            {settingsLoading
              ? <div className={skeletonCls} />
              : <input type="number" min="1000" max="30000" step="500" value={webhookTimeoutMs}
                  onChange={(e) => setWebhookTimeoutMs(e.target.value)} className={inputCls} />}
          </div>
        </div>

        <div>
          <label className={labelCls}>Events</label>
          <div className="grid grid-cols-2 gap-2 mt-2">
            {WEBHOOK_EVENT_OPTIONS.map(({ value, label }) => (
              <label key={value} className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={webhookEvents.includes(value)}
                  onChange={() => toggleWebhookEvent(value)}
                  className="h-3.5 w-3.5 rounded border-slate-600 bg-[#0a0d13] text-emerald-500 focus:ring-emerald-500 focus:ring-offset-0"
                />
                {label}
              </label>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-3 pt-2">
          <Button
            type="submit"
            disabled={updateMutation.isPending || settingsLoading}
            className="bg-emerald-600 hover:bg-emerald-700"
          >
            {updateMutation.isPending ? 'Saving…' : 'Save Notification Settings'}
          </Button>
          <Button
            type="button"
            variant="secondary"
            onClick={handleSendTestWebhook}
            disabled={testWebhookMutation.isPending || !webhookUrl}
          >
            {testWebhookMutation.isPending ? 'Sending…' : 'Send Test'}
          </Button>
        </div>
      </form>
    </div>
  )
}
