const express = require('express')
const router = express.Router()
const { handleEngineStats } = require('../controllers/algo.controller')

// Called by Python engine to push session stat updates
router.patch('/algo/sessions/:id/stats', handleEngineStats)

module.exports = router
