require('dotenv').config()
const http = require('http')
const mongoose = require('mongoose')
const app = require('./app')
const { initSocket } = require('./config/socket')

// Import workers to start them — side effect only
require('./workers/backtest.worker')
require('./workers/simulation.worker')
require('./workers/optimization.worker')
require('./workers/pbo.worker')

const PORT = process.env.PORT || 5000
const MONGO_URI = process.env.MONGO_URI || 'mongodb://mongodb:27017/enma_trading'
const MONGO_DB = process.env.MONGO_DB || 'enma_trading'

const { reconcileSymbolLocks, reconcileFullAccountPositions } = require('./services/reconciliation')
const eventStreamConsumer = require('./services/eventStreamConsumer')

const FULL_RECONCILE_INTERVAL_MS = 10 * 60 * 1000 // 10 min — safety-net sweep, see reconciliation.js

async function startServer() {
  await mongoose.connect(MONGO_URI, { dbName: MONGO_DB })
  console.log('MongoDB connected')

  await reconcileSymbolLocks()

  const httpServer = http.createServer(app)
  initSocket(httpServer)

  // Plan 6 Step 6.5 (ENG-16): consumes the engine's algo:events Redis
  // Stream — started after initSocket() so getIO() resolves inside it.
  await eventStreamConsumer.start()

  httpServer.listen(PORT, '0.0.0.0', () => {
    console.log(`Server running on port ${PORT}`)
  })

  const reconcileTimer = setInterval(() => {
    reconcileFullAccountPositions().catch((e) =>
      console.error('[Reconciliation] Full-account sweep error:', e.message)
    )
  }, FULL_RECONCILE_INTERVAL_MS)

  async function shutdown(signal) {
    console.log(`${signal} received — shutting down gracefully`)
    clearInterval(reconcileTimer)
    await eventStreamConsumer.stop()
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
