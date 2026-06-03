const express = require('express')
const router = express.Router()
const { listStrategies, getStrategyCode } = require('../controllers/strategy.controller')

router.get('/', listStrategies)
router.get('/:id/code', getStrategyCode)

module.exports = router
