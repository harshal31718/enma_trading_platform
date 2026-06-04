const Settings = require('../models/Settings')
const ApiError = require('../utils/ApiError')

async function requireBinanceCredentials(req, res, next) {
  try {
    const settings = await Settings.findById('global')
    if (!settings?.binanceApiKey || !settings?.binanceApiSecret) {
      throw new ApiError(400, 'NO_CREDENTIALS', 'Binance API credentials are not configured')
    }
    req.binanceHeaders = {
      'X-Binance-API-Key': settings.binanceApiKey,
      'X-Binance-API-Secret': settings.binanceApiSecret,
    }
    next()
  } catch (err) {
    next(err)
  }
}

module.exports = requireBinanceCredentials
