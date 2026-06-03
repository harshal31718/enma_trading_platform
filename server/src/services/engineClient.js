const axios = require('axios')

const engineClient = axios.create({
  baseURL: process.env.ENGINE_URL || 'http://engine:8000',
  timeout: 60 * 60 * 1000, // 1 hour — candle imports can take a long time
  headers: {
    'X-API-Key': process.env.ENGINE_API_KEY || '',
    'Content-Type': 'application/json',
  },
})

module.exports = engineClient
