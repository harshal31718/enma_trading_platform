const express = require('express')
const router = express.Router()
const {
  startSession,
  requestAlgoAccess,
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
const { requireAlgoAccess } = require('../middleware/auth.middleware')

// User requests Algo Trading access (not gated — that's the point).
router.post('/access-request', requestAlgoAccess)

// Start actions require granted access; everything else (list/stop/delete/preview)
// stays open so a user whose access is revoked can still stop running sessions.
router.post('/sessions', requireAlgoAccess, startSession)
router.post('/chaos', requireAlgoAccess, startChaos)
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
