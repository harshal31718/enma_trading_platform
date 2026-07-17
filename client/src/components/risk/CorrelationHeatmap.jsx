import React from 'react'

export default function CorrelationHeatmap({ matrix = {} }) {
  const symbols = Object.keys(matrix)

  const getBgColor = (val) => {
    const num = parseFloat(val)
    if (isNaN(num)) return 'transparent'
    
    if (num > 0) {
      const opacity = Math.round(num * 90)
      return `hsla(142, 70%, 45%, ${opacity / 100})` // emerald-500 equivalent
    } else {
      const opacity = Math.round(Math.abs(num) * 90)
      return `hsla(350, 70%, 45%, ${opacity / 100})` // red-500 equivalent
    }
  }

  const getTextColor = (val) => {
    const num = parseFloat(val)
    if (isNaN(num)) return 'text-slate-300'
    return Math.abs(num) > 0.5 ? 'text-slate-950 font-bold' : 'text-slate-300'
  }

  if (symbols.length === 0) {
    return (
      <div className="bg-slate-950 border border-slate-800 p-5 shadow-2xl h-full flex flex-col justify-center items-center relative overflow-hidden min-h-[220px]">
        {/* Muted correlation matrix blueprint SVG background */}
        <div className="absolute inset-0 opacity-[0.03] flex items-center justify-center pointer-events-none scale-110 blur-[0.5px]">
          <svg width="100%" height="100%" viewBox="0 0 200 200" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="10" y="10" width="40" height="40" stroke="#34d399" strokeWidth="2" strokeDasharray="2 2" />
            <rect x="60" y="10" width="40" height="40" stroke="#34d399" strokeWidth="2" strokeDasharray="2 2" />
            <rect x="110" y="10" width="40" height="40" stroke="#34d399" strokeWidth="2" strokeDasharray="2 2" />
            <rect x="10" y="60" width="40" height="40" stroke="#34d399" strokeWidth="2" strokeDasharray="2 2" />
            <rect x="60" y="60" width="40" height="40" stroke="#34d399" strokeWidth="2" />
            <rect x="110" y="60" width="40" height="40" stroke="#34d399" strokeWidth="2" strokeDasharray="2 2" />
            <rect x="10" y="110" width="40" height="40" stroke="#34d399" strokeWidth="2" strokeDasharray="2 2" />
            <rect x="60" y="110" width="40" height="40" stroke="#34d399" strokeWidth="2" strokeDasharray="2 2" />
            <rect x="110" y="110" width="40" height="40" stroke="#34d399" strokeWidth="2" />
            <line x1="30" y1="30" x2="80" y2="80" stroke="#34d399" strokeWidth="2" strokeDasharray="3 3" />
            <line x1="80" y1="80" x2="130" y2="130" stroke="#34d399" strokeWidth="2" strokeDasharray="3 3" />
            <circle cx="30" cy="30" r="4" fill="#34d399" />
            <circle cx="80" cy="80" r="4" fill="#34d399" />
            <circle cx="130" cy="130" r="4" fill="#34d399" />
          </svg>
        </div>

        <h3 className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-2 z-10">
          Rolling 30d Asset Correlation
        </h3>
        <p className="text-xs text-slate-400 z-10">No active positions to correlate</p>
      </div>
    )
  }

  return (
    <div className="bg-slate-950 border border-slate-800 p-5 shadow-2xl">
      <h3 className="text-[11px] font-semibold text-gray-300 uppercase tracking-wider mb-4">
        Rolling 30d Asset Correlation
      </h3>
      <div
        className="grid gap-0"
        style={{ gridTemplateColumns: `repeat(${symbols.length + 1}, minmax(0, 1fr))` }}
      >
        {/* Top-left empty corner cell */}
        <div className="text-[10px] font-semibold text-slate-400 p-1 border border-slate-800/20"></div>
        {/* Column Headers */}
        {symbols.map((s) => (
          <div
            key={s}
            className="text-[10px] font-semibold text-slate-400 p-1 font-mono text-center truncate border border-slate-800/20"
            title={s}
          >
            {s.replace('USDT', '')}
          </div>
        ))}

        {/* Rows */}
        {symbols.map((rowSymbol) => (
          <React.Fragment key={rowSymbol}>
            {/* Row Header */}
            <div
              className="text-[10px] font-semibold text-slate-400 p-1 font-mono flex items-center border border-slate-800/20 truncate"
              title={rowSymbol}
            >
              {rowSymbol.replace('USDT', '')}
            </div>
            {/* Heatmap Cells */}
            {symbols.map((colSymbol) => {
              const valStr = matrix[rowSymbol]?.[colSymbol] ?? '0.00'
              const val = parseFloat(valStr)
              return (
                <div
                  key={colSymbol}
                  className={`aspect-square flex items-center justify-center text-[10px] font-mono m-0.5 border border-slate-800/10 ${getTextColor(valStr)}`}
                  style={{ backgroundColor: getBgColor(valStr) }}
                  title={`${rowSymbol} vs ${colSymbol}: ${val.toFixed(2)}`}
                >
                  {val.toFixed(1)}
                </div>
              )
            })}
          </React.Fragment>
        ))}
      </div>
    </div>
  )
}
