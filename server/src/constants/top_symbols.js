// Top Binance USDS-M Perpetuals — curated for Chaos Mode stress testing.
// This module now derives its symbol list from the engine's live exchangeInfo
// (via symbolService.js), falling back to a hand-maintained static list if the
// engine is unreachable (e.g. during initial startup).
//
// The static fallback preserves the exact same 80-symbol tiered list that was
// previously the sole source. When the engine is reachable, the list is dynamic
// and reflects current exchange trading status + volume rankings.
//
// Three volume tiers:
//   high — top 20 by 24h quote volume; deepest books, tightest spreads.
//   mid  — solid liquidity (top 55), suitable for meaningful position sizing.
//   low  — still acceptable; lower OI but actively traded on Binance Futures.

const symbolService = require('../services/symbolService')

// ── Static fallback (last updated 2026-06-22) ──────────────────────────────
const STATIC_TIERED = [
  { symbol: 'BTCUSDT',        tier: 'high' },
  { symbol: 'ETHUSDT',        tier: 'high' },
  { symbol: 'SOLUSDT',        tier: 'high' },
  { symbol: 'BNBUSDT',        tier: 'high' },
  { symbol: 'XRPUSDT',        tier: 'high' },
  { symbol: 'DOGEUSDT',       tier: 'high' },
  { symbol: 'ADAUSDT',        tier: 'high' },
  { symbol: 'AVAXUSDT',       tier: 'high' },
  { symbol: 'LINKUSDT',       tier: 'high' },
  { symbol: 'DOTUSDT',        tier: 'high' },
  { symbol: 'TRXUSDT',        tier: 'high' },
  { symbol: 'LTCUSDT',        tier: 'high' },
  { symbol: 'NEARUSDT',       tier: 'high' },
  { symbol: 'AAVEUSDT',       tier: 'high' },
  { symbol: 'INJUSDT',        tier: 'high' },
  { symbol: 'SUIUSDT',        tier: 'high' },
  { symbol: 'ARBUSDT',        tier: 'high' },
  { symbol: 'OPUSDT',         tier: 'high' },
  { symbol: 'MKRUSDT',        tier: 'high' },
  { symbol: 'RUNEUSDT',       tier: 'high' },

  { symbol: 'APTUSDT',        tier: 'mid' },
  { symbol: 'ATOMUSDT',       tier: 'mid' },
  { symbol: 'BCHUSDT',        tier: 'mid' },
  { symbol: 'ETCUSDT',        tier: 'mid' },
  { symbol: 'XLMUSDT',        tier: 'mid' },
  { symbol: 'FILUSDT',        tier: 'mid' },
  { symbol: 'MATICUSDT',      tier: 'mid' },
  { symbol: 'LDOUSDT',        tier: 'mid' },
  { symbol: 'CRVUSDT',        tier: 'mid' },
  { symbol: 'SNXUSDT',        tier: 'mid' },
  { symbol: 'COMPUSDT',       tier: 'mid' },
  { symbol: 'JUPUSDT',        tier: 'mid' },
  { symbol: 'PYTHUSDT',       tier: 'mid' },
  { symbol: 'ORDIUSDT',       tier: 'mid' },
  { symbol: 'STRKUSDT',       tier: 'mid' },
  { symbol: 'JTOUSDT',        tier: 'mid' },
  { symbol: 'GALAUSDT',       tier: 'mid' },
  { symbol: 'SANDUSDT',       tier: 'mid' },
  { symbol: 'MANAUSDT',       tier: 'mid' },
  { symbol: 'AXSUSDT',        tier: 'mid' },
  { symbol: 'EOSUSDT',        tier: 'mid' },
  { symbol: 'VETUSDT',        tier: 'mid' },
  { symbol: 'ALGOUSDT',       tier: 'mid' },
  { symbol: 'HBARUSDT',       tier: 'mid' },
  { symbol: 'GRTUSDT',        tier: 'mid' },
  { symbol: 'XMRUSDT',        tier: 'mid' },
  { symbol: 'ENJUSDT',        tier: 'mid' },
  { symbol: '1000BONKUSDT',   tier: 'mid' },
  { symbol: 'KAVAUSDT',       tier: 'mid' },
  { symbol: 'YFIUSDT',        tier: 'mid' },
  { symbol: 'CAKEUSDT',       tier: 'mid' },
  { symbol: 'ZILUSDT',        tier: 'mid' },
  { symbol: 'CHZUSDT',        tier: 'mid' },
  { symbol: 'POLUSDT',        tier: 'mid' },

  { symbol: 'KSMUSDT',        tier: 'low' },
  { symbol: 'DASHUSDT',       tier: 'low' },
  { symbol: 'ZRXUSDT',        tier: 'low' },
  { symbol: 'LRCUSDT',        tier: 'low' },
  { symbol: 'SKLUSDT',        tier: 'low' },
  { symbol: 'RVNUSDT',        tier: 'low' },
  { symbol: 'COTIUSDT',       tier: 'low' },
  { symbol: 'CELOUSDT',       tier: 'low' },
  { symbol: 'ICPUSDT',        tier: 'low' },
  { symbol: 'FLOWUSDT',       tier: 'low' },
  { symbol: 'QNTUSDT',        tier: 'low' },
  { symbol: 'EGLDUSDT',       tier: 'low' },
  { symbol: 'IOSTUSDT',       tier: 'low' },
  { symbol: 'ONTUSDT',        tier: 'low' },
  { symbol: 'ANKRUSDT',       tier: 'low' },
  { symbol: 'BANDUSDT',       tier: 'low' },
  { symbol: 'STXUSDT',        tier: 'low' },
  { symbol: 'CTSIUSDT',       tier: 'low' },
  { symbol: 'RSRUSDT',        tier: 'low' },
  { symbol: 'SFPUSDT',        tier: 'low' },
  { symbol: 'ALPACAUSDT',     tier: 'low' },
  { symbol: 'BLZUSDT',        tier: 'low' },
  { symbol: 'ARUSDT',         tier: 'low' },
  { symbol: 'LINAUSDT',       tier: 'low' },
]

// ── Dynamic resolution ────────────────────────────────────────────────────

async function _resolveTiered() {
  try {
    const dynamic = await symbolService.getTieredSymbols()
    if (dynamic && dynamic.length > 20) return dynamic
  } catch {
    // fall through to static
  }
  return STATIC_TIERED
}

async function _resolveTop() {
  try {
    const top = await symbolService.getTopSymbols()
    if (top && top.length > 20) return top
  } catch {
    // fall through
  }
  return STATIC_TIERED.map((e) => e.symbol)
}

// ── Exports ───────────────────────────────────────────────────────────────

let _tieredCache = null
let _topCache = null

async function getTIERED_SYMBOLS() {
  if (!_tieredCache) _tieredCache = await _resolveTiered()
  return _tieredCache
}

async function getTOP_SYMBOLS() {
  if (!_topCache) _topCache = await _resolveTop()
  return _topCache
}

function bucketSymbols(symbols) {
  const tierMap = new Map(STATIC_TIERED.map((e) => [e.symbol, e.tier]))
  const result = { high: [], mid: [], low: [] }
  for (const sym of symbols) {
    const tier = tierMap.get(sym) || 'low'
    result[tier].push(sym)
  }
  return result
}

function invalidateCache() {
  _tieredCache = null
  _topCache = null
  symbolService.invalidateCache()
}

module.exports = {
  getTIERED_SYMBOLS,
  getTOP_SYMBOLS,
  TOP_SYMBOLS: STATIC_TIERED.map((e) => e.symbol),
  TIERED_SYMBOLS: STATIC_TIERED,
  bucketSymbols,
  invalidateCache,
}
