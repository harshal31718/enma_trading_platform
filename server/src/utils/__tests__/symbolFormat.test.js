const { isValidSymbolFormat, SYMBOL_REGEX } = require('../symbolFormat')

describe('isValidSymbolFormat', () => {
  test('accepts standard Binance USDT-M futures symbols', () => {
    expect(isValidSymbolFormat('BTCUSDT')).toBe(true)
    expect(isValidSymbolFormat('1000SHIBUSDT')).toBe(true)
    expect(isValidSymbolFormat('ETHUSDT')).toBe(true)
  })

  test('rejects a Mongo dot-path segment', () => {
    expect(isValidSymbolFormat('foo.bar')).toBe(false)
  })

  test('rejects a Mongo operator-shaped key', () => {
    expect(isValidSymbolFormat('$where')).toBe(false)
    expect(isValidSymbolFormat('__proto__')).toBe(false)
  })

  test('rejects lowercase, empty, and non-string input', () => {
    expect(isValidSymbolFormat('btcusdt')).toBe(false)
    expect(isValidSymbolFormat('')).toBe(false)
    expect(isValidSymbolFormat(null)).toBe(false)
    expect(isValidSymbolFormat(undefined)).toBe(false)
    expect(isValidSymbolFormat(123)).toBe(false)
    expect(isValidSymbolFormat({ symbol: 'BTCUSDT' })).toBe(false)
  })

  test('rejects a symbol exceeding the max length', () => {
    expect(isValidSymbolFormat('A'.repeat(21))).toBe(false)
  })

  test('SYMBOL_REGEX is exported for direct use', () => {
    expect(SYMBOL_REGEX.test('BTCUSDT')).toBe(true)
  })
})
