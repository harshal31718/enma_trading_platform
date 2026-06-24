import React from 'react'

export default function AggregateMarginGauge({
  marginUsed = '0.00',
  walletBalance = '0.00',
  netLeverage = '0.00'
}) {
  const used = parseFloat(marginUsed) || 0.0
  const total = parseFloat(walletBalance) || 1.0
  const ratio = Math.min(100, Math.max(0, (used / total) * 100))
  const lev = parseFloat(netLeverage) || 0.0

  // Style color depending on warning threshold (30% margin used)
  const isHighRisk = ratio > 30.0
  const strokeColor = isHighRisk ? '#f87171' : '#34d399' // red-400 or emerald-400
  const textColor = isHighRisk ? 'text-red-400' : 'text-emerald-400'

  // Circumference for 120 size circle, radius 45 -> 2 * PI * 45 = 282.7
  const r = 45
  const circ = 2 * Math.PI * r
  const strokeDashoffset = circ - (ratio / 100) * circ

  return (
    <div className="bg-slate-950 border border-slate-800 p-5 shadow-2xl flex flex-col justify-between h-full">
      <div>
        <h3 className="text-[11px] font-semibold text-gray-300 uppercase tracking-wider mb-2">
          Margin Ratio & Leverage
        </h3>
        <p className="text-xs text-slate-500 mb-4">Locked Margin vs Free Wallet Balance</p>
      </div>

      <div className="flex items-center justify-around gap-4 my-2">
        {/* SVG Radial Progress */}
        <div className="relative w-28 h-28 flex items-center justify-center shrink-0">
          <svg className="w-full h-full transform -rotate-90">
            <circle
              cx="56"
              cy="56"
              r={r}
              className="stroke-slate-800"
              strokeWidth="10"
              fill="transparent"
            />
            <circle
              cx="56"
              cy="56"
              r={r}
              stroke={strokeColor}
              strokeWidth="10"
              fill="transparent"
              strokeDasharray={circ}
              strokeDashoffset={strokeDashoffset}
              className="transition-all duration-500 ease-out"
            />
          </svg>
          <div className="absolute flex flex-col items-center justify-center">
            <span className={`text-base font-mono font-bold ${textColor}`}>
              {ratio.toFixed(1)}%
            </span>
            <span className="text-[9px] uppercase tracking-wider text-slate-500">Margin</span>
          </div>
        </div>

        {/* Detailed Stats */}
        <div className="flex flex-col gap-2 font-mono">
          <div>
            <span className="text-[9px] block uppercase text-slate-500 tracking-wider">Locked Margin</span>
            <span className="text-sm font-semibold text-slate-200">${used.toFixed(2)}</span>
          </div>
          <div>
            <span className="text-[9px] block uppercase text-slate-500 tracking-wider">Wallet Balance</span>
            <span className="text-sm font-semibold text-slate-200">${total.toFixed(2)}</span>
          </div>
          <div>
            <span className="text-[9px] block uppercase text-slate-500 tracking-wider">Net Leverage</span>
            <span className={`text-sm font-semibold ${textColor}`}>{lev.toFixed(2)}x</span>
          </div>
        </div>
      </div>

      <div className="border-t border-slate-800/60 pt-3 flex items-center justify-between text-[10px] text-slate-400">
        <span>Status</span>
        {isHighRisk ? (
          <span className="text-red-400 font-semibold uppercase tracking-wider animate-pulse">
            ⚠️ HIGH EXPOSURE
          </span>
        ) : (
          <span className="text-emerald-400 font-semibold uppercase tracking-wider">
            ✓ SAFE EXPOSURE
          </span>
        )}
      </div>
    </div>
  )
}
