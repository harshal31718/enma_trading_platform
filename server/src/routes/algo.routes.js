const express = require('express')
const router = express.Router()
const {
  startSession,
  stopSession,
  setTradingState,
  listSessions,
  getSession,
  getLockedSymbols,
  getSessionEquity,
  deleteSession,
  deleteAllStopped,
  startChaos,
  getChaosSymbols,
  previewPairlist,
} = require('../controllers/algo.controller')

router.post('/sessions', startSession)
router.post('/chaos', startChaos)
router.get('/chaos/symbols', getChaosSymbols)
router.get('/sessions', listSessions)
router.delete('/sessions', deleteAllStopped)
router.get('/sessions/:id', getSession)
router.get('/sessions/:id/equity', getSessionEquity)
router.post('/sessions/:id/stop', stopSession)
router.post('/sessions/:id/trading-state', setTradingState)
router.delete('/sessions/:id', deleteSession)
router.post('/pairlist/preview', previewPairlist)
router.get('/symbols/locked', getLockedSymbols)

module.exports = router
