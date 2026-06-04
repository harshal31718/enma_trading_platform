const LiveSession = require('../models/LiveSession')
const Strategy = require('../models/Strategy')
const engineClient = require('../services/engineClient')
const ApiError = require('../utils/ApiError')
const ApiResponse = require('../utils/ApiResponse')
const { lockSymbol, releaseSymbolLock, getAllLockedSymbols, isSymbolFree } = require('../services/symbolLock')
const { getIO } = require('../config/socket')

// POST /api/v1/algo/sessions
async function startSession(req, res, next) {
  try {
    const { strategyId, symbols, timeframe, params, capital, leverage } = req.body

    if (!strategyId || !symbols || !symbols.length || !timeframe || !capital) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'strategyId, symbols, timeframe, and capital are required')
    }

    // 1. Strategy exists
    const strategy = await Strategy.findById(strategyId).lean()
    if (!strategy) throw new ApiError(404, 'NOT_FOUND', 'Strategy not found')

    // 2. All symbols free
    for (const symbol of symbols) {
      const free = await isSymbolFree(symbol)
      if (!free) {
        const locks = await getAllLockedSymbols()
        const lock = locks[symbol]
        throw new ApiError(
          409,
          'SYMBOL_LOCKED',
          `Symbol ${symbol} is locked (${lock?.reason || 'unknown'}). Release the position first.`
        )
      }
    }

    // 3. Create session in MongoDB
    const session = await LiveSession.create({
      strategyId: strategy._id,
      strategyName: strategy.name,
      symbols,
      timeframe,
      params: params || {},
      capital: String(capital),
      leverage: Number(leverage) || 1,
      status: 'starting',
      mode: 'paper',
    })

    // 4. Lock all symbols in Redis
    const lockedSoFar = []
    try {
      for (const symbol of symbols) {
        await lockSymbol(symbol, 'bot', String(session._id))
        lockedSoFar.push(symbol)
      }
    } catch (lockErr) {
      // Rollback: release any already-locked symbols and delete the session
      for (const s of lockedSoFar) await releaseSymbolLock(s)
      await LiveSession.findByIdAndDelete(session._id)
      throw lockErr
    }

    // 5. Call Engine to start session
    try {
      await engineClient.post('/algo/sessions', {
        session_id: String(session._id),
        strategy_name: strategy.name,
        symbols,
        timeframe,
        params: params || {},
        capital: String(capital),
        leverage: Number(leverage) || 1,
      })
    } catch (engineErr) {
      // Rollback on engine failure
      for (const symbol of symbols) await releaseSymbolLock(symbol).catch(() => {})
      await LiveSession.findByIdAndUpdate(session._id, {
        status: 'error',
        errorMessage: engineErr.message,
      })
      throw new ApiError(502, 'BOT_START_FAILED', `Engine failed to start bot: ${engineErr.message}`)
    }

    // 6. Update status to running
    await LiveSession.findByIdAndUpdate(session._id, { status: 'running' })

    res.status(201).json(ApiResponse.created({ sessionId: String(session._id), status: 'running' }))
  } catch (err) {
    next(err)
  }
}

// POST /api/v1/algo/sessions/:id/stop
async function stopSession(req, res, next) {
  try {
    const session = await LiveSession.findById(req.params.id)
    if (!session) throw new ApiError(404, 'SESSION_NOT_FOUND', 'Session not found')
    if (session.status !== 'running') {
      throw new ApiError(409, 'SESSION_NOT_RUNNING', `Session is ${session.status}, not running`)
    }

    await LiveSession.findByIdAndUpdate(req.params.id, { status: 'stopping' })

    // Call engine asynchronously — don't await full stop
    engineClient.post(`/algo/sessions/${req.params.id}/stop`).catch((err) => {
      console.error(`[AlgoBot] Engine stop call failed for ${req.params.id}:`, err.message)
    })

    res.json(ApiResponse.success({ status: 'stopping' }))
  } catch (err) {
    next(err)
  }
}

// GET /api/v1/algo/sessions
async function listSessions(req, res, next) {
  try {
    const sessions = await LiveSession.find({}).sort({ createdAt: -1 }).lean()
    res.json(ApiResponse.success({ sessions }))
  } catch (err) {
    next(err)
  }
}

// GET /api/v1/algo/sessions/:id
async function getSession(req, res, next) {
  try {
    const session = await LiveSession.findById(req.params.id).lean()
    if (!session) throw new ApiError(404, 'SESSION_NOT_FOUND', 'Session not found')
    res.json(ApiResponse.success({ session }))
  } catch (err) {
    next(err)
  }
}

// GET /api/v1/algo/symbols/locked
async function getLockedSymbols(req, res, next) {
  try {
    const locked = await getAllLockedSymbols()
    res.json(ApiResponse.success({ locked }))
  } catch (err) {
    next(err)
  }
}

// PATCH /internal/algo/sessions/:id/stats (called by Engine)
async function handleEngineStats(req, res, next) {
  try {
    const { id } = req.params
    const { pnl, openPositions, status, event, eventData } = req.body

    const updateData = {}
    if (pnl !== undefined) updateData.pnl = String(pnl)
    if (openPositions !== undefined) updateData.openPositions = openPositions
    if (status && ['running', 'stopping', 'stopped', 'error'].includes(status)) {
      updateData.status = status
      if (status === 'stopped') updateData.stoppedAt = new Date()
    }

    const session = await LiveSession.findByIdAndUpdate(id, updateData, { new: true }).lean()

    if (!session) {
      return res.json({ success: true })
    }

    // Emit Socket.IO events
    try {
      const io = getIO()

      // Always emit session update
      io.emit('algo:session:update', {
        sessionId: id,
        status: session.status,
        pnl: session.pnl,
        openPositions: session.openPositions,
      })

      if (event === 'position:open' && eventData) {
        io.emit('algo:position:open', { sessionId: id, ...eventData })
      }

      if (event === 'position:close' && eventData) {
        io.emit('algo:position:close', { sessionId: id, ...eventData })
        // Release the Redis lock for this symbol
        if (eventData.symbol) {
          await releaseSymbolLock(eventData.symbol).catch(() => {})
        }
      }

      if (event === 'stopped') {
        // Release all remaining locks for this session
        const session2 = await LiveSession.findById(id).lean()
        if (session2?.symbols) {
          for (const sym of session2.symbols) {
            await releaseSymbolLock(sym).catch(() => {})
          }
        }
      }
    } catch (socketErr) {
      console.error('[AlgoBot] Socket.IO emit error:', socketErr.message)
    }

    res.json({ success: true })
  } catch (err) {
    next(err)
  }
}

module.exports = {
  startSession,
  stopSession,
  listSessions,
  getSession,
  getLockedSymbols,
  handleEngineStats,
}
