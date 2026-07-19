const { Queue } = require('bullmq')
const redis = require('../config/redis')

// Plan 10 Phase 3a — mirrors simulationQueue.js exactly (same BullMQ/worker
// pattern as backtestQueue before it).
const optimizationQueue = new Queue('optimization', { connection: redis })

module.exports = optimizationQueue
