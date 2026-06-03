const Settings = require('../models/Settings')
const TradeOrder = require('../models/TradeOrder')
const TradeExecution = require('../models/TradeExecution')
const TradeTransaction = require('../models/TradeTransaction')
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

function fromBinanceSymbol(sym) {
  if (!sym) return ''
  if (sym.endsWith('USDT')) {
    return sym.slice(0, -4) + '-' + sym.slice(-4)
  }
  return sym
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
    const orderDetails = data.data
    try {
      await TradeOrder.findOneAndUpdate(
        { orderId: String(orderDetails.orderId) },
        {
          $set: {
            orderId: String(orderDetails.orderId),
            clientOrderId: orderDetails.clientOrderId,
            symbol: fromBinanceSymbol(orderDetails.symbol) || symbol,
            status: orderDetails.status || 'NEW',
            price: String(orderDetails.price || price || '0'),
            avgPrice: String(orderDetails.avgPrice || '0'),
            origQty: String(orderDetails.origQty || quantity),
            executedQty: String(orderDetails.executedQty || '0'),
            side: orderDetails.side || side,
            type: orderDetails.type || type,
            timeInForce: orderDetails.timeInForce || 'GTC',
            stopPrice: String(orderDetails.stopPrice || '0'),
            time: orderDetails.updateTime ? new Date(orderDetails.updateTime) : new Date(),
            updateTime: orderDetails.updateTime ? new Date(orderDetails.updateTime) : new Date(),
            reduceOnly: orderDetails.reduceOnly || false,
            postOnly: orderDetails.postOnly || false,
            isAlgo: false,
          }
        },
        { upsert: true }
      )
    } catch (dbErr) {
      console.error('Failed to save local order draft:', dbErr)
    }
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
    try {
      await TradeOrder.findOneAndUpdate(
        { orderId: String(orderId) },
        { $set: { status: 'CANCELED', updateTime: new Date() } }
      )
    } catch (dbErr) {
      console.error('Failed to update canceled order status:', dbErr)
    }
    res.json(ApiResponse.success(data.data))
  } catch (err) {
    if (err instanceof ApiError) return next(err)
    const detail = err.response?.data?.detail
    const message = typeof detail === 'string' ? detail : detail?.message || 'Failed to cancel order'
    next(new ApiError(err.response?.status || 500, 'ENGINE_ERROR', message))
  }
}

async function placeOCOOrder(req, res, next) {
  try {
    const { symbol, side, quantity, stopPrice, takeProfitPrice } = req.body
    if (!symbol || !side || quantity == null) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'symbol, side, and quantity are required')
    }
    if (stopPrice == null && takeProfitPrice == null) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'At least one of stopPrice or takeProfitPrice is required')
    }
    if (!['BUY', 'SELL'].includes(side.toUpperCase())) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'side must be BUY or SELL')
    }
    if (typeof quantity !== 'number' || quantity <= 0) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'quantity must be a positive number')
    }
    const credHeaders = await loadCredentialHeaders()
    const { data } = await engineClient.post(
      '/trade/order/oco_futures',
      { symbol, side: side.toUpperCase(), quantity, stopPrice, takeProfitPrice },
      { headers: credHeaders }
    )
    const ocoDetails = data.data
    if (ocoDetails?.orders && Array.isArray(ocoDetails.orders)) {
      try {
        for (const ord of ocoDetails.orders) {
          await TradeOrder.findOneAndUpdate(
            { orderId: String(ord.orderId) },
            {
              $set: {
                orderId: String(ord.orderId),
                clientOrderId: ord.clientOrderId,
                symbol: symbol,
                status: 'NEW',
                price: '0.00',
                avgPrice: '0.00',
                origQty: String(quantity),
                executedQty: '0.00',
                side: side.toUpperCase() === 'BUY' ? 'SELL' : 'BUY',
                type: ord.type,
                timeInForce: 'GTC',
                stopPrice: String(ord.type === 'STOP_MARKET' ? stopPrice : takeProfitPrice),
                time: new Date(),
                updateTime: new Date(),
                reduceOnly: true,
                postOnly: false,
                isAlgo: true,
              }
            },
            { upsert: true }
          )
        }
      } catch (dbErr) {
        console.error('Failed to save OCO order drafts:', dbErr)
      }
    }
    res.json(ApiResponse.success(data.data))
  } catch (err) {
    if (err instanceof ApiError) return next(err)
    const detail = err.response?.data?.detail
    const message = typeof detail === 'string' ? detail : detail?.message || 'Failed to place OCO order'
    next(new ApiError(err.response?.status || 500, 'ENGINE_ERROR', message))
  }
}

async function placeOrderWithTpSl(req, res, next) {
  try {
    const { symbol, side, type, quantity, price, stopLoss, takeProfit } = req.body
    if (!symbol || !side || !type || quantity == null) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'symbol, side, type, and quantity are required')
    }
    if (!['BUY', 'SELL'].includes(side.toUpperCase())) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'side must be BUY or SELL')
    }
    if (typeof quantity !== 'number' || quantity <= 0) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'quantity must be a positive number')
    }
    const credHeaders = await loadCredentialHeaders()
    const { data } = await engineClient.post(
      '/trade/order/with_tp_sl',
      { symbol, side: side.toUpperCase(), type: type.toUpperCase(), quantity, price, stopLoss, takeProfit },
      { headers: credHeaders }
    )
    const resData = data.data
    try {
      if (resData.entry) {
        await TradeOrder.findOneAndUpdate(
          { orderId: String(resData.entry.orderId) },
          {
            $set: {
              orderId: String(resData.entry.orderId),
              clientOrderId: '',
              symbol: symbol,
              status: 'NEW',
              price: String(price || '0'),
              avgPrice: '0.00',
              origQty: String(quantity),
              executedQty: '0.00',
              side: side.toUpperCase(),
              type: type.toUpperCase(),
              timeInForce: 'GTC',
              stopPrice: '0.00',
              time: new Date(),
              updateTime: new Date(),
              reduceOnly: false,
              postOnly: false,
              isAlgo: false,
            }
          },
          { upsert: true }
        )
      }
      if (resData.sl) {
        await TradeOrder.findOneAndUpdate(
          { orderId: String(resData.sl.orderId) },
          {
            $set: {
              orderId: String(resData.sl.orderId),
              clientOrderId: resData.sl.clientOrderId,
              symbol: symbol,
              status: 'NEW',
              price: '0.00',
              avgPrice: '0.00',
              origQty: String(quantity),
              executedQty: '0.00',
              side: side.toUpperCase() === 'BUY' ? 'SELL' : 'BUY',
              type: 'STOP_MARKET',
              timeInForce: 'GTC',
              stopPrice: String(stopLoss),
              time: new Date(),
              updateTime: new Date(),
              reduceOnly: true,
              postOnly: false,
              isAlgo: true,
            }
          },
          { upsert: true }
        )
      }
      if (resData.tp) {
        await TradeOrder.findOneAndUpdate(
          { orderId: String(resData.tp.orderId) },
          {
            $set: {
              orderId: String(resData.tp.orderId),
              clientOrderId: resData.tp.clientOrderId,
              symbol: symbol,
              status: 'NEW',
              price: '0.00',
              avgPrice: '0.00',
              origQty: String(quantity),
              executedQty: '0.00',
              side: side.toUpperCase() === 'BUY' ? 'SELL' : 'BUY',
              type: 'TAKE_PROFIT_MARKET',
              timeInForce: 'GTC',
              stopPrice: String(takeProfit),
              time: new Date(),
              updateTime: new Date(),
              reduceOnly: true,
              postOnly: false,
              isAlgo: true,
            }
          },
          { upsert: true }
        )
      }
    } catch (dbErr) {
      console.error('Failed to save order with TP/SL drafts:', dbErr)
    }
    res.json(ApiResponse.success(data.data))
  } catch (err) {
    if (err instanceof ApiError) return next(err)
    const detail = err.response?.data?.detail
    const message = typeof detail === 'string' ? detail : detail?.message || 'Failed to place order with TP/SL'
    next(new ApiError(err.response?.status || 500, 'ENGINE_ERROR', message))
  }
}

async function getOrderStatus(req, res, next) {
  try {
    const { symbol, orderId } = req.query
    if (!symbol || !orderId) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'symbol and orderId are required')
    }
    const credHeaders = await loadCredentialHeaders()
    const { data } = await engineClient.get('/trade/order', {
      headers: credHeaders,
      params: { symbol, orderId },
    })
    res.json(ApiResponse.success(data.data))
  } catch (err) {
    if (err instanceof ApiError) return next(err)
    const detail = err.response?.data?.detail
    const message = typeof detail === 'string' ? detail : detail?.message || 'Failed to fetch order status'
    next(new ApiError(err.response?.status || 500, 'ENGINE_ERROR', message))
  }
}

async function cancelAllOrders(req, res, next) {
  try {
    const { symbol } = req.query
    if (!symbol) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'symbol is required')
    }
    const credHeaders = await loadCredentialHeaders()
    const { data } = await engineClient.delete('/trade/all-orders', {
      headers: credHeaders,
      params: { symbol },
    })
    try {
      await TradeOrder.updateMany(
        { symbol, status: 'NEW' },
        { $set: { status: 'CANCELED', updateTime: new Date() } }
      )
    } catch (dbErr) {
      console.error('Failed to update all canceled orders status:', dbErr)
    }
    res.json(ApiResponse.success(data.data))
  } catch (err) {
    if (err instanceof ApiError) return next(err)
    const detail = err.response?.data?.detail
    const message = typeof detail === 'string' ? detail : detail?.message || 'Failed to cancel all orders'
    next(new ApiError(err.response?.status || 500, 'ENGINE_ERROR', message))
  }
}

async function getTradeOrders(req, res, next) {
  try {
    const { symbol } = req.query
    if (!symbol) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'symbol query parameter is required')
    }
    const credHeaders = await loadCredentialHeaders()

    try {
      const { data } = await engineClient.get('/trade/history-orders', {
        headers: credHeaders,
        params: { symbol, limit: 100 },
      })

      if (data?.data && Array.isArray(data.data)) {
        const ops = data.data.map(order => ({
          updateOne: {
            filter: { orderId: order.orderId },
            update: {
              $set: {
                ...order,
                time: new Date(order.time),
                updateTime: order.updateTime ? new Date(order.updateTime) : null,
              }
            },
            upsert: true,
          }
        }))
        if (ops.length > 0) {
          await TradeOrder.bulkWrite(ops)
        }
      }
    } catch (engineErr) {
      console.error('Failed to sync trade orders from engine:', engineErr.message)
    }

    const orders = await TradeOrder.find({ symbol }).sort({ time: -1 }).lean()
    res.json(ApiResponse.success(orders))
  } catch (err) {
    next(err)
  }
}

async function getTradeExecutions(req, res, next) {
  try {
    const { symbol } = req.query
    if (!symbol) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'symbol query parameter is required')
    }
    const credHeaders = await loadCredentialHeaders()

    try {
      const { data } = await engineClient.get('/trade/history-executions', {
        headers: credHeaders,
        params: { symbol, limit: 100 },
      })

      if (data?.data && Array.isArray(data.data)) {
        const ops = data.data.map(exec => ({
          updateOne: {
            filter: { id: exec.id },
            update: {
              $set: {
                ...exec,
                time: new Date(exec.time),
              }
            },
            upsert: true,
          }
        }))
        if (ops.length > 0) {
          await TradeExecution.bulkWrite(ops)
        }
      }
    } catch (engineErr) {
      console.error('Failed to sync executions from engine:', engineErr.message)
    }

    const executions = await TradeExecution.find({ symbol }).sort({ time: -1 }).lean()
    res.json(ApiResponse.success(executions))
  } catch (err) {
    next(err)
  }
}

async function getTradeTransactions(req, res, next) {
  try {
    const { symbol } = req.query
    const credHeaders = await loadCredentialHeaders()

    try {
      const params = { limit: 100 }
      if (symbol) params.symbol = symbol
      const { data } = await engineClient.get('/trade/history-transactions', {
        headers: credHeaders,
        params,
      })

      if (data?.data && Array.isArray(data.data)) {
        const ops = data.data.map(tx => ({
          updateOne: {
            filter: { tranId: tx.tranId },
            update: {
              $set: {
                ...tx,
                time: new Date(tx.time),
              }
            },
            upsert: true,
          }
        }))
        if (ops.length > 0) {
          await TradeTransaction.bulkWrite(ops)
        }
      }
    } catch (engineErr) {
      console.error('Failed to sync transactions from engine:', engineErr.message)
    }

    const filter = symbol ? { symbol } : {}
    const transactions = await TradeTransaction.find(filter).sort({ time: -1 }).lean()
    res.json(ApiResponse.success(transactions))
  } catch (err) {
    next(err)
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
  placeOCOOrder,
  placeOrderWithTpSl,
  getOrderStatus,
  cancelAllOrders,
  getTradeOrders,
  getTradeExecutions,
  getTradeTransactions,
}
