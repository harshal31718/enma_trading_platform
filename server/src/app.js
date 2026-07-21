const express = require('express')
const helmet = require('helmet')
const cors = require('cors')
const pinoHttp = require('pino-http')
const mongoose = require('mongoose')
const redis = require('./config/redis')
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
const labRoutes = require('./routes/lab.routes')
const errorHandler = require('./middleware/errorHandler')
const { verifyJWT } = require('./middleware/auth.middleware')
const requireInternalKey = require('./middleware/requireInternalKey')
const { authLimiter, mutatingLimiter, readLimiter } = require('./middleware/rateLimiters')
const { checkMongoHealth, checkRedisHealth } = require('./utils/healthCheck')

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

// Unprotected. Plan 8 Step 8.7 (SEC-8): both checks reuse the app's existing
// shared connections (mongoose.connection, config/redis.js's singleton)
// instead of opening — and tearing down — a brand-new connection per request.
app.get('/api/v1/health', async (req, res) => {
  const [mongo, redisStatus] = await Promise.all([
    checkMongoHealth(mongoose.connection),
    checkRedisHealth(redis),
  ])
  const health = { status: 'ok', mongo, redis: redisStatus }
  const statusCode = mongo === 'connected' && redisStatus === 'connected' ? 200 : 503
  res.status(statusCode).json(health)
})

app.use('/api/v1/auth', authLimiter, authRoutes)
// Plan 3 Step 3.1 (SEC-1): engine-only callbacks that can place/close real
// Binance orders — previously completely unauthenticated.
app.use('/internal', requireInternalKey, internalRoutes)

// JWT gate — all routes below require a valid cookie
app.use('/api/v1', verifyJWT)

app.use('/api/v1/strategies', readLimiter, strategyRoutes)
app.use('/api/v1/candles', readLimiter, candleRoutes)
app.use('/api/v1/backtest', readLimiter, backtestRoutes)
app.use('/api/v1/dashboard', readLimiter, dashboardRoutes)
app.use('/api/v1/trade', mutatingLimiter, tradeRoutes)
app.use('/api/v1/algo', mutatingLimiter, algoRoutes)
app.use('/api/v1/settings', readLimiter, settingsRoutes)
app.use('/api/v1/order-history', readLimiter, orderHistoryRoutes)
app.use('/api/v1/risk', readLimiter, riskRoutes)
app.use('/api/v1/lab', mutatingLimiter, labRoutes)
app.use('/api/v1/admin', readLimiter, adminRoutes)

app.use(errorHandler)

module.exports = app
