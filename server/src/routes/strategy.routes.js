const express = require('express')
const router = express.Router()
const { listStrategies, getStrategyCode, getStrategyParams } = require('../controllers/strategy.controller')

router.get('/', listStrategies)
router.get('/:id/code', getStrategyCode)
router.get('/:id/params', getStrategyParams)

module.exports = router
