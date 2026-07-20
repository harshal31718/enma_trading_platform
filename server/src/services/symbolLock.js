const redis = require('../config/redis')
const ApiError = require('../utils/ApiError')

const LOCK_PREFIX = 'symbol:lock:'

async function isSymbolFree(symbol) {
  const val = await redis.get(`${LOCK_PREFIX}${symbol}`)
  return val === null
}

async function lockSymbol(symbol, reason, sessionId = null) {
  const lockData = {
    reason,
    sessionId,
    lockedAt: new Date().toISOString(),
  }
  // SET NX — atomic, only set if key doesn't exist
  const result = await redis.set(
    `${LOCK_PREFIX}${symbol}`,
    JSON.stringify(lockData),
    'NX'
  )
  if (!result) {
    const existing = await getSymbolLock(symbol)
    throw new ApiError(
      409,
      'SYMBOL_LOCKED',
      `Symbol ${symbol} is already locked: ${existing?.reason || 'unknown'}`
    )
  }
}

async function releaseSymbolLock(symbol, sessionId = null) {
  if (sessionId) {
    const lock = await getSymbolLock(symbol)
    if (lock && lock.sessionId !== sessionId) {
      return
    }
  }
  await redis.del(`${LOCK_PREFIX}${symbol}`)
}

async function getSymbolLock(symbol) {
  const val = await redis.get(`${LOCK_PREFIX}${symbol}`)
  if (!val) return null
  try { return JSON.parse(val) } catch { return null }
}

async function getAllLockedSymbols() {
  const keys = await redis.keys(`${LOCK_PREFIX}*`)
  const result = {}
  for (const key of keys) {
    const symbol = key.replace(LOCK_PREFIX, '')
    const data = await getSymbolLock(symbol)
    if (data) result[symbol] = data
  }
  return result
}

// Plan 7 Step 7.1 (SRV-1) third slice: the manual-trading side's "reject if a
// bot already owns this symbol" guard, duplicated identically across
// trade.controller.js's placeOrder/placeOCOOrder/placeOrderWithTpSl (and with
// one word changed in closePosition). Throws, so callers just `await` it
// inside their existing try/catch — no behavior change from the inline
// `if (lock && lock.reason === 'bot') return next(new ApiError(...))` it
// replaces, since every call site's catch already forwards ApiError as-is.
async function assertSymbolNotBotLocked(symbol, { closing = false } = {}) {
  const lock = await getSymbolLock(symbol)
  if (lock && lock.reason === 'bot') {
    throw new ApiError(409, 'SYMBOL_LOCKED', closing
      ? `Symbol ${symbol} is locked by an active bot session and cannot be closed manually.`
      : `Symbol ${symbol} is locked by an active bot session. Close it through the bot page or wait for the bot to close it.`)
  }
}

// The engine-callback side's inverse guard — "reject unless THIS bot session
// owns the lock" — duplicated identically across algo.controller.js's
// handleAlgoPlaceOrder/ClosePosition/SetLeverage.
async function assertSymbolLockedByBotSession(symbol, sessionId) {
  const lock = await getSymbolLock(symbol)
  if (!lock || lock.reason !== 'bot' || lock.sessionId !== sessionId) {
    throw new ApiError(409, 'SYMBOL_LOCKED', `Symbol ${symbol} is not locked by this bot session.`)
  }
}

module.exports = {
  isSymbolFree, lockSymbol, releaseSymbolLock, getSymbolLock, getAllLockedSymbols,
  assertSymbolNotBotLocked, assertSymbolLockedByBotSession,
}
