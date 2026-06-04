const express = require('express')
const router = express.Router()
const { handleEngineStats, handleAlgoPlaceOrder, handleAlgoClosePosition, handleAlgoSetLeverage, handleAlgoGetPosition } = require('../controllers/algo.controller')

// Called by Python engine to push session stat updates
router.patch('/algo/sessions/:id/stats', handleEngineStats)

// Called by Python engine to place real Binance orders (credentials held server-side)
router.post('/algo/sessions/:id/place-order', handleAlgoPlaceOrder)
router.post('/algo/sessions/:id/close-position', handleAlgoClosePosition)
router.post('/algo/sessions/:id/set-leverage', handleAlgoSetLeverage)
router.post('/algo/sessions/:id/get-position', handleAlgoGetPosition)

module.exports = router
