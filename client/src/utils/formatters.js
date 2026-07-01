export function formatQty(value) {
  return parseFloat(parseFloat(value).toFixed(6)).toString()
}

export function formatPrice(value) {
  return `$${parseFloat(value).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

export function formatPct(value) {
  return `${parseFloat(value).toFixed(2)}%`
}

export function formatPnl(value) {
  const num = parseFloat(value)
  return {
    value: `${num >= 0 ? '+' : '-'}$${Math.abs(num).toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`,
    isPositive: num >= 0,
  }
}

export function formatSignedPct(value) {
  const num = parseFloat(value)
  const sign = num >= 0 ? '+' : ''
  return `${sign}${num.toFixed(2)}%`
}

export function formatIsoDate(dateString) {
  if (!dateString) return ''
  const date = new Date(dateString)
  return date.toLocaleString()
}

/**
 * Abbreviated large-number formatter, e.g. 1234567 -> "$1.2M" when prefix="$".
 * decimals controls fraction digits on the abbreviated value (default 1).
 */
export function formatCompact(value, { prefix = '', decimals = 1 } = {}) {
  const num = parseFloat(value)
  if (!Number.isFinite(num)) return `${prefix}0`
  const abs = Math.abs(num)
  const sign = num < 0 ? '-' : ''
  const units = [
    { value: 1e12, suffix: 'T' },
    { value: 1e9, suffix: 'B' },
    { value: 1e6, suffix: 'M' },
    { value: 1e3, suffix: 'K' },
  ]
  for (const { value: threshold, suffix } of units) {
    if (abs >= threshold) {
      return `${sign}${prefix}${(abs / threshold).toFixed(decimals)}${suffix}`
    }
  }
  return `${sign}${prefix}${abs.toFixed(decimals)}`
}

/**
 * Unsigned percent with configurable decimals (default 2), e.g. formatPercent(32.4123) -> "32.41%"
 */
export function formatPercent(value, decimals = 2) {
  const num = parseFloat(value)
  if (!Number.isFinite(num)) return '0.00%'
  return `${num.toFixed(decimals)}%`
}

/**
 * Canonical date+time formatter. UTC by default (per client/CLAUDE.md convention — traders in
 * different timezones must see the same absolute time). Pass { local: true } to render in the
 * viewer's local timezone instead.
 */
export function formatDateTime(iso, { local = false } = {}) {
  if (!iso) return '--'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '--'
  const opts = {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    ...(local ? {} : { timeZone: 'UTC' }),
  }
  const formatted = date.toLocaleString('en-US', opts)
  return local ? formatted : `${formatted} UTC`
}

/**
 * Canonical date-only formatter (no time component). UTC by default.
 */
export function formatDate(iso, { local = false } = {}) {
  if (!iso) return '--'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '--'
  const opts = {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    ...(local ? {} : { timeZone: 'UTC' }),
  }
  return date.toLocaleDateString('en-US', opts)
}
