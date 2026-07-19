const { Queue } = require('bullmq')
const redis = require('../config/redis')

// Plan 10 — PBO (Probability of Backtest Overfitting). Mirrors optimizationQueue.js exactly.
const pboQueue = new Queue('pbo', { connection: redis })

module.exports = pboQueue
