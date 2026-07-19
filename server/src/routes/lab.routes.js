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
  runPBO,
  getPBO,
  listPBO,
} = require('../controllers/lab.controller')

router.post('/simulations', runMonteCarlo)
router.get('/simulations', listSimulations)
router.get('/simulations/:simId', getSimulation)

// Plan 10 Phase 3a/3c — walk-forward optimization jobs.
router.post('/optimizations', runOptimization)
router.get('/optimizations', listOptimizations)
router.get('/objectives', listObjectives) // before /optimizations/:labId so it isn't captured as a labId
router.get('/optimizations/:labId', getOptimization)

// Plan 10 — PBO (Probability of Backtest Overfitting). /pbo (list) before /pbo/:labId, same
// capture-order reasoning as /optimizations above.
router.post('/pbo', runPBO)
router.get('/pbo', listPBO)
router.get('/pbo/:labId', getPBO)

module.exports = router
