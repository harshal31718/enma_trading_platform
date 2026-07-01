const LiveSession = require('../models/LiveSession')
const TradeRecord = require('../models/TradeRecord')
const Strategy = require('../models/Strategy')
const Settings = require('../models/Settings')
const { decrypt } = require('../utils/encryption')
const engineClient = require('../services/engineClient')
const { getTOP_SYMBOLS, getTIERED_SYMBOLS } = require('../constants/top_symbols')
const ApiError = require('../utils/ApiError')
const ApiResponse = require('../utils/ApiResponse')
const { lockSymbol, releaseSymbolLock, getAllLockedSymbols, isSymbolFree, getSymbolLock } = require('../services/symbolLock')
const { getIO } = require('../config/socket')
const { resolveModelParams, resolveStrategyRiskParams } = require('../utils/risk')
const { allocateChaosSymbols } = require('../utils/chaosAllocator')

// POST /api/v1/algo/sessions
async function startSession(req, res, next) {
  try {
    const { strategyId, symbols, timeframe, params, capital, leverage, riskParams: riskOverride } = req.body

    if (!strategyId || !symbols || !symbols.length || !timeframe || !capital) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'strategyId, symbols, timeframe, and capital are required')
    }

    // 1. Strategy exists
    const strategy = await Strategy.findById(strategyId).lean()
    if (!strategy) throw new ApiError(404, 'NOT_FOUND', 'Strategy not found')

    // Risk model: resolve per-symbol overrides over strategy overrides, symbol overrides, and saved global defaults.
    const savedSettings = await Settings.findOne({ userId: req.user.id }).lean() || {}
    const apiKey = savedSettings.encryptedApiKey ? decrypt(savedSettings.encryptedApiKey) : ''
    const apiSecret = savedSettings.encryptedApiSecret ? decrypt(savedSettings.encryptedApiSecret) : ''
    if (!apiKey || !apiSecret) throw new ApiError(400, 'NO_CREDENTIALS', 'Binance API keys not configured. Add them in Settings.')
    const riskParams = {}
    for (const symbol of symbols) {
      riskParams[symbol] = resolveStrategyRiskParams(strategy.name, symbol, savedSettings, {
        ...riskOverride,
        leverage: Number(leverage) || 1
      })
    }
    riskParams.default = resolveStrategyRiskParams(strategy.name, null, savedSettings, {
      ...riskOverride,
      leverage: Number(leverage) || 1
    })

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
      userId: req.user.id,
      strategyId: strategy._id,
      strategyName: strategy.name,
      symbols,
      timeframe,
      params: params || {},
      capital: String(capital),
      leverage: Number(leverage) || 1,
      riskParams,
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
    const feeRate = savedSettings.takerFee ?? 0.0005

    try {
      await engineClient.post('/algo/sessions', {
        session_id: String(session._id),
        strategy_name: strategy.name,
        symbols,
        timeframe,
        params: params || {},
        capital: String(capital),
        leverage: Number(leverage) || 1,
        fee_rate: feeRate,
        risk_params: riskParams,
        user_id: String(req.user.id),
        api_key: apiKey,
        api_secret: apiSecret,
      })
    } catch (engineErr) {
      // Rollback on engine failure
      for (const symbol of symbols) await releaseSymbolLock(symbol, String(session._id)).catch(() => { })
      await LiveSession.findByIdAndUpdate(session._id, {
        status: 'error',
        errorMessage: engineErr.message,
      })
      throw new ApiError(502, 'BOT_START_FAILED', `Engine failed to start bot: ${engineErr.message}`)
    }

    // 6. Update status to running
    await LiveSession.findByIdAndUpdate(session._id, { status: 'running' })

    const io = getIO()
    io.to(`user:${req.user.id}`).emit('algo:session:log', {
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
    const session = await LiveSession.findOne({ _id: req.params.id, userId: req.user.id })
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
        const headers = await _getBinanceHeaders(req.params.id)
        const { releaseSymbolLock } = require('../services/symbolLock')
        for (const symbol of session.symbols) {
          console.log(`[AlgoBot] Engine stop call failed. Fallback force-closing position for ${symbol}...`)
          await engineClient.post('/trade/close-position', { symbol }, { headers }).catch((closeErr) => {
            console.log(`[AlgoBot] Note: No position closed or error for ${symbol}: ${closeErr.message}`)
          })
          await releaseSymbolLock(symbol, String(session._id)).catch(() => { })
        }
      } catch (fallbackErr) {
        console.error(`[AlgoBot] Fallback position closing/lock release failed:`, fallbackErr.message)
      }

      const io = getIO()
      io.to(`user:${String(session.userId)}`).emit('algo:session:update', {
        sessionId: req.params.id,
        status: 'stopped',
      })
      io.to(`user:${String(session.userId)}`).emit('algo:session:log', {
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
    const sessions = await LiveSession.find({ userId: req.user.id }).sort({ createdAt: -1 }).lean()
    res.json(ApiResponse.success({ sessions }))
  } catch (err) {
    next(err)
  }
}

// GET /api/v1/algo/sessions/:id
async function getSession(req, res, next) {
  try {
    const session = await LiveSession.findOne({ _id: req.params.id, userId: req.user.id }).lean()
    if (!session) throw new ApiError(404, 'SESSION_NOT_FOUND', 'Session not found')
    res.json(ApiResponse.success({ session }))
  } catch (err) {
    next(err)
  }
}

// POST /api/v1/algo/sessions/:id/trading-state
async function setTradingState(req, res, next) {
  try {
    const { state } = req.body
    if (!['active', 'reducing', 'halted'].includes(state)) {
      throw new ApiError(400, 'INVALID_STATE', 'trading_state must be "active", "reducing", or "halted"')
    }

    const session = await LiveSession.findOne({ _id: req.params.id, userId: req.user.id }).lean()
    if (!session) throw new ApiError(404, 'SESSION_NOT_FOUND', 'Session not found')

    // Call engine to update trading state
    try {
      await engineClient.post(`/algo/sessions/${req.params.id}/trading-state`, { state })
    } catch (engineErr) {
      throw new ApiError(502, 'ENGINE_ERROR', `Engine failed to set trading state: ${engineErr.message}`)
    }

    // Update in MongoDB
    await LiveSession.findByIdAndUpdate(req.params.id, { tradingState: state })

    const io = getIO()
    io.to(`user:${String(session.userId)}`).emit('algo:session:update', { sessionId: req.params.id, tradingState: state })
    io.to(`user:${String(session.userId)}`).emit('algo:session:log', {
      sessionId: req.params.id,
      timestamp: new Date().toISOString(),
      type: 'info',
      message: `Trading state changed to ${state}`
    })

    res.json(ApiResponse.success({ tradingState: state }))
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
    const session = await LiveSession.findOne({ _id: req.params.id, userId: req.user.id }).lean()
    if (!session) throw new ApiError(404, 'SESSION_NOT_FOUND', 'Session not found')
    res.json(ApiResponse.success({ equity: session.tradeHistory || [] }))
  } catch (err) {
    next(err)
  }
}

// Re-derive per-symbol aggregates for a session from the tradeRecords
// collection (the engine is the sole writer). Returns a { symbol: {...} } map.
async function computeSymbolStats(sessionId) {
  const rows = await TradeRecord.aggregate([
    { $match: { sessionId: String(sessionId) } },
    { $sort: { exitTime: 1 } },
    {
      $group: {
        _id: '$symbol',
        trades: { $sum: 1 },
        qty: { $sum: { $toDouble: '$qty' } },
        notional: { $sum: { $multiply: [{ $toDouble: '$qty' }, { $toDouble: '$entryPrice' }] } },
        realisedPnl: { $sum: { $toDouble: '$netPnl' } },
        leverage: { $last: '$leverage' },
      },
    },
  ])
  const stats = {}
  for (const r of rows) {
    stats[r._id] = {
      trades: r.trades,
      qty: r.qty,
      notional: r.notional,
      realisedPnl: r.realisedPnl,
      leverage: r.leverage || null,
    }
  }
  return stats
}

// PATCH /internal/algo/sessions/:id/stats (called by Engine)
async function handleEngineStats(req, res, next) {
  try {
    const { id } = req.params
    const { pnl, openPositions, status, event, eventData, positionDetails } = req.body

    const updateData = {}
    if (pnl !== undefined) updateData.pnl = String(pnl)
    if (openPositions !== undefined) updateData.openPositions = openPositions
    if (status && ['running', 'stopping', 'stopped', 'error'].includes(status)) {
      updateData.status = status
      if (status === 'stopped') updateData.stoppedAt = new Date()
      if (status === 'error' && req.body.errorMessage) updateData.errorMessage = req.body.errorMessage
    }
    // Store exchange-truth position details from engine reconciliation
    // (F-001/F-023) — each symbol's side, qty, price, mark_price,
    // unrealized_pnl. Used by the UI as single source of truth.
    if (positionDetails && typeof positionDetails === 'object') {
      const pd = {}
      for (const [sym, info] of Object.entries(positionDetails)) {
        pd[sym] = info
      }
      updateData.positionDetails = pd
    }

    const session = await LiveSession.findByIdAndUpdate(id, updateData, { new: true }).lean()

    if (!session) {
      return res.json({ success: true })
    }

    // Emit Socket.IO events
    try {
      const io = getIO()
      const userRoom = `user:${String(session.userId)}`

      // Always emit session update
      io.to(userRoom).emit('algo:session:update', {
        sessionId: id,
        status: session.status,
        pnl: session.pnl,
        openPositions: session.openPositions,
      })

      if (event === 'position:open' && eventData) {
        io.to(userRoom).emit('algo:position:open', { sessionId: id, ...eventData })
        const openLog = {
          sessionId: id,
          timestamp: new Date().toISOString(),
          type: eventData.side === 'long' ? 'long' : 'short',
          message: `${eventData.side.toUpperCase()} ${eventData.symbol} · qty ${eventData.qty} · entry $${eventData.price}`
        }
        io.to(userRoom).emit('algo:session:log', openLog)
        await LiveSession.findByIdAndUpdate(id, {
          $push: { logs: { $each: [{ type: openLog.type, message: openLog.message }], $slice: -100 } },
          // Persist the open-position snapshot with exchange-truth PnL data
          // (F-023/A-013): mark_price and unrealized_pnl come from Binance.
          $set: {
            [`positionDetails.${eventData.symbol}`]: {
              side: eventData.side,
              qty: eventData.qty,
              price: eventData.price,
              leverage: eventData.leverage,
              mark_price: eventData.mark_price || null,
              unrealized_pnl: eventData.unrealized_pnl || null,
              price_missing: eventData.price_missing || false,
            },
          },
        }).catch(() => { })
      }

      if (event === 'position:close' && eventData) {
        io.to(userRoom).emit('algo:position:close', { sessionId: id, ...eventData })

        const isPositive = parseFloat(eventData.pnl) >= 0
        const closeLog = {
          sessionId: id,
          timestamp: new Date().toISOString(),
          type: 'closed',
          message: `Closed ${eventData.symbol} · PnL ${isPositive ? '+' : ''}$${eventData.pnl}`
        }
        io.to(userRoom).emit('algo:session:log', closeLog)
        await LiveSession.findByIdAndUpdate(id, {
          $push: { logs: { $each: [{ type: closeLog.type, message: closeLog.message }], $slice: -100 } },
          // Clear the persisted snapshot — the position is no longer open.
          $unset: { [`positionDetails.${eventData.symbol}`]: '' },
        }).catch(() => { })

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

        // Re-derive per-symbol aggregates from the now-recorded trade and push
        // them to clients so the Open Positions panel updates live.
        try {
          const symbolStats = await computeSymbolStats(id)
          await LiveSession.findByIdAndUpdate(id, { symbolStats })
          io.to(userRoom).emit('algo:session:update', { sessionId: id, symbolStats })
        } catch (statsErr) {
          console.error('[AlgoBot] symbolStats aggregation failed:', statsErr.message)
        }

        // NOTE: Symbol lock is intentionally NOT released here.
        // The lock persists for the entire bot session to allow multiple trades on the same symbol.
        // Lock is released only when the session stops or encounters an error.
      }

      if (status === 'error') {
        const errMsg = req.body.errorMessage || session?.errorMessage || 'Unknown strategy error'
        io.to(userRoom).emit('algo:session:log', {
          sessionId: id,
          timestamp: new Date().toISOString(),
          type: 'error',
          message: errMsg
        })
        // Release all symbol locks for errored sessions
        if (session?.symbols) {
          for (const sym of session.symbols) {
            await releaseSymbolLock(sym, id).catch(() => { })
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
        io.to(userRoom).emit('algo:session:log', logEntry)
        await LiveSession.findByIdAndUpdate(id, {
          $push: { logs: { $each: [{ type: logEntry.type, message: logEntry.message }], $slice: -100 } }
        }).catch(() => { })
      }

      if (event === 'stopped') {
        // Final per-symbol aggregation — captures positions force-closed during
        // the stop sequence (which emit no position:close event).
        try {
          const symbolStats = await computeSymbolStats(id)
          await LiveSession.findByIdAndUpdate(id, { symbolStats })
          io.to(userRoom).emit('algo:session:update', { sessionId: id, symbolStats })
        } catch (statsErr) {
          console.error('[AlgoBot] symbolStats aggregation (stop) failed:', statsErr.message)
        }

        // Release all remaining locks for this session
        const session2 = await LiveSession.findById(id).lean()
        if (session2?.symbols) {
          for (const sym of session2.symbols) {
            await releaseSymbolLock(sym, id).catch(() => { })
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
    const session = await LiveSession.findOne({ _id: req.params.id, userId: req.user.id })
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
    const result = await LiveSession.deleteMany({ userId: req.user.id, status: { $in: ['stopped', 'error'] } })
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
    const headers = await _getBinanceHeaders(req.params.id)
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

// POST /internal/algo/sessions/:id/get-open-orders
// Body: { symbol }
// Returns the raw Binance open orders for this symbol so the engine can
// reconcile open orders against exchange state every loop (F-002).
async function handleAlgoGetOpenOrders(req, res) {
  try {
    const { symbol } = req.body
    const headers = await _getBinanceHeaders(req.params.id)
    const { data } = await engineClient.get('/trade/open-orders', { headers, params: { symbol } })
    res.json({ success: true, data: data?.data || [] })
  } catch (err) {
    console.error('[AlgoBot] get-open-orders failed:', err.message)
    res.json({ success: false, error: err.message })
  }
}

// ── Chaos Mode ──────────────────────────────────────────────────────────────
// POST /api/v1/algo/chaos
// Guided wizard launch — accepts an optional JSON body; empty body reproduces
// the original fire-and-forget behaviour (auto-select all strategies, full pool).
// Testnet-only by construction (sessions are created with mode:'paper').
//
// Body schema (all optional):
// {
//   "timeframe": "1m",
//   "strategies": [
//     { "name": "MicroScalper", "symbols": ["BTCUSDT","ETHUSDT"] },
//     { "name": "AdaptiveTrend" }
//   ],
//   "risk": { "capital": "500", "leverage": 50, "riskReward": 1.5,
//             "maxDrawdown": 25, "riskPct": 1, "minEdgeMult": 1 }
// }

const CHAOS_LAUNCH_LIST = [
  {
    name: 'MicroScalper',
    params: {
      fast_period:    2,
      slow_period:    3,
      atr_period:     5,
      atr_multiplier: 0.0,
      sl_atr_mult:    0.1,
      tp_atr_mult:    0.2,
    },
  },
  {
    name: 'AdaptiveTrend',
    params: {
      trend_period:   50,
      slope_lookback: 1,
      fast_period:    3,
      slow_period:    10,
      atr_period:     5,
      atr_floor_mult: 0.0,
      sl_atr_mult:    0.5,
      trail_atr_mult: 0.5,
      breakeven_r:    0.0,
      tp_r_mult:      0.0,
      max_leverage:   20.0,
      allow_shorts:   1,
    },
  },
  {
    name: 'BestSupertrend',
    params: {
      order_type:        'Longs+Shorts',
      fast_length:       1,
      slow_length:       2,
      factor:            1.0,
      pd:                1,
      sl_atr_mult:       0.5,
      atr_period:        5,
      tf:                '1h',
      position_size_pct: 1.0,
    },
  },
  {
    name: 'MicroMacroRSIDivergence',
    params: {
      rsi_period:                  2,
      micro_pivot:                 1,
      macro_pivot:                 2,
      confluence_window:           1,
      min_pivot_bars:              1,
      max_pivot_bars:              5,
      min_div_diff:                0.0,
      smooth_type:                 0,
      smooth_length:               2,
      enable_rsi_level_filter:     0,
      enable_rsi_direction_filter: 0,
      enable_smoothed_filter:      0,
      exit_on_opposite:            1,
      atr_period:                  5,
      sl_atr_mult:                 0.5,
    },
  },
  {
    name: 'MultiDivergence',
    params: {
      piv_len:        2,
      min_confluence: 1,
      sl_atr_mult:    0.1,
      tp_atr_mult:    0.1,
      use_custom_sl:  0,
      custom_sl_pct:  0.1,
      allow_shorts:   1,
      atr_period:     5,
      rsi_period:     2,
      mfi_period:     2,
      stoch_period:   2,
      adx_period:     5,
      macd_fast:      2,
      macd_slow:      5,
      macd_signal:    2,
      z_period:       5,
      use_rsi:        1, use_mfi: 1, use_stoch: 1, use_zscore: 1,
      use_adx:        1, use_macd: 1, use_obv:   1, use_price:  1, use_swing: 1,
    },
  },
]

const CHAOS_SUPPORTED_TIMEFRAMES = ['1m','3m','5m','15m','30m','1h','2h','4h','6h','8h','12h','1d']

async function startChaos(req, res, next) {
  try {
    // ── 1. Load settings & known strategies ─────────────────────────────────
    const savedSettings = await Settings.findOne({ userId: req.user.id }).lean() || {}
    const chaosApiKey = savedSettings.encryptedApiKey ? decrypt(savedSettings.encryptedApiKey) : ''
    const chaosApiSecret = savedSettings.encryptedApiSecret ? decrypt(savedSettings.encryptedApiSecret) : ''
    if (!chaosApiKey || !chaosApiSecret) throw new ApiError(400, 'NO_CREDENTIALS', 'Binance API keys not configured. Add them in Settings.')
    const feeRate = savedSettings.takerFee ?? 0.0005
    const riskParams = resolveModelParams(savedSettings, null)

    const maxStrategies    = savedSettings.chaosMaxStrategies    ?? 10
    const maxManualSymbols = savedSettings.chaosMaxManualSymbols ?? 5
    const defaultCapital   = savedSettings.chaosDefaultCapital   ?? 500
    const defaultLeverage  = savedSettings.chaosDefaultLeverage  ?? 50
    const defaultTF        = savedSettings.chaosDefaultTimeframe ?? '1m'

    const allStrategies = await Strategy.find({}).sort({ updatedAt: -1, createdAt: -1 }).lean()
    const strategyMap = new Map(allStrategies.map(s => [s.name, s]))

    // ── 2. Parse + validate request body ────────────────────────────────────
    const body = req.body || {}

    // timeframe
    const timeframe = body.timeframe ?? defaultTF
    if (!CHAOS_SUPPORTED_TIMEFRAMES.includes(timeframe)) {
      throw new ApiError(400, 'VALIDATION_ERROR',
        `timeframe "${timeframe}" is not supported. Must be one of: ${CHAOS_SUPPORTED_TIMEFRAMES.join(', ')}`)
    }

    // risk override (capital + leverage come from body.risk or settings defaults)
    const riskBody = body.risk || {}
    const capital  = String(riskBody.capital  ?? defaultCapital)
    const leverage = Number(riskBody.leverage ?? defaultLeverage)
    // Per-run risk model override (riskReward, maxDrawdown, riskPct, minEdgeMult)
    const riskOverride = {}
    if (riskBody.riskReward  != null) riskOverride.riskRewardRatio    = riskBody.riskReward
    if (riskBody.maxDrawdown != null) riskOverride.maxSessionDrawdown = riskBody.maxDrawdown / 100
    if (riskBody.riskPct     != null) riskOverride.riskPct            = riskBody.riskPct / 100
    if (riskBody.minEdgeMult != null) riskOverride.minEdgeMult        = riskBody.minEdgeMult
    // We will resolve risk parameters per-strategy and per-symbol inside the launch loop below.

    // strategies body: array of { name, symbols? }
    const strategiesBody = body.strategies || []
    if (!Array.isArray(strategiesBody)) {
      throw new ApiError(400, 'VALIDATION_ERROR', '"strategies" must be an array')
    }

    // ── 3. Resolve active strategies (D2) ───────────────────────────────────
    let activeNames
    if (strategiesBody.length === 0) {
      // Auto-select: most-recent up to cap
      activeNames = allStrategies.slice(0, maxStrategies).map(s => s.name)
    } else {
      // Validate names
      const knownNames = new Set(allStrategies.map(s => s.name))
      for (const entry of strategiesBody) {
        if (!knownNames.has(entry.name)) {
          throw new ApiError(400, 'VALIDATION_ERROR', `Strategy "${entry.name}" not found in the database.`)
        }
      }
      if (strategiesBody.length > maxStrategies) {
        throw new ApiError(400, 'VALIDATION_ERROR',
          `Too many strategies selected (${strategiesBody.length}). Max is ${maxStrategies}.`)
      }
      activeNames = strategiesBody.map(e => e.name)
    }

    if (activeNames.length === 0) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'No strategies available to run.')
    }

    // Build manualPicks map { strategyName: [symbols] }
    const manualPicks = {}
    for (const entry of strategiesBody) {
      if (entry.symbols && entry.symbols.length > 0) {
        manualPicks[entry.name] = entry.symbols
      }
    }

    // ── 4. Read current symbol locks ────────────────────────────────────────
    const locksSnapshot = await getAllLockedSymbols()
    const lockedSymbols = Object.keys(locksSnapshot)

    // ── 5. Allocate symbols via the pure allocator ───────────────────────────
    const [TOP_SYMBOLS, TIERED_SYMBOLS] = await Promise.all([
      getTOP_SYMBOLS(),
      getTIERED_SYMBOLS(),
    ])
    let assignments, dropped
    try {
      const result = allocateChaosSymbols({
        activeStrategies: activeNames,
        manualPicks,
        lockedSymbols,
        curatedSymbols: TOP_SYMBOLS,
        tierMap: TIERED_SYMBOLS,
        maxManualSymbols,
      })
      assignments = result.assignments
      dropped = result.dropped
    } catch (allocErr) {
      // allocator throws { status, code, message } for validation failures
      if (allocErr.status) {
        throw new ApiError(allocErr.status, allocErr.code, allocErr.message)
      }
      throw allocErr
    }

    // ── 6. Launch each strategy (existing loop — lock → create → engine → rollback) ──
    const created = []
    const errors  = []

    for (const stratName of activeNames) {
      const strategy = strategyMap.get(stratName)
      if (!strategy) {
        errors.push({ strategy: stratName, error: 'Strategy not found in MongoDB — run engine to seed' })
        continue
      }

      const symbols = assignments[stratName] || []
      if (symbols.length === 0) {
        errors.push({ strategy: stratName, error: 'No symbols allocated (all locked or pool exhausted)' })
        continue
      }

      // Find matching chaos params (fall back to empty if not in CHAOS_LAUNCH_LIST)
      const launchEntry = CHAOS_LAUNCH_LIST.find(e => e.name === stratName)
      const params = launchEntry?.params || {}

      // a. Check all symbols still free (race-condition guard)
      const blockedSymbols = []
      for (const sym of symbols) {
        if (!(await isSymbolFree(sym))) blockedSymbols.push(sym)
      }
      if (blockedSymbols.length) {
        errors.push({ strategy: stratName, error: `Symbols locked: ${blockedSymbols.join(', ')} — stop existing sessions first` })
        continue
      }

      // Resolve risk parameters for this specific chaos strategy and symbols
      const resolvedRisk = {}
      for (const sym of symbols) {
        resolvedRisk[sym] = resolveStrategyRiskParams(stratName, sym, savedSettings, {
          ...riskOverride,
          leverage: Number(leverage) || 1
        })
      }
      resolvedRisk.default = resolveStrategyRiskParams(stratName, null, savedSettings, {
        ...riskOverride,
        leverage: Number(leverage) || 1
      })

      // b. Create session in MongoDB
      let session
      try {
        session = await LiveSession.create({
          userId:       req.user.id,
          strategyId:   String(strategy._id),
          strategyName: stratName,
          symbols,
          timeframe,
          params,
          capital:    String(capital),
          leverage:   Number(leverage),
          riskParams: resolvedRisk,
          status:     'starting',
          mode:       'paper',
        })
      } catch (dbErr) {
        errors.push({ strategy: stratName, error: `DB create failed: ${dbErr.message}` })
        continue
      }

      // c. Lock all symbols for this session
      const lockedSoFar = []
      let lockFailed = false
      try {
        for (const sym of symbols) {
          await lockSymbol(sym, 'bot', String(session._id))
          lockedSoFar.push(sym)
        }
      } catch (lockErr) {
        for (const s of lockedSoFar) await releaseSymbolLock(s, String(session._id)).catch(() => {})
        await LiveSession.findByIdAndDelete(session._id)
        errors.push({ strategy: stratName, error: `Symbol lock failed: ${lockErr.message}` })
        lockFailed = true
      }
      if (lockFailed) continue

      // d. Call engine to start the session
      try {
        await engineClient.post('/algo/sessions', {
          session_id:    String(session._id),
          strategy_name: stratName,
          symbols,
          timeframe,
          params,
          capital:       String(capital),
          leverage:      Number(leverage),
          fee_rate:      feeRate,
          risk_params:   resolvedRisk,
          user_id:       String(req.user.id),
          api_key:       chaosApiKey,
          api_secret:    chaosApiSecret,
        })
        await LiveSession.findByIdAndUpdate(session._id, { status: 'running' })
        created.push({ strategy: stratName, sessionId: String(session._id), symbols, status: 'running' })
      } catch (engineErr) {
        for (const sym of symbols) await releaseSymbolLock(sym, String(session._id)).catch(() => {})
        await LiveSession.findByIdAndUpdate(session._id, { status: 'error', errorMessage: engineErr.message })
        errors.push({ strategy: stratName, error: `Engine start failed: ${engineErr.message}` })
      }
    }

    // ── 7. Respond ──────────────────────────────────────────────────────────
    const statusCode = errors.length && created.length === 0 ? 502 : 207
    res.status(statusCode).json(ApiResponse.success({
      launched: created,
      errors,
      dropped,
      note: '⚡ Chaos Mode — testnet-only. All sessions run on Binance Testnet (mode:paper). Stop with DELETE /api/v1/algo/sessions.',
    }))
  } catch (err) {
    next(err)
  }
}

// GET /api/v1/algo/chaos/symbols
async function getChaosSymbols(req, res, next) {
  try {
    const tiered = await getTIERED_SYMBOLS()
    res.json(ApiResponse.success({ tieredSymbols: tiered }))
  } catch (err) {
    next(err)
  }
}

// POST /api/v1/algo/pairlist/preview
async function previewPairlist(req, res, next) {
  try {
    const { config } = req.body
    const payload = { config: config ? JSON.stringify(config) : '{}' }
    const { data } = await engineClient.post('/algo/pairlist/preview', payload)
    res.json(ApiResponse.success(data?.data || data))
  } catch (err) {
    next(err)
  }
}

module.exports = {
  startSession,
  stopSession,
  setTradingState,
  listSessions,
  getSession,
  getLockedSymbols,
  getSessionEquity,
  handleEngineStats,
  handleAlgoPlaceOrder,
  handleAlgoClosePosition,
  handleAlgoSetLeverage,
  handleAlgoGetPosition,
  handleAlgoGetOpenOrders,
  handleEngineStartup,
  deleteSession,
  deleteAllStopped,
  startChaos,
  getChaosSymbols,
  previewPairlist,
}

// ── Internal handlers for real Binance order placement ──────────────────────
// These are called by the Python engine, not the browser client.

async function _getBinanceHeaders(sessionId) {
  const Settings = require('../models/Settings')
  const { decrypt } = require('../utils/encryption')

  const session = await LiveSession.findById(sessionId).select('userId').lean()
  if (!session?.userId) throw new Error(`Session ${sessionId} has no userId`)

  const settings = await Settings.findOne({ userId: session.userId })
  const apiKey = settings?.encryptedApiKey ? decrypt(settings.encryptedApiKey) : ''
  const apiSecret = settings?.encryptedApiSecret ? decrypt(settings.encryptedApiSecret) : ''

  if (!apiKey || !apiSecret) throw new Error(`No Binance credentials configured for session ${sessionId}`)

  return {
    'X-Binance-API-Key': apiKey,
    'X-Binance-API-Secret': apiSecret,
    'X-Binance-Mode': settings?.mode || 'testnet',
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

    const headers = await _getBinanceHeaders(req.params.id)

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

    const headers = await _getBinanceHeaders(req.params.id)

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

    const headers = await _getBinanceHeaders(req.params.id)

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

// POST /internal/algo/engine-startup
async function handleEngineStartup(req, res, next) {
  try {
    const { reconcileSymbolLocks } = require('../services/reconciliation')
    await reconcileSymbolLocks()
    res.json({ success: true, message: 'Reconciliation complete' })
  } catch (err) {
    console.error('[Startup] Engine notification reconciliation failed:', err.message)
    res.status(500).json({ success: false, error: err.message })
  }
}
