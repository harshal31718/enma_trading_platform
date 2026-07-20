// Plan 7 Step 7.4 (CLI-1): extracted out of ChaosWizard.jsx.
import { AlertTriangle } from 'lucide-react'

export default function Step4Review({ timeframe, capital, leverage, risk, activeStrategies, preview, strategyToggles }) {
  return (
    <div>
      <h3 className="text-sm font-semibold text-gray-300 mb-4">Review Chaos Run</h3>

      <div className="space-y-3 text-sm">
        <div className="flex justify-between py-2 border-b border-slate-800">
          <span className="text-slate-450">Active Timeframe</span>
          <span className="text-gray-100 font-medium">{timeframe}</span>
        </div>
        <div className="flex justify-between py-2 border-b border-slate-800">
          <span className="text-slate-450">Capital per Strategy</span>
          <span className="text-gray-100 font-medium">${parseFloat(capital).toLocaleString()}</span>
        </div>
        <div className="flex justify-between py-2 border-b border-slate-800">
          <span className="text-slate-450">Leverage</span>
          <span className="text-gray-100 font-medium">{leverage}x</span>
        </div>
        <div className="flex justify-between py-2 border-b border-slate-800">
          <span className="text-slate-450">Risk Constraints</span>
          <span className="text-gray-100 font-medium">
            {risk.riskPct}% / trade · {risk.riskReward}:1 R:R · {risk.maxDrawdown}% max DD · {risk.minEdgeMult} edge mult
          </span>
        </div>
        <div className="flex justify-between py-2 border-b border-slate-800">
          <span className="text-slate-450">Target Environment</span>
          <span className="text-yellow-400 font-semibold flex items-center gap-1">
            Binance Testnet (Paper)
          </span>
        </div>

        <div className="py-3 border-b border-slate-800">
          <span className="text-slate-450 block mb-2">Strategy Deployments ({activeStrategies.length})</span>
          <div className="space-y-2">
            {activeStrategies.map(name => {
              const s = preview.stats[name] || { total: 0 }
              const isManual = strategyToggles[name] === 'manual'
              return (
                <div key={name} className="flex justify-between items-center text-xs bg-slate-950/50 px-3 py-2 rounded border border-slate-900">
                  <span className="text-slate-300 font-medium">{name}</span>
                  <span className="text-slate-400">
                    {isManual ? 'manual picks' : 'auto'} · <strong className="text-purple-400 font-semibold">{s.total}</strong> symbols
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* Testnet alert warning */}
      <div className="mt-5 flex items-start gap-3 bg-amber-950/20 border border-amber-800/40 rounded-lg p-4">
        <AlertTriangle size={18} className="text-amber-400 shrink-0 mt-0.5" />
        <div>
          <p className="text-amber-350 text-xs font-semibold">Stress Test Invariant</p>
          <p className="text-slate-400 text-[11px] mt-1 leading-relaxed">
            Chaos Mode launches multiple concurrent trading loops. Selected symbols will be locked in Redis, blocking manual entry on those markets until stopped. Ensure your Binance Testnet balance has sufficient funds to afford the initial margin.
          </p>
        </div>
      </div>
    </div>
  )
}
