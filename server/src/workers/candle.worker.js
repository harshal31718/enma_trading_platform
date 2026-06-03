const { Worker } = require('bullmq')
const redis = require('../config/redis')
const engineClient = require('../services/engineClient')
const { subscribeToJob } = require('../services/socketEmitter')
const { getIO } = require('../config/socket')
const CandleImport = require('../models/CandleImport')

const worker = new Worker('candles', async (job) => {
  const { jobId, exchange, symbol, timeframe, startDate, endDate } = job.data

  subscribeToJob(jobId)

  await CandleImport.findOneAndUpdate({ jobId }, { status: 'running' })

  try {
    const response = await engineClient.post('/candles/import', {
      jobId, exchange, symbol, timeframe, startDate, endDate,
    })

    const { candlesImported } = response.data.data

    await CandleImport.findOneAndUpdate({ jobId }, {
      status: 'completed',
      candleCount: candlesImported,
      importedAt: new Date(),
    })

    const io = getIO()
    io.to(`candles:${jobId}`).emit('candles:complete', {
      jobId,
      candlesImported,
      symbol,
      timeframe,
      exchange,
    })
  } catch (err) {
    await CandleImport.findOneAndUpdate({ jobId }, {
      status: 'failed',
      error: err.message,
    })

    const io = getIO()
    io.to(`candles:${jobId}`).emit('candles:error', {
      jobId,
      error: err.message,
    })

    throw err
  }
}, { connection: redis })

worker.on('failed', (job, err) => {
  console.error(`[candle.worker] job ${job?.id} failed:`, err.message)
})

module.exports = worker
