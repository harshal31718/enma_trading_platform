const http = require('http')
const https = require('https')
const axios = require('axios')

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

module.exports = engineClient
