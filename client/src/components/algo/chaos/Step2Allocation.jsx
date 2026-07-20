// Plan 7 Step 7.4 (CLI-1): extracted out of ChaosWizard.jsx.
import ScopedSymbolPicker from '../ScopedSymbolPicker'

export default function Step2Allocation({
  activeStrategies, strategyToggles, manualPicks, preview, curatedSymbols,
  lockedSymbols, maxManualSymbols, onModeToggle, onSymbolToggle, getGlobalClaimedByOthers,
}) {
  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-gray-300 mb-4">Symbol Allocation</h3>

      <div className="space-y-4">
        {activeStrategies.map((stratName) => {
          const isManual = strategyToggles[stratName] === 'manual'
          const picks = manualPicks[stratName] || []
          const s = preview.stats[stratName] || { high: 0, mid: 0, low: 0, total: 0 }

          return (
            <div key={stratName} className="border border-slate-800 rounded-lg bg-slate-950/40 p-4">
              <div className="flex items-center gap-3 mb-3">
                {/* Strategy name — fixed width so stats column aligns across rows */}
                <span className="text-sm font-bold text-slate-200 w-44 shrink-0 truncate">{stratName}</span>

                {/* Inline allocation preview — left-aligned, consistent start position */}
                <div className="flex items-center gap-1.5 flex-1 min-w-0 justify-start">
                  <span className="text-[10px] bg-purple-500/10 text-purple-400 px-1.5 py-0.5 rounded border border-purple-500/20" title="High volume">
                    H: {s.high}
                  </span>
                  <span className="text-[10px] bg-blue-500/10 text-blue-400 px-1.5 py-0.5 rounded border border-blue-500/20" title="Mid volume">
                    M: {s.mid}
                  </span>
                  <span className="text-[10px] bg-slate-700/20 text-slate-400 px-1.5 py-0.5 rounded border border-slate-800" title="Low volume">
                    L: {s.low}
                  </span>
                  <span className="text-[10px] font-semibold text-slate-300 ml-1">
                    {s.total} symbols
                  </span>
                </div>

                {/* Auto / Manual toggle */}
                <div className="inline-flex rounded-lg bg-slate-900 p-0.5 border border-slate-800 shrink-0">
                  <button
                    type="button"
                    onClick={() => onModeToggle(stratName, 'auto')}
                    className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                      !isManual ? 'bg-purple-650 text-white shadow' : 'text-slate-400 hover:text-slate-250'
                    }`}
                  >
                    Auto
                  </button>
                  <button
                    type="button"
                    onClick={() => onModeToggle(stratName, 'manual')}
                    className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                      isManual ? 'bg-purple-650 text-white shadow' : 'text-slate-400 hover:text-slate-250'
                    }`}
                  >
                    Manual
                  </button>
                </div>
              </div>

              {isManual && (
                <div className="pt-2 border-t border-slate-800/50">
                  <ScopedSymbolPicker
                    symbols={curatedSymbols}
                    selected={picks}
                    lockedSymbols={lockedSymbols}
                    globalClaimedByOthers={getGlobalClaimedByOthers(stratName)}
                    onToggle={(sym) => onSymbolToggle(stratName, sym)}
                    maxManualSymbols={maxManualSymbols}
                  />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
