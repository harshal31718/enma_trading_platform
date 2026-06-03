const { Queue } = require('bullmq')
const redis = require('../config/redis')

const backtestQueue = new Queue('backtest', { connection: redis })

module.exports = backtestQueue
