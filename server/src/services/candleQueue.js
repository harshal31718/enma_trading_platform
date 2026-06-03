const { Queue } = require('bullmq')
const redis = require('../config/redis')

const candleQueue = new Queue('candles', { connection: redis })

module.exports = candleQueue
