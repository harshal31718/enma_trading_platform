// Plan 7 Step 7.4 (CLI-1): Trade-page-specific formatters, extracted out of
// Trade.jsx (was a 1,760-line file with ~20 components crammed into one
// module). Deliberately separate from `@/utils/formatters.js` — these are
// symbol-precision-aware (tickSize/stepSize-driven decimal places), which
// the shared formatters don't do; not a duplicate, a different concern.
import { SYMBOL_LIMITS } from '@/utils/symbolLimits'

export function fmtPrice(n) {
  return Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function getPrecisionDecimalPlaces(step) {
  if (!step) return 4
  const stepStr = step.toString()
  if (stepStr.includes('e-')) {
    const parts = stepStr.split('e-')
    return parseInt(parts[1], 10)
  }
  if (stepStr.includes('.')) {
    return stepStr.split('.')[1].length
  }
  return 0
}

export function fmtPriceForSymbol(n, symbol) {
  const limits = SYMBOL_LIMITS[symbol]
  const dp = limits ? getPrecisionDecimalPlaces(limits.tickSize) : 2
  return Number(n).toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp })
}

export function fmtQtyForSymbol(n, symbol) {
  const limits = SYMBOL_LIMITS[symbol]
  const dp = limits ? getPrecisionDecimalPlaces(limits.stepSize) : 4
  return Number(n).toFixed(Math.max(dp, 0))
}

export function fmtQty(n, dp = 4) {
  return Number(n).toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp })
}

export function roundToStep(value, step) {
  const decimals = getPrecisionDecimalPlaces(step)
  const factor = Math.pow(10, decimals)
  return Math.floor(value * factor) / factor
}

export function fmtPct(n) {
  const v = parseFloat(n)
  return (v >= 0 ? '+' : '') + v.toFixed(2) + '%'
}
