// Plan 2 Step 2.4 (SYS-6): structured logging via pino, replacing morgan('dev').
// Redacts anything that could leak a session or exchange credential into logs.
const pino = require('pino')

const logger = pino({
  level: process.env.LOG_LEVEL || 'info',
  redact: {
    paths: [
      'req.headers.cookie',
      'req.headers.authorization',
      'req.headers["x-binance-api-key"]',
      'req.headers["x-binance-api-secret"]',
      'res.headers["set-cookie"]',
    ],
    censor: '[REDACTED]',
  },
})

module.exports = logger
