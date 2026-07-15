// Plan 3 Step 3.4 (SEC-5): the previous single global limiter (10k/15min per
// IP, ~11 rps) was effectively off. Tiered limits proportional to blast
// radius, backed by Redis (already in the stack) so limits hold across
// multiple server instances instead of resetting per-process.
const rateLimit = require('express-rate-limit')
const { RedisStore } = require('rate-limit-redis')
const redis = require('../config/redis')
const ApiError = require('../utils/ApiError')

function makeLimiter({ windowMs, max, prefix, message }) {
  return rateLimit({
    windowMs,
    max,
    standardHeaders: true,
    legacyHeaders: false,
    store: new RedisStore({
      sendCommand: (...args) => redis.call(...args),
      prefix: `rl:${prefix}:`,
    }),
    handler: (req, res, next) => {
      next(new ApiError(429, 'TOO_MANY_REQUESTS', message))
    },
  })
}

// Auth: brute-force protection on login/callback.
const authLimiter = makeLimiter({
  windowMs: 15 * 60 * 1000,
  max: 20,
  prefix: 'auth',
  message: 'Too many authentication attempts, please try again later.',
})

// Mutating trade/algo actions: bounded well below what a runaway client
// script or compromised session could use to hammer Binance through us.
const mutatingLimiter = makeLimiter({
  windowMs: 60 * 1000,
  max: 60,
  prefix: 'mutate',
  message: 'Too many requests, please slow down.',
})

// General reads: generous — dashboards/tickers poll frequently.
const readLimiter = makeLimiter({
  windowMs: 15 * 60 * 1000,
  max: 10000,
  prefix: 'read',
  message: 'Too many requests from this IP, please try again after 15 minutes.',
})

module.exports = { authLimiter, mutatingLimiter, readLimiter }
