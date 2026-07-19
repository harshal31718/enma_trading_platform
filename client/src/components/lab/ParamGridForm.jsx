import { useEffect, useState } from 'react'

// Plan 10 Phase 3c §4.3.7 — "param grid auto-rendered from the PARAMS schema
// (min/max/step prefilled from schema bounds)". Reuses the exact same schema
// shape `ParamsForm.jsx` already renders for a single-value backtest run
// ({label, default, min, max, type} per param, from useStrategyParams) — here
// each param gets a small RANGE spec instead of one value: int params get
// {min, max, step}; float params get {min, max, num} (the engine's
// `_expand_param_range` uses `num` — a point count via np.linspace — for
// float ranges, not a step size).
export default function ParamGridForm({ schema, value, onChange }) {
  const [enabled, setEnabled] = useState({})

  useEffect(() => {
    if (!schema) return
    // Default: every param included, seeded from its schema bounds.
    const next = {}
    const nextEnabled = {}
    for (const [key, meta] of Object.entries(schema)) {
      nextEnabled[key] = true
      if (meta.type === 'float') {
        next[key] = { type: 'float', min: meta.min, max: meta.max, num: 5 }
      } else {
        next[key] = { type: 'int', min: meta.min, max: meta.max, step: 1 }
      }
    }
    setEnabled(nextEnabled)
    onChange(next)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schema])

  if (!schema || Object.keys(schema).length === 0) {
    return (
      <p className="text-xs text-slate-500 font-mono italic">
        This strategy has no tunable PARAMS — nothing to optimize.
      </p>
    )
  }

  const updateField = (key, field, raw) => {
    const num = field === 'type' ? raw : parseFloat(raw)
    const current = value?.[key] || {}
    const updated = { ...current, [field]: field === 'type' ? raw : (isNaN(num) ? current[field] : num) }
    onChange({ ...value, [key]: updated })
  }

  const toggleParam = (key) => {
    const next = { ...enabled, [key]: !enabled[key] }
    setEnabled(next)
    if (!next[key]) {
      const { [key]: _drop, ...rest } = value
      onChange(rest)
    } else {
      const meta = schema[key]
      const spec = meta.type === 'float'
        ? { type: 'float', min: meta.min, max: meta.max, num: 5 }
        : { type: 'int', min: meta.min, max: meta.max, step: 1 }
      onChange({ ...value, [key]: spec })
    }
  }

  return (
    <div className="space-y-2">
      <label className="text-[9px] uppercase text-slate-400 font-semibold tracking-wider block">
        Parameter grid (min/max/{'{step or point count}'} per param)
      </label>
      {Object.entries(schema).map(([key, meta]) => {
        const spec = value?.[key]
        const isEnabled = enabled[key] !== false
        return (
          <div key={key} className="border border-slate-800 bg-slate-900/40 p-2">
            <label className="flex items-center gap-2 text-xs font-mono text-slate-300 mb-1.5">
              <input type="checkbox" checked={isEnabled} onChange={() => toggleParam(key)} className="accent-emerald-500" />
              {meta.label || key}
            </label>
            {isEnabled && spec && (
              <div className="grid grid-cols-3 gap-2 pl-5">
                <div>
                  <span className="text-[9px] text-slate-500 block">Min</span>
                  <input
                    type="number"
                    value={spec.min}
                    onChange={(e) => updateField(key, 'min', e.target.value)}
                    className="w-full bg-slate-900 border border-slate-700 px-1.5 py-1 text-[11px] font-mono text-slate-200 outline-none focus:border-emerald-500"
                  />
                </div>
                <div>
                  <span className="text-[9px] text-slate-500 block">Max</span>
                  <input
                    type="number"
                    value={spec.max}
                    onChange={(e) => updateField(key, 'max', e.target.value)}
                    className="w-full bg-slate-900 border border-slate-700 px-1.5 py-1 text-[11px] font-mono text-slate-200 outline-none focus:border-emerald-500"
                  />
                </div>
                <div>
                  <span className="text-[9px] text-slate-500 block">{meta.type === 'float' ? '# points' : 'Step'}</span>
                  <input
                    type="number"
                    value={meta.type === 'float' ? spec.num : spec.step}
                    onChange={(e) => updateField(key, meta.type === 'float' ? 'num' : 'step', e.target.value)}
                    className="w-full bg-slate-900 border border-slate-700 px-1.5 py-1 text-[11px] font-mono text-slate-200 outline-none focus:border-emerald-500"
                  />
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
