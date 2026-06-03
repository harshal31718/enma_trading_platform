const express = require('express')
const router = express.Router()
const { getSymbols, getCached } = require('../controllers/candle.controller')

router.get('/symbols', getSymbols)
router.get('/cached', getCached)

module.exports = router
