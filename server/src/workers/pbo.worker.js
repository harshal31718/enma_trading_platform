const { Worker } = require('bullmq')
const redis = require('../config/redis')
const engineClient = require('../services/engineClient')
const { subscribeToJob, unsubscribeFromJob } = require('../services/socketEmitter')
const { getIO } = require('../config/socket')
const LabResult = require('../models/LabResult')

// Plan 10 — PBO (Probability of Backtest Overfitting). Mirrors optimization.worker.js exactly —
// a PBO run is a full-range optimization pass plus in-memory CSCV combinatorics, genuinely long
// like walk-forward, so the same job/progress infra applies unchanged.
const worker = new Worker('pbo', async (job) => {
  const { labId, userId, config, configHash } = job.data

  subscribeToJob(labId, 'pbo')

  await LabResult.findOneAndUpdate({ labId }, { status: 'running' })

  try {
    await engineClient.post('/simulate/pbo', {
      labId,
      userId,
      config,
      configHash,
    }, { timeout: engineClient.LONG_JOB_TIMEOUT_MS })

    await LabResult.findOneAndUpdate({ labId }, { status: 'completed' })

    const io = getIO()
    io.to(`pbo:${labId}`).emit('pbo:complete', { labId })
  } catch (err) {
    const errMsg = err.response?.data?.detail || err.message

    await LabResult.findOneAndUpdate({ labId }, {
      status: 'failed',
      error: errMsg,
    })

    const io = getIO()
    io.to(`pbo:${labId}`).emit('pbo:error', { labId, error: errMsg })

    throw err
  } finally {
    unsubscribeFromJob(labId)
  }
}, { connection: redis })

worker.on('failed', (job, err) => {
  console.error(`[pbo.worker] job ${job?.id} failed:`, err.message)
})

module.exports = worker
