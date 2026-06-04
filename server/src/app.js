const express = require('express')
const helmet = require('helmet')
const cors = require('cors')
const morgan = require('morgan')
const mongoose = require('mongoose')
const Redis = require('ioredis')
const rateLimit = require('express-rate-limit')

const candleRoutes = require('./routes/candle.routes')
const dashboardRoutes = require('./routes/dashboard.routes')
const strategyRoutes = require('./routes/strategy.routes')
const backtestRoutes = require('./routes/backtest.routes')
const tradeRoutes = require('./routes/trade.routes')
const algoRoutes = require('./routes/algo.routes')
const internalRoutes = require('./routes/internal.routes')
const errorHandler = require('./middleware/errorHandler')
const ApiError = require('./utils/ApiError')

const app = express()

app.use(helmet())
app.use(cors({ origin: process.env.CLIENT_URL || 'http://localhost:5173' }))
app.use(morgan('dev'))
app.use(express.json())

const apiLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 100,
  handler: (req, res, next) => {
    next(new ApiError(429, 'TOO_MANY_REQUESTS', 'Too many requests from this IP, please try again after 15 minutes'))
  },
})
app.use('/api/v1/', apiLimiter)

// Health check — verifies live MongoDB and Redis connections
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

app.use('/api/v1/strategies', strategyRoutes)
app.use('/api/v1/candles', candleRoutes)
app.use('/api/v1/backtest', backtestRoutes)
app.use('/api/v1/dashboard', dashboardRoutes)
app.use('/api/v1/trade', tradeRoutes)
app.use('/api/v1/algo', algoRoutes)
app.use('/internal', internalRoutes)

app.use(errorHandler)

module.exports = app
