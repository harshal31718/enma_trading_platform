// Plan 7 Step 7.4 (CLI-1): extracted out of ChaosWizard.jsx. Similar to
// SymbolPicker.jsx but customized for tiered lists & unique selection
// constraints (locked-by-session / claimed-by-other-strategy / manual cap).
import { Check } from 'lucide-react'

export default function ScopedSymbolPicker({ symbols = [], selected = [], lockedSymbols = {}, globalClaimedByOthers = new Set(), onToggle, maxManualSymbols }) {
  const isAtCap = selected.length >= maxManualSymbols

  return (
    <div>
      <div className="flex justify-between items-center mb-2">
        <span className="text-xs text-slate-400">
          Selected: <strong className="text-slate-200">{selected.length} / {maxManualSymbols}</strong> max
        </span>
        {isAtCap && (
          <span className="text-[10px] text-amber-400 bg-amber-500/10 px-1.5 py-0.5 rounded border border-amber-500/20">
            Cap reached
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2 max-h-60 overflow-y-auto p-2 bg-[#0a0d13] rounded border border-slate-800">
        {symbols.map(({ symbol, tier }) => {
          const isLockedBySession = !!lockedSymbols?.[symbol]
          const isClaimedByOtherStrategy = globalClaimedByOthers.has(symbol)
          const isSelected = selected.includes(symbol)

          // Disable conditions: locked by live session, claimed by other strategy, or at manual cap (if not currently selected)
          const isDisabled = isLockedBySession || isClaimedByOtherStrategy || (isAtCap && !isSelected)

          let title = `Tier: ${tier.toUpperCase()}`
          if (isLockedBySession) title = `Locked: ${lockedSymbols[symbol].reason}`
          else if (isClaimedByOtherStrategy) title = 'Claimed by another strategy'
          else if (isAtCap && !isSelected) title = `Max manual cap (${maxManualSymbols}) reached`

          const tierBadgeCls =
            tier === 'high' ? 'bg-purple-500/20 text-purple-400 border-purple-500/30' :
            tier === 'mid' ? 'bg-blue-500/20 text-blue-400 border-blue-500/30' :
            'bg-slate-700/30 text-slate-400 border-slate-700/40'

          return (
            <button
              key={symbol}
              type="button"
              onClick={() => onToggle(symbol)}
              disabled={isDisabled}
              title={title}
              className={[
                'relative px-3 py-2 text-xs rounded border transition-all text-left flex flex-col justify-between h-14',
                isDisabled
                  ? 'bg-slate-900/30 border-slate-900 text-slate-600 cursor-not-allowed opacity-50'
                  : isSelected
                  ? 'bg-purple-500/10 border-purple-500 text-purple-300 shadow-md shadow-purple-950/20'
                  : 'bg-slate-800/60 border-slate-700/50 text-gray-300 hover:border-slate-500 hover:bg-slate-800'
              ].join(' ')}
            >
              <span className="font-semibold">{symbol}</span>
              <div className="flex justify-between items-center w-full mt-1">
                <span className={`text-[9px] px-1 rounded border ${tierBadgeCls}`}>
                  {tier}
                </span>
                {isSelected && (
                  <Check size={10} className="text-purple-400" />
                )}
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
