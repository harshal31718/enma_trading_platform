const ApiError = require('../utils/ApiError')

async function requireBinanceCredentials(req, res, next) {
  try {
    // Always testnet — mainnet is not yet available
    const apiKey = process.env.BINANCE_TESTNET_API_KEY
    const apiSecret = process.env.BINANCE_TESTNET_SECRET

    if (!apiKey || !apiSecret) {
      throw new ApiError(
        400,
        'NO_CREDENTIALS',
        'Binance Testnet API credentials are not configured. Set BINANCE_TESTNET_API_KEY and BINANCE_TESTNET_SECRET in the environment.'
      )
    }

    req.binanceHeaders = {
      'X-Binance-API-Key': apiKey,
      'X-Binance-API-Secret': apiSecret,
      'X-Binance-Mode': 'testnet',
    }

    next()
  } catch (err) {
    next(err)
  }
}

module.exports = requireBinanceCredentials
