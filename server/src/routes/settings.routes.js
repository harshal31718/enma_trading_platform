const express = require('express')
const router = express.Router()
const { getExchangeSettings, updateExchangeSettings, testWebhook } = require('../controllers/settings.controller')

router.get('/exchange', getExchangeSettings)
router.put('/exchange', updateExchangeSettings)
router.post('/webhook/test', testWebhook)

module.exports = router
