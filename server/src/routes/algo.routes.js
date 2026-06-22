const express = require('express')
const router = express.Router()
const {
  startSession,
  stopSession,
  listSessions,
  getSession,
  getLockedSymbols,
  getSessionEquity,
  deleteSession,
  deleteAllStopped,
  startChaos,
  getChaosSymbols,
} = require('../controllers/algo.controller')

router.post('/sessions', startSession)
router.post('/chaos', startChaos)
router.get('/chaos/symbols', getChaosSymbols)
router.get('/sessions', listSessions)
router.delete('/sessions', deleteAllStopped)
router.get('/sessions/:id', getSession)
router.get('/sessions/:id/equity', getSessionEquity)
router.post('/sessions/:id/stop', stopSession)
router.delete('/sessions/:id', deleteSession)
router.get('/symbols/locked', getLockedSymbols)

module.exports = router
