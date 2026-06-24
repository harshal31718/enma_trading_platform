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
      <div className="bg-slate-950 border border-slate-800 p-5 shadow-2xl h-full flex flex-col justify-center items-center">
        <h3 className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-2">
          Rolling 30d Asset Correlation
        </h3>
        <p className="text-xs text-slate-500">No active positions to correlate</p>
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
        <div className="text-[10px] font-semibold text-slate-500 p-1 border border-slate-800/20"></div>
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
