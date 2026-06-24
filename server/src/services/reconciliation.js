const { lockSymbol, releaseSymbolLock, getSymbolLock, getAllLockedSymbols } = require('./symbolLock')
const engineClient = require('./engineClient')
const LiveSession = require('../models/LiveSession')
const { getIO } = require('../config/socket')

async function reconcileSymbolLocks() {
  try {
    const apiKey = process.env.BINANCE_TESTNET_API_KEY
    const apiSecret = process.env.BINANCE_TESTNET_SECRET
    const headers = (apiKey && apiSecret) ? {
      'X-Binance-API-Key': apiKey,
      'X-Binance-API-Secret': apiSecret,
      'X-Binance-Mode': 'testnet',
    } : null

    // 1. Stop orphaned active sessions (server/engine restarted mid-run)
    const orphanedSessions = await LiveSession.find({
      status: { $in: ['running', 'starting', 'stopping'] }
    }).lean()

    for (const session of orphanedSessions) {
      await LiveSession.findByIdAndUpdate(session._id, {
        status: 'stopped',
        stoppedAt: new Date(),
      }).catch(() => {})
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

    // 3. Re-lock open manual positions
    try {
      const posRes = await engineClient.get('/trade/positions')
      const positions = posRes.data?.data?.positions || []
      for (const pos of positions) {
        if (parseFloat(pos.positionAmt) !== 0) {
          const existing = await getSymbolLock(pos.symbol)
          if (!existing) {
            await lockSymbol(pos.symbol, 'manual').catch(() => {})
          }
        }
      }
    } catch {
      // Position fetch may fail if no Binance keys configured — that's OK
    }

    console.log('[Startup] Symbol lock reconciliation complete')
  } catch (err) {
    console.error('[Startup] Lock reconciliation failed:', err.message)
  }
}

module.exports = { reconcileSymbolLocks }
