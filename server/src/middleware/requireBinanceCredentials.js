const Settings = require('../models/Settings')
const { decrypt } = require('../utils/encryption')
const ApiError = require('../utils/ApiError')

async function requireBinanceCredentials(req, res, next) {
  try {
    const settings = await Settings.findOne({ userId: String(req.user._id) })
    const apiKey = settings?.encryptedApiKey ? decrypt(settings.encryptedApiKey) : ''
    const apiSecret = settings?.encryptedApiSecret ? decrypt(settings.encryptedApiSecret) : ''

    if (!apiKey || !apiSecret) {
      throw new ApiError(400, 'NO_CREDENTIALS', 'Binance API keys not configured. Add them in Settings.')
    }

    req.binanceHeaders = {
      'X-Binance-API-Key': apiKey,
      'X-Binance-API-Secret': apiSecret,
      'X-Binance-Mode': settings?.mode || 'testnet',
    }

    next()
  } catch (err) {
    next(err)
  }
}

module.exports = requireBinanceCredentials
