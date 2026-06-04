const LiveSession = require('../models/LiveSession')
const Strategy = require('../models/Strategy')
const engineClient = require('../services/engineClient')
const ApiError = require('../utils/ApiError')
const ApiResponse = require('../utils/ApiResponse')
const { lockSymbol, releaseSymbolLock, getAllLockedSymbols, isSymbolFree, getSymbolLock } = require('../services/symbolLock')
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
      for (const s of lockedSoFar) await releaseSymbolLock(s, String(session._id))
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
      for (const symbol of symbols) await releaseSymbolLock(symbol, String(session._id)).catch(() => {})
      await LiveSession.findByIdAndUpdate(session._id, {
        status: 'error',
        errorMessage: engineErr.message,
      })
      throw new ApiError(502, 'BOT_START_FAILED', `Engine failed to start bot: ${engineErr.message}`)
    }

    // 6. Update status to running
    await LiveSession.findByIdAndUpdate(session._id, { status: 'running' })

    const io = getIO()
    io.emit('algo:session:log', {
      sessionId: String(session._id),
      timestamp: new Date().toISOString(),
      type: 'info',
      message: `Bot initialized and started trading ${symbols.length} symbols.`
    })

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
    engineClient.post(`/algo/sessions/${req.params.id}/stop`).catch(async (err) => {
      console.error(`[AlgoBot] Engine stop call failed for ${req.params.id}:`, err.message)
      
      // Force stop in DB if engine fails (e.g. 404 because engine restarted)
      await LiveSession.findByIdAndUpdate(req.params.id, { status: 'stopped', stoppedAt: new Date() })

      // Fallback: Close positions and release locks
      try {
        const headers = await _getBinanceHeaders()
        const { releaseSymbolLock } = require('../services/symbolLock')
        for (const symbol of session.symbols) {
          console.log(`[AlgoBot] Engine stop call failed. Fallback force-closing position for ${symbol}...`)
          await engineClient.post('/trade/close-position', { symbol }, { headers }).catch((closeErr) => {
            console.log(`[AlgoBot] Note: No position closed or error for ${symbol}: ${closeErr.message}`)
          })
          await releaseSymbolLock(symbol, String(session._id)).catch(() => {})
        }
      } catch (fallbackErr) {
        console.error(`[AlgoBot] Fallback position closing/lock release failed:`, fallbackErr.message)
      }

      const io = getIO()
      io.emit('algo:session:update', {
        sessionId: req.params.id,
        status: 'stopped',
      })
      io.emit('algo:session:log', {
        sessionId: req.params.id,
        timestamp: new Date().toISOString(),
        type: 'error',
        message: 'Engine process not found. Fallback: Position closed and session forcefully stopped.'
      })
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

// GET /api/v1/algo/sessions/:id/equity
async function getSessionEquity(req, res, next) {
  try {
    const session = await LiveSession.findById(req.params.id).lean()
    if (!session) throw new ApiError(404, 'SESSION_NOT_FOUND', 'Session not found')
    res.json(ApiResponse.success({ equity: session.tradeHistory || [] }))
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
      if (status === 'error' && req.body.errorMessage) updateData.errorMessage = req.body.errorMessage
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
        const openLog = {
          sessionId: id,
          timestamp: new Date().toISOString(),
          type: eventData.side === 'long' ? 'long' : 'short',
          message: `${eventData.side.toUpperCase()} ${eventData.symbol} · qty ${eventData.qty} · entry $${eventData.price}`
        }
        io.emit('algo:session:log', openLog)
        await LiveSession.findByIdAndUpdate(id, {
          $push: { logs: { $each: [{ type: openLog.type, message: openLog.message }], $slice: -100 } }
        }).catch(() => {})
      }

      if (event === 'position:close' && eventData) {
        io.emit('algo:position:close', { sessionId: id, ...eventData })

        const isPositive = parseFloat(eventData.pnl) >= 0
        const closeLog = {
          sessionId: id,
          timestamp: new Date().toISOString(),
          type: 'closed',
          message: `Closed ${eventData.symbol} · PnL ${isPositive ? '+' : ''}$${eventData.pnl}`
        }
        io.emit('algo:session:log', closeLog)
        await LiveSession.findByIdAndUpdate(id, {
          $push: { logs: { $each: [{ type: closeLog.type, message: closeLog.message }], $slice: -100 } }
        }).catch(() => {})
        
        // Push to trade history
        const currentBalance = parseFloat(session.capital) + parseFloat(session.pnl || '0')
        await LiveSession.findByIdAndUpdate(id, {
          $inc: { totalTrades: 1 },
          $push: {
            tradeHistory: {
              timestamp: new Date(),
              balance: currentBalance.toString()
            }
          }
        })
        
        // Release the Redis lock for this symbol
        if (eventData.symbol) {
          await releaseSymbolLock(eventData.symbol, id).catch(() => {})
        }
      }

      if (status === 'error') {
        const errMsg = req.body.errorMessage || session?.errorMessage || 'Unknown strategy error'
        io.emit('algo:session:log', {
          sessionId: id,
          timestamp: new Date().toISOString(),
          type: 'error',
          message: errMsg
        })
        // Release all symbol locks for errored sessions
        if (session?.symbols) {
          for (const sym of session.symbols) {
            await releaseSymbolLock(sym, id).catch(() => {})
          }
        }
      }

      if (event === 'log' && eventData) {
        const logEntry = {
          sessionId: id,
          timestamp: new Date().toISOString(),
          type: eventData.type || 'info',
          message: eventData.message,
        }
        io.emit('algo:session:log', logEntry)
        await LiveSession.findByIdAndUpdate(id, {
          $push: { logs: { $each: [{ type: logEntry.type, message: logEntry.message }], $slice: -100 } }
        }).catch(() => {})
      }

      if (event === 'stopped') {
        // Release all remaining locks for this session
        const session2 = await LiveSession.findById(id).lean()
        if (session2?.symbols) {
          for (const sym of session2.symbols) {
            await releaseSymbolLock(sym, id).catch(() => {})
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

// DELETE /api/v1/algo/sessions/:id  — only allowed for stopped/error sessions
async function deleteSession(req, res, next) {
  try {
    const session = await LiveSession.findById(req.params.id)
    if (!session) throw new ApiError(404, 'SESSION_NOT_FOUND', 'Session not found')
    if (['running', 'starting', 'stopping'].includes(session.status)) {
      throw new ApiError(409, 'SESSION_ACTIVE', 'Stop the session before deleting it')
    }
    await LiveSession.findByIdAndDelete(req.params.id)
    res.json(ApiResponse.success({ deleted: true }))
  } catch (err) {
    next(err)
  }
}

// DELETE /api/v1/algo/sessions  — bulk delete all stopped/error sessions
async function deleteAllStopped(req, res, next) {
  try {
    const result = await LiveSession.deleteMany({ status: { $in: ['stopped', 'error'] } })
    res.json(ApiResponse.success({ deleted: result.deletedCount }))
  } catch (err) {
    next(err)
  }
}

// POST /internal/algo/sessions/:id/get-position
// Body: { symbol }
// Returns the raw Binance positionRisk entry so the engine can sync local state.
async function handleAlgoGetPosition(req, res) {
  try {
    const { symbol } = req.body
    const headers = await _getBinanceHeaders()
    const { data } = await engineClient.get('/trade/positions', { headers, params: { symbol } })
    const positions = data?.data || []
    const pos = Array.isArray(positions)
      ? positions.find(p => p.symbol === symbol)
      : null
    res.json({ success: true, data: pos || null })
  } catch (err) {
    console.error('[AlgoBot] get-position failed:', err.message)
    res.json({ success: false, error: err.message })
  }
}

module.exports = {
  startSession,
  stopSession,
  listSessions,
  getSession,
  getLockedSymbols,
  getSessionEquity,
  handleEngineStats,
  handleAlgoPlaceOrder,
  handleAlgoClosePosition,
  handleAlgoSetLeverage,
  handleAlgoGetPosition,
  deleteSession,
  deleteAllStopped,
}

// ── Internal handlers for real Binance order placement ──────────────────────
// These are called by the Python engine, not the browser client.

async function _getBinanceHeaders() {
  const apiKey = process.env.BINANCE_TESTNET_API_KEY
  const apiSecret = process.env.BINANCE_TESTNET_SECRET
  if (!apiKey || !apiSecret) {
    throw new Error('Binance Testnet API credentials not configured. Set BINANCE_TESTNET_API_KEY and BINANCE_TESTNET_SECRET in server/.env')
  }

  return {
    'X-Binance-API-Key': apiKey,
    'X-Binance-API-Secret': apiSecret,
    'X-Binance-Mode': 'testnet',
  }
}

// POST /internal/algo/sessions/:id/place-order
// Body: { symbol, side, type, quantity, price?, stopLoss?, takeProfit? }
async function handleAlgoPlaceOrder(req, res, next) {
  try {
    const { symbol, side, type, quantity, price, stopLoss, takeProfit } = req.body

    const lock = await getSymbolLock(symbol)
    if (!lock || lock.reason !== 'bot' || lock.sessionId !== req.params.id) {
      throw new ApiError(409, 'SYMBOL_LOCKED', `Symbol ${symbol} is not locked by this bot session.`)
    }

    const headers = await _getBinanceHeaders()

    const { data } = await engineClient.post(
      '/trade/order/with_tp_sl',
      { symbol, side: side.toUpperCase(), type: type?.toUpperCase() || 'MARKET', quantity, price, stopLoss, takeProfit },
      { headers }
    )

    res.json({ success: true, data: data.data })
  } catch (err) {
    console.error('[AlgoBot] Real order placement failed:', err.message)
    const detail = err.response?.data?.detail
    const message = typeof detail === 'string' ? detail : detail?.message || err.message
    res.status(err.response?.status || 500).json({ success: false, error: message })
  }
}

// POST /internal/algo/sessions/:id/close-position
// Body: { symbol }
async function handleAlgoClosePosition(req, res, next) {
  try {
    const { symbol } = req.body

    const lock = await getSymbolLock(symbol)
    if (!lock || lock.reason !== 'bot' || lock.sessionId !== req.params.id) {
      throw new ApiError(409, 'SYMBOL_LOCKED', `Symbol ${symbol} is not locked by this bot session.`)
    }

    const headers = await _getBinanceHeaders()

    const { data } = await engineClient.post('/trade/close-position', { symbol }, { headers })
    res.json({ success: true, data: data.data })
  } catch (err) {
    console.error('[AlgoBot] Real close position failed:', err.message)
    const detail = err.response?.data?.detail
    const message = typeof detail === 'string' ? detail : detail?.message || err.message
    res.status(err.response?.status || 500).json({ success: false, error: message })
  }
}

// POST /internal/algo/sessions/:id/set-leverage
// Body: { symbol, leverage }
async function handleAlgoSetLeverage(req, res, next) {
  try {
    const { symbol, leverage } = req.body

    const lock = await getSymbolLock(symbol)
    if (!lock || lock.reason !== 'bot' || lock.sessionId !== req.params.id) {
      throw new ApiError(409, 'SYMBOL_LOCKED', `Symbol ${symbol} is not locked by this bot session.`)
    }

    const headers = await _getBinanceHeaders()

    await engineClient.post('/trade/leverage', { symbol, leverage }, { headers })
    res.json({ success: true })
  } catch (err) {
    // Ignore "no need to change" errors
    const code = err.response?.data?.detail?.code
    if (code === -4046) return res.json({ success: true })
    console.error('[AlgoBot] Real set leverage failed:', err.message)
    res.status(err.response?.status || 500).json({ success: false, error: err.message })
  }
}
