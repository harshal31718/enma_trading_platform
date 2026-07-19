const { Queue } = require('bullmq')
const redis = require('../config/redis')

const simulationQueue = new Queue('simulation', { connection: redis })

module.exports = simulationQueue
