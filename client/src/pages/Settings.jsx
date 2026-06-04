import { useState } from 'react'
import { Server, Zap, CheckCircle2, Clock, X } from 'lucide-react'
import PageWrapper from '@/components/layout/PageWrapper'
import PageHeader from '@/components/ui/PageHeader'

export default function Settings() {
  const [showComingSoon, setShowComingSoon] = useState(false)

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
    </PageWrapper>
  )
}
