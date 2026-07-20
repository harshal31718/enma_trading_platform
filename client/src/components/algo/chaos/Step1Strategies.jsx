// Plan 7 Step 7.4 (CLI-1): extracted out of ChaosWizard.jsx.
import { Check } from 'lucide-react'

export default function Step1Strategies({ strategies, selectedStrategyNames, maxStrategies, onToggle }) {
  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-sm font-semibold text-gray-300">Select Strategies</h3>
        <span className="text-xs text-slate-400">Cap: {maxStrategies}</span>
      </div>

      <div className="space-y-2">
        {strategies.map((s) => {
          const isSelected = selectedStrategyNames.includes(s.name)
          const isAtCap = selectedStrategyNames.length >= maxStrategies
          const isDisabled = isAtCap && !isSelected

          return (
            <button
              key={s.id}
              type="button"
              disabled={isDisabled}
              onClick={() => onToggle(s.name)}
              className={`w-full text-left p-4 rounded-lg border transition-all ${
                isSelected
                  ? 'bg-purple-500/10 border-purple-500 text-purple-300 shadow-md shadow-purple-950/20'
                  : isDisabled
                  ? 'bg-slate-950/30 border-slate-900 text-slate-600 cursor-not-allowed opacity-50'
                  : 'bg-slate-850 border-slate-800 text-slate-300 hover:border-slate-650 hover:bg-slate-800'
              }`}
            >
              <div className="flex justify-between items-center">
                <div className="font-semibold text-sm">{s.name}</div>
                <div className={`w-4 h-4 rounded border flex items-center justify-center transition-colors ${
                  isSelected ? 'bg-purple-500 border-purple-500 text-white' : 'border-slate-600 bg-slate-900'
                }`}>
                  {isSelected && <Check size={10} />}
                </div>
              </div>
              {s.description && (
                <div className="text-xs text-slate-400 mt-1 whitespace-normal break-words">{s.description}</div>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
