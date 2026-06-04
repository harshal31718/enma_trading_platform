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
    const { lockSymbol, releaseSymbolLock, getSymbolLock } = require('./services/symbolLock')
    const engineClient = require('./services/engineClient')
    const LiveSession = require('./models/LiveSession')

    // Re-lock symbols for running/starting bot sessions
    const activeSessions = await LiveSession.find({
      status: { $in: ['running', 'starting', 'stopping'] }
    }).lean()

    for (const session of activeSessions) {
      for (const symbol of session.symbols) {
        const existing = await getSymbolLock(symbol)
        if (!existing) {
          await lockSymbol(symbol, 'bot', String(session._id)).catch(() => {})
        }
      }
    }

    // Re-lock open manual positions
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
