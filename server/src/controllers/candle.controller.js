const { v4: uuidv4 } = require('uuid')
const candleQueue = require('../services/candleQueue')
const engineClient = require('../services/engineClient')
const CandleImport = require('../models/CandleImport')
const ApiResponse = require('../utils/ApiResponse')
const ApiError = require('../utils/ApiError')

async function importCandles(req, res, next) {
  try {
    const { exchange, symbol, timeframe, startDate, endDate } = req.body

    if (!exchange || !symbol || !timeframe || !startDate || !endDate) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'exchange, symbol, timeframe, startDate, endDate are required')
    }

    const jobId = uuidv4()

    await CandleImport.create({
      jobId, exchange, symbol, timeframe, startDate, endDate, status: 'queued',
    })

    await candleQueue.add('import', {
      jobId, exchange, symbol, timeframe, startDate, endDate,
    }, { jobId })

    res.status(202).json(ApiResponse.success({ jobId, status: 'queued' }))
  } catch (err) {
    next(err)
  }
}

async function getSymbols(req, res, next) {
  try {
    const response = await engineClient.get('/candles/symbols')
    res.json(ApiResponse.success(response.data.data))
  } catch (err) {
    next(new ApiError(503, 'ENGINE_UNAVAILABLE', 'Could not fetch symbols from engine'))
  }
}

async function getAvailable(req, res, next) {
  try {
    const imports = await CandleImport.find({ status: 'completed' })
      .sort({ importedAt: -1 })
      .limit(100)
      .lean()
    res.json(ApiResponse.success({ imports }))
  } catch (err) {
    next(err)
  }
}

module.exports = { importCandles, getSymbols, getAvailable }
