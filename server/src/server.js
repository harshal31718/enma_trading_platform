require('dotenv').config()
const http = require('http')
const mongoose = require('mongoose')
const app = require('./app')
const { initSocket } = require('./config/socket')

// Import worker to start it — side effect only
require('./workers/backtest.worker')

const PORT = process.env.PORT || 5000
const MONGO_URI = process.env.MONGO_URI || 'mongodb://mongodb:27017/enma_trading'

// Startup reconciliation — ensure Redis lock state matches DB state
async function reconcileSymbolLocks() {
  try {
    const { lockSymbol, releaseSymbolLock, getSymbolLock, getAllLockedSymbols } = require('./services/symbolLock')
    const engineClient = require('./services/engineClient')
    const LiveSession = require('./models/LiveSession')

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
      console.log(`[Startup] Force-stopped orphaned session ${session._id} (${session.symbols.join(', ')})`)
    }

    // 2. Release bot locks whose session no longer exists in MongoDB.
    //    This covers the case where sessions were deleted (e.g. deleteAllStopped)
    //    before the engine got a chance to release their locks.
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

async function startServer() {
  await mongoose.connect(MONGO_URI)
  console.log('MongoDB connected')

  await reconcileSymbolLocks()

  const httpServer = http.createServer(app)
  initSocket(httpServer)

  httpServer.listen(PORT, '0.0.0.0', () => {
    console.log(`Server running on port ${PORT}`)
  })

  async function shutdown(signal) {
    console.log(`${signal} received — shutting down gracefully`)
    httpServer.close(async () => {
      await mongoose.connection.close()
      console.log('MongoDB connection closed')
      process.exit(0)
    })
  }

  process.on('SIGINT', () => shutdown('SIGINT'))
  process.on('SIGTERM', () => shutdown('SIGTERM'))
}

startServer().catch((err) => {
  console.error('Failed to start server:', err)
  process.exit(1)
})
