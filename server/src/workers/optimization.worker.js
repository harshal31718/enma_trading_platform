const { Worker } = require('bullmq')
const redis = require('../config/redis')
const engineClient = require('../services/engineClient')
const { subscribeToJob, unsubscribeFromJob } = require('../services/socketEmitter')
const { getIO } = require('../config/socket')
const LabResult = require('../models/LabResult')

// Plan 10 Phase 3a — mirrors simulation.worker.js exactly. Unlike Monte Carlo
// (sub-second, no sourceJobId dependency issue), a walk-forward run is
// genuinely long (n_folds x grid-combo backtests) — the same job/progress
// infra applies unchanged, just a longer-running job under it.
const worker = new Worker('optimization', async (job) => {
  const { labId, userId, config, configHash } = job.data

  subscribeToJob(labId, 'optimization')

  await LabResult.findOneAndUpdate({ labId }, { status: 'running' })

  try {
    await engineClient.post('/simulate/optimize', {
      labId,
      userId,
      config,
      configHash,
    })

    // Engine wrote the full results doc to MongoDB — only update status here
    // (mirrors backtest.worker.js / simulation.worker.js's redundant-but-harmless
    // status double-write).
    await LabResult.findOneAndUpdate({ labId }, { status: 'completed' })

    const io = getIO()
    io.to(`optimization:${labId}`).emit('optimization:complete', { labId })
  } catch (err) {
    const errMsg = err.response?.data?.detail || err.message

    await LabResult.findOneAndUpdate({ labId }, {
      status: 'failed',
      error: errMsg,
    })

    const io = getIO()
    io.to(`optimization:${labId}`).emit('optimization:error', { labId, error: errMsg })

    throw err
  } finally {
    unsubscribeFromJob(labId)
  }
}, { connection: redis })

worker.on('failed', (job, err) => {
  console.error(`[optimization.worker] job ${job?.id} failed:`, err.message)
})

module.exports = worker
