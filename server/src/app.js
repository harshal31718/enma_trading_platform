const express = require('express')
const helmet = require('helmet')
const cors = require('cors')
const pinoHttp = require('pino-http')
const mongoose = require('mongoose')
const Redis = require('ioredis')
const rateLimit = require('express-rate-limit')
const cookieParser = require('cookie-parser')

require('./config/passport')

const logger = require('./config/logger')
const requestId = require('./middleware/requestId')

const authRoutes = require('./routes/auth.routes')
const adminRoutes = require('./routes/admin.routes')
const candleRoutes = require('./routes/candle.routes')
const dashboardRoutes = require('./routes/dashboard.routes')
const strategyRoutes = require('./routes/strategy.routes')
const backtestRoutes = require('./routes/backtest.routes')
const tradeRoutes = require('./routes/trade.routes')
const algoRoutes = require('./routes/algo.routes')
const internalRoutes = require('./routes/internal.routes')
const settingsRoutes = require('./routes/settings.routes')
const orderHistoryRoutes = require('./routes/orderHistory.routes')
const riskRoutes = require('./routes/risk.routes')
const errorHandler = require('./middleware/errorHandler')
const { verifyJWT } = require('./middleware/auth.middleware')
const ApiError = require('./utils/ApiError')

const passport = require('passport')

const app = express()

// Behind the production Nginx reverse proxy: needed for express-rate-limit
// (X-Forwarded-For) and correct req.ip / secure-cookie handling
app.set('trust proxy', 1)

app.use(cookieParser())
app.use(helmet())
app.use(cors({ origin: process.env.CLIENT_URL || 'http://localhost:5173', credentials: true }))
app.use(requestId)
app.use(pinoHttp({
  logger,
  genReqId: (req) => req.id,
  customLogLevel: (req, res, err) => {
    if (res.statusCode >= 500 || err) return 'error'
    if (res.statusCode >= 400) return 'warn'
    return 'info'
  },
}))
app.use(express.json())
app.use(passport.initialize())

const apiLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 10000,
  handler: (req, res, next) => {
    next(new ApiError(429, 'TOO_MANY_REQUESTS', 'Too many requests from this IP, please try again after 15 minutes'))
  },
})
app.use('/api/v1/', apiLimiter)

// Unprotected
app.get('/api/v1/health', async (req, res) => {
  const health = { status: 'ok', mongo: 'disconnected', redis: 'disconnected' }

  try {
    if (mongoose.connection.readyState === 1) {
      await mongoose.connection.db.admin().command({ ping: 1 })
      health.mongo = 'connected'
    }
  } catch {
    health.mongo = 'error'
  }

  try {
    const redis = new Redis(process.env.REDIS_URL, { lazyConnect: true })
    await redis.connect()
    await redis.ping()
    redis.disconnect()
    health.redis = 'connected'
  } catch {
    health.redis = 'error'
  }

  const statusCode = health.mongo === 'connected' && health.redis === 'connected' ? 200 : 503
  res.status(statusCode).json(health)
})

app.use('/api/v1/auth', authRoutes)
app.use('/internal', internalRoutes)

// JWT gate — all routes below require a valid cookie
app.use('/api/v1', verifyJWT)

app.use('/api/v1/strategies', strategyRoutes)
app.use('/api/v1/candles', candleRoutes)
app.use('/api/v1/backtest', backtestRoutes)
app.use('/api/v1/dashboard', dashboardRoutes)
app.use('/api/v1/trade', tradeRoutes)
app.use('/api/v1/algo', algoRoutes)
app.use('/api/v1/settings', settingsRoutes)
app.use('/api/v1/order-history', orderHistoryRoutes)
app.use('/api/v1/risk', riskRoutes)
app.use('/api/v1/admin', adminRoutes)

app.use(errorHandler)

module.exports = app
