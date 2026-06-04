export default function SymbolPicker({ symbols, selected, lockedSymbols, onChange }) {
  const toggle = (sym) => {
    if (lockedSymbols?.[sym]) return
    if (selected.includes(sym)) {
      onChange(selected.filter((s) => s !== sym))
    } else {
      onChange([...selected, sym])
    }
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2 max-h-64 overflow-y-auto pr-1">
      {symbols.map((sym) => {
        const lock = lockedSymbols?.[sym]
        const isLocked = !!lock
        const isSelected = selected.includes(sym)

        return (
          <button
            key={sym}
            onClick={() => toggle(sym)}
            disabled={isLocked}
            title={isLocked ? `Locked: ${lock.reason}` : undefined}
            className={[
              'px-3 py-2 text-xs rounded border transition-colors text-left',
              isLocked
                ? 'bg-gray-800/40 border-gray-700/40 text-gray-600 cursor-not-allowed'
                : isSelected
                ? 'bg-emerald-500/10 border-emerald-500 text-emerald-400'
                : 'bg-gray-800 border-gray-700 text-gray-300 hover:border-gray-500',
            ].join(' ')}
          >
            <span className="font-medium">{sym}</span>
            {isLocked && <span className="ml-1 text-gray-600">(locked)</span>}
          </button>
        )
      })}
    </div>
  )
}
