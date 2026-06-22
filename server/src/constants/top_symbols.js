// Top Binance USDS-M Perpetuals — curated for Chaos Mode stress testing.
// Source: Binance Futures open-interest / volume rankings (curated 2026-06-22).
// Excludes illiquid or recently-deprecated names (BTTUSDT, LUNA2USDT, BONKUSDT,
// STMXUSDT, XECUSDT, FTTUSDT, GTCUSDT, CHRBUSDT — removed for low/unreliable volume).
//
// Three volume tiers:
//   high — top 20 by combined OI + 24h volume; deepest books, tightest spreads.
//   mid  — solid liquidity, suitable for meaningful position sizing.
//   low  — still acceptable; lower OI but actively traded on Binance Futures.
//
// Each strategy in a Chaos run gets a near-equal slice of EACH tier (round-robin
// per tier) so no strategy hogs the high-volume names.  See chaosAllocator.js.

const TIERED_SYMBOLS = [
  // ── HIGH tier (top 20) ──────────────────────────────────────────────────────
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

  // ── MID tier (next 35) ──────────────────────────────────────────────────────
  { symbol: 'APTUSDT',        tier: 'mid' },
  { symbol: 'FTMUSDT',        tier: 'mid' },
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

  // ── LOW tier (final 25) — acceptable volume, actively traded ────────────────
  { symbol: 'KSMUSDT',        tier: 'low' },
  { symbol: 'DASHUSDT',       tier: 'low' },
  { symbol: 'ZRXUSDT',        tier: 'low' },
  { symbol: 'LRCUSDT',        tier: 'low' },
  { symbol: 'SKLUSDT',        tier: 'low' },
  { symbol: 'RVNUSDT',        tier: 'low' },
  { symbol: 'WAVESUSDT',      tier: 'low' },
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

// Flat array — preserves backwards compatibility with all existing imports.
const TOP_SYMBOLS = TIERED_SYMBOLS.map((e) => e.symbol)

/**
 * Split an array of symbol strings into three tier buckets.
 * Only symbols present in TIERED_SYMBOLS get a tier; the rest fall to 'low'.
 *
 * @param {string[]} symbols
 * @returns {{ high: string[], mid: string[], low: string[] }}
 */
function bucketSymbols(symbols) {
  const tierMap = new Map(TIERED_SYMBOLS.map((e) => [e.symbol, e.tier]))
  const result = { high: [], mid: [], low: [] }
  for (const sym of symbols) {
    const tier = tierMap.get(sym) || 'low'
    result[tier].push(sym)
  }
  return result
}

module.exports = { TOP_SYMBOLS, TIERED_SYMBOLS, bucketSymbols }
