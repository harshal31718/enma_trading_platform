const Settings = require('../models/Settings')
const TradeOrder = require('../models/TradeOrder')
const TradeExecution = require('../models/TradeExecution')
const TradeTransaction = require('../models/TradeTransaction')
const engineClient = require('../services/engineClient')
const ApiResponse = require('../utils/ApiResponse')
const ApiError = require('../utils/ApiError')
const { isSymbolFree, getSymbolLock } = require('../services/symbolLock')

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

function handleEngineError(err, defaultMessage) {
  if (err instanceof ApiError) return err
  const detail = err.response?.data?.detail
  const message = typeof detail === 'string' ? detail : detail?.message || defaultMessage
  return new ApiError(err.response?.status || 500, 'ENGINE_ERROR', message)
}

async function upsertTradeOrder(orderDetails, fallback = {}) {
  await TradeOrder.findOneAndUpdate(
    { orderId: String(orderDetails.orderId) },
    {
      $set: {
        orderId: String(orderDetails.orderId),
        clientOrderId: orderDetails.clientOrderId || fallback.clientOrderId || '',
        symbol: fromBinanceSymbol(orderDetails.symbol) || fallback.symbol,
        status: orderDetails.status || 'NEW',
        price: String(orderDetails.price || fallback.price || '0'),
        avgPrice: String(orderDetails.avgPrice || '0'),
        origQty: String(orderDetails.origQty || fallback.quantity),
        executedQty: String(orderDetails.executedQty || '0'),
        side: orderDetails.side || fallback.side,
        type: orderDetails.type || fallback.type,
        timeInForce: orderDetails.timeInForce || 'GTC',
        stopPrice: String(orderDetails.stopPrice || fallback.stopPrice || '0'),
        time: orderDetails.updateTime ? new Date(orderDetails.updateTime) : new Date(),
        updateTime: orderDetails.updateTime ? new Date(orderDetails.updateTime) : new Date(),
        reduceOnly: orderDetails.reduceOnly || fallback.reduceOnly || false,
        postOnly: orderDetails.postOnly || fallback.postOnly || false,
        isAlgo: orderDetails.isAlgo || fallback.isAlgo || false,
      }
    },
    { upsert: true }
  )
}

async function getSettingsKeys(req, res, next) {
  try {
    const settings = await Settings.findById('global')

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

    let settings = await Settings.findById('global')
    if (!settings) {
      settings = new Settings({ _id: 'global' })
    }
    settings.paperTrading = paperTrading
    if (binanceApiKey) settings.binanceApiKey = binanceApiKey
    if (binanceApiSecret) settings.binanceApiSecret = binanceApiSecret
    await settings.save()

    res.json(ApiResponse.success({ saved: true }))
  } catch (err) {
    next(err)
  }
}

async function verifySettings(req, res, next) {
  try {
    const settings = await Settings.findById('global')
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

async function getAccountDetails(req, res, next) {
  try {
    const { data } = await engineClient.get('/trade/account', { headers: req.binanceHeaders })
    res.json(ApiResponse.success(data.data))
  } catch (err) {
    next(handleEngineError(err, 'Failed to fetch account'))
  }
}

async function getPositionRisk(req, res, next) {
  try {
    const { symbol } = req.query
    const params = symbol ? { symbol } : {}
    const { data } = await engineClient.get('/trade/positions', { headers: req.binanceHeaders, params })

    const allPositions = data.data || []
    const result = symbol
      ? allPositions
      : allPositions.filter(
          (p) => p.positionAmt !== '0' && p.positionAmt !== '0.0' && parseFloat(p.positionAmt) !== 0
        )

    res.json(ApiResponse.success(result))

    // Fire-and-forget: keep manual Redis locks in sync with live positions.
    // Only run on full (no symbol filter) polls — the client does this every 4000ms.
    if (!symbol) {
      _reconcileManualLocks(allPositions).catch(() => {})
    }
  } catch (err) {
    next(handleEngineError(err, 'Failed to fetch positions'))
  }
}

async function _reconcileManualLocks(allPositions) {
  const { lockSymbol, releaseSymbolLock, getSymbolLock, getAllLockedSymbols } = require('../services/symbolLock')

  const openSymbols = new Set()
  for (const pos of allPositions) {
    if (parseFloat(pos.positionAmt) !== 0) {
      const sym = fromBinanceSymbol(pos.symbol)
      openSymbols.add(sym)
      const existing = await getSymbolLock(sym)
      if (!existing) {
        await lockSymbol(sym, 'manual').catch(() => {})
      }
    }
  }

  // Release manual locks for positions that are now closed (never touch bot locks)
  const allLocked = await getAllLockedSymbols()
  for (const [sym, lock] of Object.entries(allLocked)) {
    if (lock.reason === 'manual' && !openSymbols.has(sym)) {
      await releaseSymbolLock(sym).catch(() => {})
    }
  }
}

async function getOpenOrders(req, res, next) {
  try {
    const { data } = await engineClient.get('/trade/open-orders', { headers: req.binanceHeaders })
    res.json(ApiResponse.success(data.data))
  } catch (err) {
    next(handleEngineError(err, 'Failed to fetch open orders'))
  }
}

async function changeLeverage(req, res, next) {
  try {
    const { symbol, leverage } = req.body
    if (!symbol || leverage == null) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'symbol and leverage are required')
    }
    const { data } = await engineClient.post('/trade/leverage', { symbol, leverage }, { headers: req.binanceHeaders })
    res.json(ApiResponse.success(data.data))
  } catch (err) {
    next(handleEngineError(err, 'Failed to update leverage'))
  }
}

async function changeMarginType(req, res, next) {
  try {
    const { symbol, marginType } = req.body
    if (!symbol || !marginType) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'symbol and marginType are required')
    }
    if (!['ISOLATED', 'CROSSED'].includes(marginType)) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'marginType must be ISOLATED or CROSSED')
    }
    const { data } = await engineClient.post('/trade/margin-type', { symbol, marginType }, { headers: req.binanceHeaders })
    res.json(ApiResponse.success(data.data))
  } catch (err) {
    next(handleEngineError(err, 'Failed to update margin type'))
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
    // Symbol lock check
    const symbolFree = await isSymbolFree(symbol)
    if (!symbolFree) {
      const lock = await getSymbolLock(symbol)
      return next(new ApiError(409, 'SYMBOL_LOCKED', `Symbol ${symbol} is locked by ${lock?.reason || 'an active position'}. Close it first.`))
    }
    const { data } = await engineClient.post(
      '/trade/order',
      { symbol, side, type, quantity, price },
      { headers: req.binanceHeaders }
    )
    const orderDetails = data.data
    try {
      await upsertTradeOrder(orderDetails, { symbol, side, type, quantity, price })
    } catch (dbErr) {
      console.error('Failed to save local order draft:', dbErr)
      throw new ApiError(500, 'DB_SYNC_ERROR', 'Order placed but local DB sync failed')
    }
    res.json(ApiResponse.success(data.data))
  } catch (err) {
    next(handleEngineError(err, 'Failed to place order'))
  }
}

async function closePosition(req, res, next) {
  try {
    const { symbol } = req.body
    if (!symbol) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'symbol is required')
    }
    const { data } = await engineClient.post('/trade/close-position', { symbol }, { headers: req.binanceHeaders })
    res.json(ApiResponse.success(data.data))
  } catch (err) {
    next(handleEngineError(err, 'Failed to close position'))
  }
}

const VALID_INTERVALS = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w', '1M']

async function getKlines(req, res, next) {
  try {
    const { symbol, interval } = req.query
    if (!VALID_INTERVALS.includes(interval)) {
      throw new ApiError(400, 'VALIDATION_ERROR', `interval must be one of: ${VALID_INTERVALS.join(', ')}`)
    }
    const parsedLimit = parseInt(req.query.limit, 10)
    const limit = (!isNaN(parsedLimit) && parsedLimit >= 1 && parsedLimit <= 1000) ? parsedLimit : 200
    const { data } = await engineClient.get('/trade/klines', {
      params: { symbol, interval, limit }
    })
    res.json(ApiResponse.success(data.data))
  } catch (err) {
    next(handleEngineError(err, 'Failed to fetch public klines'))
  }
}

async function cancelOrder(req, res, next) {
  try {
    const { symbol, orderId } = req.query
    if (!symbol || !orderId) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'symbol and orderId are required')
    }
    const { data } = await engineClient.delete('/trade/order', {
      headers: req.binanceHeaders,
      params: { symbol, orderId },
    })
    try {
      await TradeOrder.findOneAndUpdate(
        { orderId: String(orderId) },
        { $set: { status: 'CANCELED', updateTime: new Date() } }
      )
    } catch (dbErr) {
      console.error('Failed to update canceled order status:', dbErr)
      throw new ApiError(500, 'DB_SYNC_ERROR', 'Order cancelled but local DB sync failed')
    }
    res.json(ApiResponse.success(data.data))
  } catch (err) {
    next(handleEngineError(err, 'Failed to cancel order'))
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
    // Symbol lock check
    const symbolFree = await isSymbolFree(symbol)
    if (!symbolFree) {
      const lock = await getSymbolLock(symbol)
      return next(new ApiError(409, 'SYMBOL_LOCKED', `Symbol ${symbol} is locked by ${lock?.reason || 'an active position'}. Close it first.`))
    }
    const { data } = await engineClient.post(
      '/trade/order/oco_futures',
      { symbol, side: side.toUpperCase(), quantity, stopPrice, takeProfitPrice },
      { headers: req.binanceHeaders }
    )
    const ocoDetails = data.data
    if (ocoDetails?.orders && Array.isArray(ocoDetails.orders)) {
      try {
        for (const ord of ocoDetails.orders) {
          await upsertTradeOrder(ord, {
            symbol,
            quantity: String(quantity),
            side: side.toUpperCase() === 'BUY' ? 'SELL' : 'BUY',
            type: ord.type,
            stopPrice: String(ord.type === 'STOP_MARKET' ? stopPrice : takeProfitPrice),
            reduceOnly: true,
            isAlgo: true,
          })
        }
      } catch (dbErr) {
        console.error('Failed to save OCO order drafts:', dbErr)
        throw new ApiError(500, 'DB_SYNC_ERROR', 'Order placed but local DB sync failed')
      }
    }
    res.json(ApiResponse.success(data.data))
  } catch (err) {
    next(handleEngineError(err, 'Failed to place OCO order'))
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
    // Symbol lock check
    const symbolFree = await isSymbolFree(symbol)
    if (!symbolFree) {
      const lock = await getSymbolLock(symbol)
      return next(new ApiError(409, 'SYMBOL_LOCKED', `Symbol ${symbol} is locked by ${lock?.reason || 'an active position'}. Close it first.`))
    }
    const { data } = await engineClient.post(
      '/trade/order/with_tp_sl',
      { symbol, side: side.toUpperCase(), type: type.toUpperCase(), quantity, price, stopLoss, takeProfit },
      { headers: req.binanceHeaders }
    )
    const resData = data.data
    try {
      if (resData.entry) {
        await upsertTradeOrder(resData.entry, {
          symbol,
          price: String(price || '0'),
          quantity: String(quantity),
          side: side.toUpperCase(),
          type: type.toUpperCase(),
        })
      }
      if (resData.sl) {
        await upsertTradeOrder(resData.sl, {
          clientOrderId: resData.sl.clientOrderId,
          symbol,
          quantity: String(quantity),
          side: side.toUpperCase() === 'BUY' ? 'SELL' : 'BUY',
          type: 'STOP_MARKET',
          stopPrice: String(stopLoss),
          reduceOnly: true,
          isAlgo: true,
        })
      }
      if (resData.tp) {
        await upsertTradeOrder(resData.tp, {
          clientOrderId: resData.tp.clientOrderId,
          symbol,
          quantity: String(quantity),
          side: side.toUpperCase() === 'BUY' ? 'SELL' : 'BUY',
          type: 'TAKE_PROFIT_MARKET',
          stopPrice: String(takeProfit),
          reduceOnly: true,
          isAlgo: true,
        })
      }
    } catch (dbErr) {
      console.error('Failed to save order with TP/SL drafts:', dbErr)
      throw new ApiError(500, 'DB_SYNC_ERROR', 'Order placed but local DB sync failed')
    }
    res.json(ApiResponse.success(data.data))
  } catch (err) {
    next(handleEngineError(err, 'Failed to place order with TP/SL'))
  }
}

async function getOrderStatus(req, res, next) {
  try {
    const { symbol, orderId } = req.query
    if (!symbol || !orderId) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'symbol and orderId are required')
    }
    const { data } = await engineClient.get('/trade/order', {
      headers: req.binanceHeaders,
      params: { symbol, orderId },
    })
    res.json(ApiResponse.success(data.data))
  } catch (err) {
    next(handleEngineError(err, 'Failed to fetch order status'))
  }
}

async function cancelAllOrders(req, res, next) {
  try {
    const { symbol } = req.query
    if (!symbol) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'symbol is required')
    }
    const { data } = await engineClient.delete('/trade/all-orders', {
      headers: req.binanceHeaders,
      params: { symbol },
    })
    try {
      await TradeOrder.updateMany(
        { symbol, status: 'NEW' },
        { $set: { status: 'CANCELED', updateTime: new Date() } }
      )
    } catch (dbErr) {
      console.error('Failed to update all canceled orders status:', dbErr)
      throw new ApiError(500, 'DB_SYNC_ERROR', 'Orders cancelled but local DB sync failed')
    }
    res.json(ApiResponse.success(data.data))
  } catch (err) {
    next(handleEngineError(err, 'Failed to cancel all orders'))
  }
}

async function getTradeOrders(req, res, next) {
  try {
    const { symbol } = req.query
    if (!symbol) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'symbol query parameter is required')
    }

    let synced = true
    try {
      const { data } = await engineClient.get('/trade/history-orders', {
        headers: req.binanceHeaders,
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
      synced = false
    }

    const orders = await TradeOrder.find({ symbol }).sort({ time: -1 }).lean()
    res.json(ApiResponse.success({ orders, synced }))
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

    let synced = true
    try {
      const { data } = await engineClient.get('/trade/history-executions', {
        headers: req.binanceHeaders,
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
      synced = false
    }

    const executions = await TradeExecution.find({ symbol }).sort({ time: -1 }).lean()
    res.json(ApiResponse.success({ executions, synced }))
  } catch (err) {
    next(err)
  }
}

async function getTradeTransactions(req, res, next) {
  try {
    const { symbol } = req.query

    let synced = true
    try {
      const params = { limit: 100 }
      if (symbol) params.symbol = symbol
      const { data } = await engineClient.get('/trade/history-transactions', {
        headers: req.binanceHeaders,
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
      synced = false
    }

    const filter = symbol ? { symbol } : {}
    const transactions = await TradeTransaction.find(filter).sort({ time: -1 }).lean()
    res.json(ApiResponse.success({ transactions, synced }))
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
