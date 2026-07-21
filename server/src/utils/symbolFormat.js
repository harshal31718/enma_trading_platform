// Binance USDT-M futures symbols are uppercase alphanumeric (e.g. BTCUSDT,
// 1000SHIBUSDT) — never contain '.', '$', or other characters that could be
// abused as a Mongo dot-path / operator segment when used to build a dynamic
// `$set`/`$unset` key (e.g. `positionDetails.${symbol}`) or a Redis lock key.
const SYMBOL_REGEX = /^[A-Z0-9]{5,20}$/

function isValidSymbolFormat(symbol) {
  return typeof symbol === 'string' && SYMBOL_REGEX.test(symbol)
}

module.exports = { SYMBOL_REGEX, isValidSymbolFormat }
