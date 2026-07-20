const http = require('http')
const https = require('https')
const axios = require('axios')
const { getRequestId } = require('../config/requestContext')

const httpAgent = new http.Agent({ keepAlive: true })
const httpsAgent = new https.Agent({ keepAlive: true })

// Plan 7 Step 7.2 (SRV-5): every engine call used to inherit a 1-hour budget,
// meaning a request-path call (place order, start session, fetch account)
// held its Express connection open for up to an hour if the engine ever
// hung — a synchronous-request footgun, not a feature. The one hour was
// only ever needed for backtests/simulations/optimizations/PBO runs, and
// those already run through BullMQ workers (backtest.worker.js and its 3
// siblings), not a request/response cycle a browser is waiting on — so they
// opt into `LONG_JOB_TIMEOUT_MS` explicitly per-call instead of it being the
// default every caller inherits. 30s comfortably exceeds the engine's own
// internal Binance client timeout (30s, `services/binance_testnet.py`) plus
// processing headroom, without holding a request open indefinitely.
const DEFAULT_TIMEOUT_MS = 30 * 1000
const LONG_JOB_TIMEOUT_MS = 60 * 60 * 1000

const engineClient = axios.create({
  baseURL: process.env.ENGINE_URL || 'http://engine:8000',
  timeout: DEFAULT_TIMEOUT_MS,
  headers: {
    'X-API-Key': process.env.ENGINE_API_KEY || '',
    'Content-Type': 'application/json',
  },
  httpAgent,
  httpsAgent,
})

engineClient.LONG_JOB_TIMEOUT_MS = LONG_JOB_TIMEOUT_MS

// Plan 2 Step 2.4 (SYS-6): thread the current request's correlation id onto
// every engine call so one Trade request's id is greppable in both server
// and engine logs. No-op outside a request context (e.g. background jobs).
engineClient.interceptors.request.use((config) => {
  const requestId = getRequestId()
  if (requestId) {
    config.headers['X-Request-Id'] = requestId
  }
  return config
})

module.exports = engineClient
