import React from 'react'

export default function NetExposureBar({ exposures = {} }) {
  let longNotional = 0.0
  let shortNotional = 0.0
  
  const items = Object.entries(exposures).map(([symbol, data]) => {
    const notional = parseFloat(data.notional) || 0.0
    const leverage = data.leverage || '1'
    const side = data.side || 'long'
    
    if (side === 'long') {
      longNotional += notional
    } else {
      shortNotional += notional
    }
    
    return { symbol, notional, side, leverage }
  })

  const total = longNotional + shortNotional
  const longPct = total > 0 ? (longNotional / total) * 100 : 0
  const shortPct = total > 0 ? (shortNotional / total) * 100 : 0

  return (
    <div className="bg-slate-950 border border-slate-800 p-5 shadow-2xl flex flex-col justify-between h-full min-h-[220px]">
      <div>
        <h3 className="text-[11px] font-semibold text-gray-300 uppercase tracking-wider mb-2">
          Portfolio Exposure & Directionality
        </h3>
        {total > 0 && (
          <p className="text-xs text-slate-500 mb-4">Total Aggregate Exposure: ${(total).toFixed(2)}</p>
        )}
      </div>

      {total === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center py-8">
          <p className="text-xs text-slate-500 italic">No active portfolio exposure</p>
        </div>
      ) : (
        <>
          <div className="my-2">
            {/* Exposure Stacked Bar */}
            <div className="h-6 w-full bg-slate-900 border border-slate-800 flex overflow-hidden">
              {longPct > 0 && (
                <div
                  className="bg-emerald-500 flex items-center justify-center text-[10px] text-slate-950 font-bold transition-all duration-500"
                  style={{ width: `${longPct}%` }}
                  title={`Long Exposure: $${longNotional.toFixed(2)} (${longPct.toFixed(1)}%)`}
                >
                  {longPct >= 15 && `LONG ${longPct.toFixed(0)}%`}
                </div>
              )}
              {shortPct > 0 && (
                <div
                  className="bg-red-500 flex items-center justify-center text-[10px] text-slate-950 font-bold transition-all duration-500"
                  style={{ width: `${shortPct}%` }}
                  title={`Short Exposure: $${shortNotional.toFixed(2)} (${shortPct.toFixed(1)}%)`}
                >
                  {shortPct >= 15 && `SHORT ${shortPct.toFixed(0)}%`}
                </div>
              )}
            </div>
            <div className="flex justify-between text-[9px] font-mono text-slate-500 mt-1">
              <span>Long: ${longNotional.toFixed(2)}</span>
              <span>Short: ${shortNotional.toFixed(2)}</span>
            </div>
          </div>

          {/* Asset Breakdown */}
          <div className="border-t border-slate-800/60 pt-3 max-h-24 overflow-y-auto pr-1">
            <div className="flex flex-col gap-1.5">
              {items.map((item) => (
                <div key={item.symbol} className="flex items-center justify-between text-xs font-mono">
                  <span className="text-slate-400 font-semibold">{item.symbol}</span>
                  <div className="flex items-center gap-2">
                    <span className={`text-[10px] uppercase font-bold ${item.side === 'long' ? 'text-emerald-400' : 'text-red-400'}`}>
                      {item.side} {item.leverage}x
                    </span>
                    <span className="text-slate-300 font-semibold">${item.notional.toFixed(2)}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
