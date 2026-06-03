const express = require('express')
const router = express.Router()
const { importCandles, getSymbols, getAvailable } = require('../controllers/candle.controller')

router.get('/symbols', getSymbols)
router.get('/available', getAvailable)
router.post('/import', importCandles)

module.exports = router
