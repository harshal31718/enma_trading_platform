const express = require('express')
const router = express.Router()
const requireBinanceCredentials = require('../middleware/requireBinanceCredentials')
const {
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
} = require('../controllers/trade.controller')

// Public routes — no credentials required
router.get('/settings/keys', getSettingsKeys)
router.post('/settings/keys', saveSettingsKeys)
router.post('/settings/verify', verifySettings)
router.get('/klines', getKlines)

// All routes below require valid Binance credentials
router.use(requireBinanceCredentials)

router.get('/account', getAccountDetails)
router.get('/positions', getPositionRisk)
router.get('/open-orders', getOpenOrders)

router.post('/leverage', changeLeverage)
router.post('/margin-type', changeMarginType)

// Specific /order sub-paths must be registered before the generic /order route
router.get('/order/history', getTradeOrders)
router.post('/order/oco_futures', placeOCOOrder)
router.post('/order/with_tp_sl', placeOrderWithTpSl)
router.post('/order', placeOrder)
router.post('/order/close', closePosition)
router.get('/order', getOrderStatus)
router.delete('/order', cancelOrder)
router.delete('/all-orders', cancelAllOrders)

router.get('/executions/history', getTradeExecutions)
router.get('/transactions/history', getTradeTransactions)

module.exports = router
