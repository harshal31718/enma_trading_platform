const express = require('express')
const router = express.Router()
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
  cancelOrder,
  getKlines,
} = require('../controllers/trade.controller')

router.get('/settings/keys', getSettingsKeys)
router.post('/settings/keys', saveSettingsKeys)
router.post('/settings/verify', verifySettings)

router.get('/account', getAccountDetails)
router.get('/positions', getPositionRisk)
router.get('/open-orders', getOpenOrders)

router.post('/leverage', changeLeverage)
router.post('/margin-type', changeMarginType)

router.post('/order', placeOrder)
router.delete('/order', cancelOrder)

router.get('/klines', getKlines)

module.exports = router
