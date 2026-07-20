const { Worker } = require('bullmq')
const redis = require('../config/redis')
const engineClient = require('../services/engineClient')
const { subscribeToJob, unsubscribeFromJob } = require('../services/socketEmitter')
const { getIO } = require('../config/socket')
const BacktestResult = require('../models/BacktestResult')

const worker = new Worker('backtest', async (job) => {
  const {
    jobId,
    userId,
    strategyFile,
    exchange,
    symbol,
    timeframe,
    startDate,
    endDate,
    capital,
    leverage,
    feeRate,
    slippagePct,
    fundingEnabled,
    fundingRate,
    riskParams,
    alphaParams,
  } = job.data

  subscribeToJob(jobId, 'backtest')

  await BacktestResult.findOneAndUpdate({ jobId }, { status: 'running' })

  try {
    await engineClient.post('/backtest/run', {
      jobId,
      userId,
      strategyFile,
      exchange,
      symbol,
      timeframe,
      startDate,
      endDate,
      capital,
      leverage,
      feeRate,
      slippagePct,
      fundingEnabled,
      fundingRate,
      riskParams,
      alphaParams,
    }, { timeout: engineClient.LONG_JOB_TIMEOUT_MS })

    // Engine wrote the full result to MongoDB — only update status here
    await BacktestResult.findOneAndUpdate({ jobId }, { status: 'completed' })

    const io = getIO()
    io.to(`backtest:${jobId}`).emit('backtest:complete', {
      jobId,
      resultId: jobId,
    })
  } catch (err) {
    const errMsg = err.response?.data?.detail || err.message
    const isCancelled = errMsg === 'JOB_CANCELLED'

    await BacktestResult.findOneAndUpdate({ jobId }, {
      status: isCancelled ? 'cancelled' : 'failed',
      error: isCancelled ? 'Cancelled by user' : errMsg,
    })

    const io = getIO()
    if (isCancelled) {
      io.to(`backtest:${jobId}`).emit('backtest:cancelled', { jobId })
    } else {
      io.to(`backtest:${jobId}`).emit('backtest:error', { jobId, error: errMsg })
    }

    throw err
  } finally {
    unsubscribeFromJob(jobId)
  }
}, { connection: redis })

worker.on('failed', (job, err) => {
  console.error(`[backtest.worker] job ${job?.id} failed:`, err.message)
})

module.exports = worker
