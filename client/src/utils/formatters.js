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
