const http = require('http')
const https = require('https')
const axios = require('axios')
const { getRequestId } = require('../config/requestContext')

const httpAgent = new http.Agent({ keepAlive: true })
const httpsAgent = new https.Agent({ keepAlive: true })

const engineClient = axios.create({
  baseURL: process.env.ENGINE_URL || 'http://engine:8000',
  timeout: 60 * 60 * 1000, // 1 hour — candle imports can take a long time
  headers: {
    'X-API-Key': process.env.ENGINE_API_KEY || '',
    'Content-Type': 'application/json',
  },
  httpAgent,
  httpsAgent,
})

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
