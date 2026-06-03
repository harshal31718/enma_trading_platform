const Settings = require('../models/Settings')
const engineClient = require('../services/engineClient')
const ApiResponse = require('../utils/ApiResponse')
const ApiError = require('../utils/ApiError')

async function loadCredentialHeaders() {
  const settings = await Settings.findById('global').lean()
  if (!settings?.binanceApiKey || !settings?.binanceApiSecret) {
    throw new ApiError(400, 'NO_CREDENTIALS', 'Binance API credentials are not configured')
  }
  return {
    'X-Binance-API-Key': settings.binanceApiKey,
    'X-Binance-API-Secret': settings.binanceApiSecret,
  }
}

function maskKey(key) {
  if (!key || key.length < 8) return key
  return key.slice(0, 4) + '*'.repeat(key.length - 8) + key.slice(-4)
}

async function getSettingsKeys(req, res, next) {
  try {
    const settings = await Settings.findById('global').lean()

    if (!settings) {
      return res.json(ApiResponse.success({ paperTrading: true, binanceApiKey: '' }))
    }

    res.json(
      ApiResponse.success({
        paperTrading: settings.paperTrading,
        binanceApiKey: maskKey(settings.binanceApiKey),
      })
    )
  } catch (err) {
    next(err)
  }
}

async function saveSettingsKeys(req, res, next) {
  try {
    const { binanceApiKey, binanceApiSecret, paperTrading } = req.body

    if (typeof paperTrading !== 'boolean') {
      throw new ApiError(400, 'VALIDATION_ERROR', 'paperTrading must be a boolean')
    }

    // If keys are provided, verify them against Binance Testnet before saving
    if (binanceApiKey && binanceApiSecret) {
      try {
        await engineClient.post('/trade/verify', { binanceApiKey, binanceApiSecret })
      } catch (engineErr) {
        const detail = engineErr.response?.data?.detail
        const message =
          typeof detail === 'string'
            ? detail
            : detail?.message || 'Binance Testnet verification failed'
        throw new ApiError(400, 'VERIFICATION_FAILED', message)
      }
    }

    const updateFields = { paperTrading }
    if (binanceApiKey) updateFields.binanceApiKey = binanceApiKey
    if (binanceApiSecret) updateFields.binanceApiSecret = binanceApiSecret

    await Settings.findByIdAndUpdate(
      'global',
      { $set: updateFields },
      { upsert: true, new: true }
    )

    res.json(ApiResponse.success({ saved: true }))
  } catch (err) {
    next(err)
  }
}

async function getAccountDetails(req, res, next) {
  try {
    const credHeaders = await loadCredentialHeaders()
    const { data } = await engineClient.get('/trade/account', { headers: credHeaders })
    res.json(ApiResponse.success(data.data))
  } catch (err) {
    if (err instanceof ApiError) return next(err)
    const detail = err.response?.data?.detail
    const message = typeof detail === 'string' ? detail : detail?.message || 'Failed to fetch account'
    next(new ApiError(err.response?.status || 500, 'ENGINE_ERROR', message))
  }
}

async function getPositionRisk(req, res, next) {
  try {
    const credHeaders = await loadCredentialHeaders()
    const { symbol } = req.query
    const params = symbol ? { symbol } : {}
    const { data } = await engineClient.get('/trade/positions', { headers: credHeaders, params })

    // When a specific symbol is requested return the raw array (used for config reads).
    // Without a symbol filter out zero-size positions for the active-positions tab.
    const result = symbol
      ? (data.data || [])
      : (data.data || []).filter(
          (p) => p.positionAmt !== '0' && p.positionAmt !== '0.0' && parseFloat(p.positionAmt) !== 0
        )

    res.json(ApiResponse.success(result))
  } catch (err) {
    if (err instanceof ApiError) return next(err)
    const detail = err.response?.data?.detail
    const message = typeof detail === 'string' ? detail : detail?.message || 'Failed to fetch positions'
    next(new ApiError(err.response?.status || 500, 'ENGINE_ERROR', message))
  }
}

async function getOpenOrders(req, res, next) {
  try {
    const credHeaders = await loadCredentialHeaders()
    const { data } = await engineClient.get('/trade/open-orders', { headers: credHeaders })
    res.json(ApiResponse.success(data.data))
  } catch (err) {
    if (err instanceof ApiError) return next(err)
    const detail = err.response?.data?.detail
    const message = typeof detail === 'string' ? detail : detail?.message || 'Failed to fetch open orders'
    next(new ApiError(err.response?.status || 500, 'ENGINE_ERROR', message))
  }
}

async function changeLeverage(req, res, next) {
  try {
    const { symbol, leverage } = req.body
    if (!symbol || leverage == null) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'symbol and leverage are required')
    }
    const credHeaders = await loadCredentialHeaders()
    const { data } = await engineClient.post('/trade/leverage', { symbol, leverage }, { headers: credHeaders })
    res.json(ApiResponse.success(data.data))
  } catch (err) {
    if (err instanceof ApiError) return next(err)
    const detail = err.response?.data?.detail
    const message = typeof detail === 'string' ? detail : detail?.message || 'Failed to update leverage'
    next(new ApiError(err.response?.status || 500, 'ENGINE_ERROR', message))
  }
}

async function changeMarginType(req, res, next) {
  try {
    const { symbol, marginType } = req.body
    if (!symbol || !marginType) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'symbol and marginType are required')
    }
    const credHeaders = await loadCredentialHeaders()
    const { data } = await engineClient.post('/trade/margin-type', { symbol, marginType }, { headers: credHeaders })
    res.json(ApiResponse.success(data.data))
  } catch (err) {
    if (err instanceof ApiError) return next(err)
    const detail = err.response?.data?.detail
    const message = typeof detail === 'string' ? detail : detail?.message || 'Failed to update margin type'
    next(new ApiError(err.response?.status || 500, 'ENGINE_ERROR', message))
  }
}

async function placeOrder(req, res, next) {
  try {
    const { symbol, side, type, quantity, price } = req.body
    if (!symbol || !side || !type || quantity == null) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'symbol, side, type, and quantity are required')
    }
    if (typeof quantity !== 'number' || quantity <= 0) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'quantity must be a positive number')
    }
    const credHeaders = await loadCredentialHeaders()
    const { data } = await engineClient.post(
      '/trade/order',
      { symbol, side, type, quantity, price },
      { headers: credHeaders }
    )
    res.json(ApiResponse.success(data.data))
  } catch (err) {
    if (err instanceof ApiError) return next(err)
    const detail = err.response?.data?.detail
    const message = typeof detail === 'string' ? detail : detail?.message || 'Failed to place order'
    next(new ApiError(err.response?.status || 500, 'ENGINE_ERROR', message))
  }
}

async function closePosition(req, res, next) {
  try {
    const { symbol } = req.body
    if (!symbol) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'symbol is required')
    }
    const credHeaders = await loadCredentialHeaders()
    const { data } = await engineClient.post('/trade/close-position', { symbol }, { headers: credHeaders })
    res.json(ApiResponse.success(data.data))
  } catch (err) {
    if (err instanceof ApiError) return next(err)
    const detail = err.response?.data?.detail
    const message = typeof detail === 'string' ? detail : detail?.message || 'Failed to close position'
    next(new ApiError(err.response?.status || 500, 'ENGINE_ERROR', message))
  }
}

async function verifySettings(req, res, next) {
  try {
    const settings = await Settings.findById('global').lean()
    if (!settings?.binanceApiKey || !settings?.binanceApiSecret) {
      throw new ApiError(400, 'NO_CREDENTIALS', 'Binance API credentials are not configured')
    }
    try {
      await engineClient.post('/trade/verify', {
        binanceApiKey: settings.binanceApiKey,
        binanceApiSecret: settings.binanceApiSecret,
      })
    } catch (engineErr) {
      const detail = engineErr.response?.data?.detail
      const message =
        typeof detail === 'string'
          ? detail
          : detail?.message || 'Binance Testnet verification failed'
      throw new ApiError(400, 'VERIFICATION_FAILED', message)
    }
    res.json(ApiResponse.success({ verified: true }))
  } catch (err) {
    next(err)
  }
}

async function getKlines(req, res, next) {
  try {
    const { symbol, interval, limit } = req.query
    const { data } = await engineClient.get('/trade/klines', {
      params: { symbol, interval, limit }
    })
    res.json(ApiResponse.success(data.data))
  } catch (err) {
    if (err instanceof ApiError) return next(err)
    const detail = err.response?.data?.detail
    const message = typeof detail === 'string' ? detail : detail?.message || 'Failed to fetch public klines'
    next(new ApiError(err.response?.status || 500, 'ENGINE_ERROR', message))
  }
}

async function cancelOrder(req, res, next) {
  try {
    const { symbol, orderId } = req.query
    if (!symbol || !orderId) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'symbol and orderId are required')
    }
    const credHeaders = await loadCredentialHeaders()
    const { data } = await engineClient.delete('/trade/order', {
      headers: credHeaders,
      params: { symbol, orderId },
    })
    res.json(ApiResponse.success(data.data))
  } catch (err) {
    if (err instanceof ApiError) return next(err)
    const detail = err.response?.data?.detail
    const message = typeof detail === 'string' ? detail : detail?.message || 'Failed to cancel order'
    next(new ApiError(err.response?.status || 500, 'ENGINE_ERROR', message))
  }
}

module.exports = {
  getSettingsKeys,
  saveSettingsKeys,
  verifySettings,
  getAccountDetails,
  getPositionRisk,
  getOpenOrders,
  changeLeverage,
  changeMarginType,
  placeOrder,
  closePosition,
  cancelOrder,
  getKlines,
}
