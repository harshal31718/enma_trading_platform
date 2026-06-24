const express = require('express')
const router = express.Router()
const requireBinanceCredentials = require('../middleware/requireBinanceCredentials')
const { getRiskSettings, updateRiskSettings, getLiveMetrics, getBacktestSimulation } = require('../controllers/risk.controller')

router.get('/settings', getRiskSettings)
router.put('/settings', updateRiskSettings)
router.get('/live-metrics', requireBinanceCredentials, getLiveMetrics)
router.get('/backtest/:id/simulation', getBacktestSimulation)

module.exports = router
