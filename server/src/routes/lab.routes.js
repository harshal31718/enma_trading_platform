const express = require('express')
const router = express.Router()
const {
  runMonteCarlo,
  getSimulation,
  listSimulations,
  runOptimization,
  getOptimization,
  listOptimizations,
  listObjectives,
} = require('../controllers/lab.controller')

router.post('/simulations', runMonteCarlo)
router.get('/simulations', listSimulations)
router.get('/simulations/:simId', getSimulation)

// Plan 10 Phase 3a/3c — walk-forward optimization jobs.
router.post('/optimizations', runOptimization)
router.get('/optimizations', listOptimizations)
router.get('/objectives', listObjectives) // before /optimizations/:labId so it isn't captured as a labId
router.get('/optimizations/:labId', getOptimization)

module.exports = router
