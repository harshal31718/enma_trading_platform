// Plan 7 Step 7.4 (CLI-1): extracted out of ChaosWizard.jsx.
import { Settings as SettingsIcon } from 'lucide-react'
import RiskParamsFields from '@/components/RiskParamsFields'

const TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d']

export default function Step3Parameters({ timeframe, setTimeframe, capital, setCapital, leverage, setLeverage, risk, setRisk }) {
  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-gray-300 mb-3">Chaos Parameters</h3>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs text-slate-400 font-medium mb-1">Timeframe</label>
          <select
            value={timeframe}
            onChange={(e) => setTimeframe(e.target.value)}
            className="w-full h-10 rounded-lg border border-slate-700/50 bg-[#0a0d13] px-3 text-sm text-gray-100 focus:outline-none focus:border-purple-500 transition-colors"
          >
            {TIMEFRAMES.map((tf) => (
              <option key={tf} value={tf}>{tf}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs text-slate-400 font-medium mb-1">Capital per Strategy (USDT)</label>
          <input
            type="number"
            value={capital}
            min="1"
            step="100"
            onChange={(e) => setCapital(e.target.value)}
            className="w-full h-10 rounded-lg border border-slate-700/50 bg-[#0a0d13] px-3 text-sm text-gray-100 focus:outline-none focus:border-purple-500 transition-colors"
          />
        </div>
      </div>

      <div>
        <label className="block text-xs text-slate-400 font-medium mb-1">Leverage (1–125)</label>
        <input
          type="number"
          value={leverage}
          min="1"
          max="125"
          onChange={(e) => setLeverage(parseInt(e.target.value, 10) || 1)}
          className="w-full h-10 rounded-lg border border-slate-700/50 bg-[#0a0d13] px-3 text-sm text-gray-100 focus:outline-none focus:border-purple-500 transition-colors"
        />
        <p className="text-[10px] text-slate-400 mt-1">
          * Note: Server clamps leverage per-symbol based on Binance exchange caps.
        </p>
      </div>

      <div className="border-t border-slate-800 pt-4 mt-4">
        <p className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-1.5">
          <SettingsIcon size={14} className="text-purple-400" />
          Shared Risk Defaults
        </p>
        <RiskParamsFields
          values={risk}
          onChange={setRisk}
          inputClassName="w-full h-10 rounded-lg border border-slate-700/50 bg-[#0a0d13] px-3 text-sm text-gray-100 focus:outline-none focus:border-purple-500 transition-colors"
          labelClassName="block text-xs text-slate-400 font-medium mb-1"
        />
      </div>
    </div>
  )
}
