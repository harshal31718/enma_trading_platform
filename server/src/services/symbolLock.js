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

module.exports = { isSymbolFree, lockSymbol, releaseSymbolLock, getSymbolLock, getAllLockedSymbols }
