// Four risk-model inputs shared by the backtest config form and the bot wizard.
//
// The three percent fields (risk/trade, max session drawdown, liquidation
// buffer) are displayed and edited as percentages; reward:risk is a plain
// ratio. The parent holds the display strings as state; convert to the
// server payload (camelCase fractions) with riskFieldsToPayload() at submit.

const FIELDS = [
  { key: 'riskPct',     label: 'Risk % / Trade',   step: '0.1', hint: 'Equity risked per trade' },
  { key: 'riskReward',  label: 'Reward : Risk',    step: '0.1', hint: 'TP distance ÷ stop distance' },
  { key: 'maxDrawdown', label: 'Max Session DD %', step: '1',   hint: 'Halts new entries' },
  { key: 'liqBuffer',   label: 'Liq. Buffer %',    step: '0.1', hint: 'Stop-to-liquidation gap' },
]

// Sensible fallbacks (match BaseStrategy / Settings schema defaults).
export const RISK_DEFAULTS = { riskPct: '1', riskReward: '2', maxDrawdown: '20', liqBuffer: '0.5' }

// Trim trailing zeros from a percentage so 0.01→"1", 0.005→"0.5", 0.20→"20".
const toPct = (v, d) => String(((v ?? d) * 100).toPrecision(4).replace(/\.?0+$/, ''))

// Build display strings from saved global Risk settings (fractions → percents).
export function riskDefaultsFromSettings(s = {}) {
  return {
    riskPct:     toPct(s.riskPct, 0.01),
    riskReward:  String(s.riskRewardRatio ?? 2),
    maxDrawdown: toPct(s.maxSessionDrawdown, 0.2),
    liqBuffer:   toPct(s.liqBufferPct, 0.005),
  }
}

// Convert display strings → server payload (camelCase fractions / ratio).
export function riskFieldsToPayload(v = {}) {
  return {
    riskPct:            parseFloat(v.riskPct) / 100,
    riskRewardRatio:    parseFloat(v.riskReward),
    maxSessionDrawdown: parseFloat(v.maxDrawdown) / 100,
    liqBufferPct:       parseFloat(v.liqBuffer) / 100,
  }
}

export default function RiskParamsFields({ values = RISK_DEFAULTS, onChange, inputClassName, labelClassName }) {
  const inputCls =
    inputClassName ||
    'h-10 w-full rounded border border-gray-800 bg-gray-950 px-3 text-sm text-gray-100 focus:outline-none focus:border-emerald-500 transition-colors'
  const labelCls = labelClassName || 'text-gray-400 text-xs font-medium'
  const set = (key) => (e) => onChange({ ...values, [key]: e.target.value })

  return (
    <div className="grid grid-cols-2 gap-3">
      {FIELDS.map((f) => (
        <div key={f.key} className="flex flex-col gap-1.5">
          <label className={labelCls}>{f.label}</label>
          <input
            type="number"
            step={f.step}
            min="0"
            value={values[f.key] ?? ''}
            onChange={set(f.key)}
            className={inputCls}
          />
          <p className="text-gray-600 text-[10px]">{f.hint}</p>
        </div>
      ))}
    </div>
  )
}
