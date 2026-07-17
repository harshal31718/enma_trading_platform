export default function ParamsForm({ params, values, onChange }) {
  if (!params || Object.keys(params).length === 0) return null

  return (
    <div className="space-y-4">
      {Object.entries(params).map(([key, meta]) => (
        <div key={key}>
          <label htmlFor={`param-input-${key}`} className="block text-sm text-gray-300 mb-1">{meta.label}</label>
          <input
            id={`param-input-${key}`}
            type="number"
            value={values[key] ?? meta.default}
            min={meta.min}
            max={meta.max}
            step={meta.type === 'float' ? 0.01 : 1}
            onChange={(e) => {
              const raw = e.target.value
              const val = meta.type === 'float' ? parseFloat(raw) : parseInt(raw, 10)
              if (!isNaN(val)) onChange({ ...values, [key]: val })
            }}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-emerald-500"
          />
          <div className="text-xs text-gray-500 mt-1">
            Range: {meta.min} – {meta.max}
          </div>
        </div>
      ))}
    </div>
  )
}
