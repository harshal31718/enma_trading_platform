const { lockSymbol, releaseSymbolLock, getSymbolLock, getAllLockedSymbols } = require('./symbolLock')
const engineClient = require('./engineClient')
const LiveSession = require('../models/LiveSession')
const Settings = require('../models/Settings')
const { decrypt } = require('../utils/encryption')
const { getIO } = require('../config/socket')

// Resolve a user's testnet Binance headers from their Settings doc — the same
// per-user, AES-encrypted credential store the Settings UI writes to. Never
// reads `.env` (see DECISIONS.md §9: credentials live in MongoDB per user, not
// `.env`). Results are cached for the duration of one reconciliation pass.
// Mode is pinned to testnet (trading is testnet-only; mainnet keys are read-only).
async function _testnetHeadersFor(userId, cache) {
  if (!userId) return null
  if (cache.has(userId)) return cache.get(userId)

  let headers = null
  try {
    const settings = await Settings.findOne({ userId }).lean()
    const apiKey = settings?.encryptedApiKey ? decrypt(settings.encryptedApiKey) : ''
    const apiSecret = settings?.encryptedApiSecret ? decrypt(settings.encryptedApiSecret) : ''
    if (apiKey && apiSecret) {
      headers = {
        'X-Binance-API-Key': apiKey,
        'X-Binance-API-Secret': apiSecret,
        'X-Binance-Mode': 'testnet',
      }
    }
  } catch {
    headers = null
  }

  cache.set(userId, headers)
  return headers
}

async function reconcileSymbolLocks() {
  try {
    // Per-pass cache of userId → decrypted testnet headers (from Settings).
    const headerCache = new Map()

    // 1. Stop orphaned active sessions (server/engine restarted mid-run)
    const orphanedSessions = await LiveSession.find({
      status: { $in: ['running', 'starting', 'stopping'] }
    }).lean()

    for (const session of orphanedSessions) {
      await LiveSession.findByIdAndUpdate(session._id, {
        status: 'stopped',
        stoppedAt: new Date(),
        openPositions: [],
        positionDetails: {},
      }).catch(() => {})
      // Close positions with the session owner's own credentials (from Settings).
      const headers = await _testnetHeadersFor(session.userId, headerCache)
      for (const symbol of session.symbols) {
        await releaseSymbolLock(symbol).catch(() => {})
        if (headers) {
          await engineClient.post('/trade/close-position', { symbol }, { headers }).catch((e) => {
            console.log(`[Startup] No position to close for ${symbol}: ${e.message}`)
          })
        }
      }
      try {
        const io = getIO()
        io.emit('algo:session:update', {
          sessionId: session._id,
          status: 'stopped',
          pnl: session.pnl || '0',
          openPositions: [],
        })
      } catch (wsErr) {
        // socket may not be initialized yet, that's fine
      }
      console.log(`[Startup] Force-stopped orphaned session ${session._id} (${session.symbols.join(', ')})`)
    }

    // 2. Release bot locks whose session no longer exists in MongoDB.
    const allLocks = await getAllLockedSymbols()
    const botLockSessionIds = [...new Set(
      Object.values(allLocks)
        .filter(l => l.reason === 'bot' && l.sessionId)
        .map(l => l.sessionId)
    )]
    if (botLockSessionIds.length > 0) {
      const existingSessions = await LiveSession.find(
        { _id: { $in: botLockSessionIds } },
        { _id: 1 }
      ).lean()
      const existingIds = new Set(existingSessions.map(s => String(s._id)))
      for (const [symbol, lock] of Object.entries(allLocks)) {
        if (lock.reason === 'bot' && lock.sessionId && !existingIds.has(lock.sessionId)) {
          await releaseSymbolLock(symbol).catch(() => {})
          console.log(`[Startup] Released stale bot lock for ${symbol} (session ${lock.sessionId} deleted)`)
        }
      }
    }

    // 3. Re-lock open manual positions, per user, using each user's own
    //    Settings-stored credentials (never `.env`).
    const keyedUsers = await Settings.find(
      { encryptedApiKey: { $ne: '' }, encryptedApiSecret: { $ne: '' } },
      { userId: 1 }
    ).lean()
    for (const { userId } of keyedUsers) {
      const headers = await _testnetHeadersFor(userId, headerCache)
      if (!headers) continue
      try {
        const posRes = await engineClient.get('/trade/positions', { headers })
        const positions = posRes.data?.data || []
        for (const pos of positions) {
          if (parseFloat(pos.positionAmt) !== 0) {
            const existing = await getSymbolLock(pos.symbol)
            if (!existing) {
              await lockSymbol(pos.symbol, 'manual').catch(() => {})
            }
          }
        }
      } catch {
        // Per-user position fetch may fail (revoked keys, etc.) — skip that user.
      }
    }

    console.log('[Startup] Symbol lock reconciliation complete')
  } catch (err) {
    console.error('[Startup] Lock reconciliation failed:', err.message)
  }
}

module.exports = { reconcileSymbolLocks }
