const express = require('express')
const router = express.Router()
const { getExchangeSettings, updateExchangeSettings } = require('../controllers/settings.controller')

router.get('/exchange', getExchangeSettings)
router.put('/exchange', updateExchangeSettings)

module.exports = router
