const engineClient = require('../services/engineClient')
const ApiResponse = require('../utils/ApiResponse')
const ApiError = require('../utils/ApiError')

async function getSymbols(req, res, next) {
  try {
    const response = await engineClient.get('/candles/symbols')
    res.json(ApiResponse.success(response.data.data))
  } catch (err) {
    next(new ApiError(503, 'ENGINE_UNAVAILABLE', 'Could not fetch symbols from engine'))
  }
}

async function getCached(req, res, next) {
  try {
    const response = await engineClient.get('/candles/cached')
    res.json(ApiResponse.success(response.data.data))
  } catch (err) {
    next(new ApiError(503, 'ENGINE_UNAVAILABLE', 'Could not fetch cached candle summary from engine'))
  }
}

module.exports = { getSymbols, getCached }
