const express = require('express')
const router = express.Router()
const {
    listStrategies,
    createStrategy,
    getStrategyCode,
    getStrategyParams,
} = require('../controllers/strategy.controller')
const validate = require('../middleware/validate')
const { createStrategySchema } = require('../validators/strategy.validators')

router.get('/', listStrategies)
router.post('/', validate(createStrategySchema), createStrategy)
router.get('/:id/code', getStrategyCode)
router.get('/:id/params', getStrategyParams)

module.exports = router
