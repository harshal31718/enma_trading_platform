const { Worker } = require('bullmq')
const redis = require('../config/redis')
const engineClient = require('../services/engineClient')
const { subscribeToJob, unsubscribeFromJob } = require('../services/socketEmitter')
const { getIO } = require('../config/socket')
const LabResult = require('../models/LabResult')

const worker = new Worker('simulation', async (job) => {
  const { simId, sourceJobId, userId, config, configHash } = job.data

  subscribeToJob(simId, 'simulation')

  await LabResult.findOneAndUpdate({ labId: simId }, { status: 'running' })

  try {
    await engineClient.post('/simulate/monte-carlo', {
      simId,
      sourceJobId,
      userId,
      config,
      configHash,
    }, { timeout: engineClient.LONG_JOB_TIMEOUT_MS })

    // Engine wrote the full results doc to MongoDB — only update status here
    // (mirrors backtest.worker.js's redundant-but-harmless status write).
    await LabResult.findOneAndUpdate({ labId: simId }, { status: 'completed' })

    const io = getIO()
    io.to(`simulation:${simId}`).emit('simulation:complete', { simId, labId: simId })
  } catch (err) {
    const errMsg = err.response?.data?.detail || err.message

    await LabResult.findOneAndUpdate({ labId: simId }, {
      status: 'failed',
      error: errMsg,
    })

    const io = getIO()
    io.to(`simulation:${simId}`).emit('simulation:error', { simId, error: errMsg })

    throw err
  } finally {
    unsubscribeFromJob(simId)
  }
}, { connection: redis })

worker.on('failed', (job, err) => {
  console.error(`[simulation.worker] job ${job?.id} failed:`, err.message)
})

module.exports = worker
