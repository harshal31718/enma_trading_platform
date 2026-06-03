const express = require('express')
const router = express.Router()
const {
  runBacktest,
  getBacktest,
  listBacktests,
  cancelBacktest,
  getBacktestTrades,
} = require('../controllers/backtest.controller')

router.post('/', runBacktest)
router.get('/', listBacktests)
router.get('/:id', getBacktest)
router.get('/:id/trades', getBacktestTrades)
router.post('/:id/cancel', cancelBacktest)

module.exports = router
