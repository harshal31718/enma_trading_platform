const express = require('express')
const router = express.Router()
const {
  startSession,
  stopSession,
  listSessions,
  getSession,
  getLockedSymbols,
} = require('../controllers/algo.controller')

router.post('/sessions', startSession)
router.get('/sessions', listSessions)
router.get('/sessions/:id', getSession)
router.post('/sessions/:id/stop', stopSession)
router.get('/symbols/locked', getLockedSymbols)

module.exports = router
