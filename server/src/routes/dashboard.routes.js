const express = require('express')
const router = express.Router()
const { getStats, getPerformanceCalendar } = require('../controllers/dashboard.controller')

router.get('/stats', getStats)
router.get('/performance-calendar', getPerformanceCalendar)

module.exports = router
