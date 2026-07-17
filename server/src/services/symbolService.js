const engineClient = require('./engineClient')

let _cachedSymbols = null
let _cacheTimestamp = 0
const CACHE_TTL_MS = 300_000 // 5 minutes

async function _fetchSymbols() {
  const { data } = await engineClient.get('/candles/symbols')
  const all = data?.data?.all || []
  const futures = data?.data?.futures || []
  return { all, futures }
}

async function getSymbolData() {
  const now = Date.now()
  if (_cachedSymbols && now - _cacheTimestamp < CACHE_TTL_MS) {
    return _cachedSymbols
  }
  try {
    _cachedSymbols = await _fetchSymbols()
    _cacheTimestamp = now
  } catch {
    if (_cachedSymbols) {
      return _cachedSymbols
    }
    _cachedSymbols = { all: [], futures: [] }
  }
  return _cachedSymbols
}

async function getAllSymbols() {
  const data = await getSymbolData()
  return data.all
}

async function getTieredSymbols() {
  const all = await getAllSymbols()
  return all.map((s) => ({ symbol: s.symbol, tier: s.tier || 'mid' }))
}

async function getTopSymbols() {
  const all = await getAllSymbols()
  return all.map((s) => s.symbol)
}

async function getTradingSymbols() {
  const all = await getAllSymbols()
  return all.filter((s) => s.status === 'TRADING')
}

function bucketSymbols(symbols, tieredList) {
  const tierMap = new Map((tieredList || []).map((e) => [e.symbol, e.tier]))
  const result = { high: [], mid: [], low: [] }
  for (const sym of symbols) {
    const tier = tierMap.get(sym) || 'mid'
    result[tier].push(sym)
  }
  return result
}

function invalidateCache() {
  _cachedSymbols = null
  _cacheTimestamp = 0
}

module.exports = {
  getSymbolData,
  getAllSymbols,
  getTieredSymbols,
  getTopSymbols,
  getTradingSymbols,
  bucketSymbols,
  invalidateCache,
}
