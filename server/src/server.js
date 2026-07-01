require('dotenv').config()
const http = require('http')
const mongoose = require('mongoose')
const app = require('./app')
const { initSocket } = require('./config/socket')

// Import worker to start it — side effect only
require('./workers/backtest.worker')

const PORT = process.env.PORT || 5000
const MONGO_URI = process.env.MONGO_URI || 'mongodb://mongodb:27017/enma_trading'
const MONGO_DB = process.env.MONGO_DB || 'enma_trading'

const { reconcileSymbolLocks } = require('./services/reconciliation')
const PlatformConfig = require('./models/PlatformConfig')

async function seedPlatformConfig() {
  const adminEmail = process.env.ADMIN_EMAIL?.toLowerCase()
  if (!adminEmail) return
  const exists = await PlatformConfig.findById('platform')
  if (!exists) {
    await PlatformConfig.create({
      _id: 'platform',
      allowedEmails: [{ email: adminEmail, addedBy: 'system', addedAt: new Date() }],
    })
    console.log('PlatformConfig seeded with admin email:', adminEmail)
  }
}

async function startServer() {
  await mongoose.connect(MONGO_URI, { dbName: MONGO_DB })
  console.log('MongoDB connected')

  await seedPlatformConfig()
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
