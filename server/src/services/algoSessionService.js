// Plan 7 Step 7.1 (SRV-1): shared logic pulled out of `startSession` and
// `startChaos` (algo.controller.js), which independently duplicated ~150
// lines of credential resolution, capital over-commit checking, concurrent-
// bot-cap counting, and per-symbol risk-params cascade building. Pure
// extraction — no behavior change; each function here does exactly what the
// inline block it replaces used to do, just once instead of twice.
//
// Deliberately scoped to what startSession/startChaos actually shared, not
// every credential-lookup site in the codebase — `_getBinanceHeaders`
// (algo.controller.js, internal engine-callback routes) and
// `reconciliation.js`'s `_testnetHeadersFor` resolve credentials by
// sessionId/cache rather than by the authenticated request's `userId`, a
// different enough shape that folding them in here would blur this module's
// contract rather than sharpen it — left as a documented follow-up, not
// silently expanded scope.

const Settings = require('../models/Settings')
const LiveSession = require('../models/LiveSession')
const TradeRecord = require('../models/TradeRecord')
const { decrypt } = require('../utils/encryption')
const engineClient = require('./engineClient')
const { resolveStrategyRiskParams } = require('../utils/risk')
const { sumReservedCapital, checkCapitalAgainstBalance } = require('../utils/capitalGate')
const { releaseSymbolLock } = require('./symbolLock')
const { dispatchWebhook } = require('../utils/webhook')
const ApiError = require('../utils/ApiError')
const { isValidSymbolFormat } = require('../utils/symbolFormat')

/**
 * Load this user's saved Settings and decrypt their Binance API credentials.
 * Throws the same `NO_CREDENTIALS` ApiError both call sites already threw.
 *
 * @param {string} userId
 * @returns {Promise<{ savedSettings: object, apiKey: string, apiSecret: string }>}
 */
async function resolveBinanceCredentials(userId) {
  const savedSettings = await Settings.findOne({ userId }).lean() || {}
  const apiKey = savedSettings.encryptedApiKey ? decrypt(savedSettings.encryptedApiKey) : ''
  const apiSecret = savedSettings.encryptedApiSecret ? decrypt(savedSettings.encryptedApiSecret) : ''
  if (!apiKey || !apiSecret) {
    throw new ApiError(400, 'NO_CREDENTIALS', 'Binance API keys not configured. Add them in Settings.')
  }
  return { savedSettings, apiKey, apiSecret }
}

/**
 * Plan 22 Step 22.1 (B-11/B-12): sum this user's other running sessions'
 * reserved capital, fetch their real testnet available balance (best-effort
 * — a failed fetch means "unknown", never a guess), and decide whether
 * `requestedCapital` would over-commit the wallet. Returns the raw check
 * result — callers build their own context-specific error message (the
 * single-session vs Chaos ×N-strategies wording genuinely differs) so this
 * function stays about the computation, not the presentation.
 *
 * @param {object} params
 * @param {string} params.userId
 * @param {number} params.requestedCapital
 * @param {string} params.apiKey
 * @param {string} params.apiSecret
 * @returns {Promise<{ checked: boolean, overCommit: boolean, totalCommitted: number, availableBalance: number|null, reservedCapital: number }>}
 */
async function checkCapitalOverCommit({ userId, requestedCapital, apiKey, apiSecret }) {
  const reservedCapital = sumReservedCapital(
    await LiveSession.find(
      { userId, status: { $in: ['starting', 'running', 'stopping'] } },
      'capital'
    ).lean()
  )
  let availableBalance = null
  try {
    const { data } = await engineClient.get('/trade/account', {
      headers: { 'X-Binance-API-Key': apiKey, 'X-Binance-API-Secret': apiSecret, 'X-Binance-Mode': 'testnet' },
    })
    const parsed = Number(data?.data?.availableBalance)
    if (Number.isFinite(parsed)) availableBalance = parsed
  } catch (balanceErr) {
    // Balance fetch failed — cannot make the over-commit call, don't guess.
  }
  const result = checkCapitalAgainstBalance({ requestedCapital, reservedCapital, availableBalance })
  return { ...result, reservedCapital }
}

/**
 * Count this user's currently running/starting/stopping sessions against
 * their concurrent-bot cap. Returns data only — startSession rejects
 * immediately at the cap, startChaos instead truncates its strategy list to
 * whatever slots remain, so the "what to do about it" stays with the caller.
 *
 * @param {object} params
 * @param {string} params.userId
 * @param {number} params.maxConcurrentBots
 * @returns {Promise<{ runningCount: number, availableSlots: number, atCap: boolean }>}
 */
async function checkConcurrentBotCap({ userId, maxConcurrentBots }) {
  const runningCount = await LiveSession.countDocuments({
    userId,
    status: { $in: ['starting', 'running', 'stopping'] },
  })
  const availableSlots = maxConcurrentBots - runningCount
  return { runningCount, availableSlots, atCap: availableSlots <= 0 }
}

/**
 * Build the per-symbol + `.default` risk-params cascade `LiveSession.riskParams`
 * expects — identical shape whether called once for startSession's whole
 * symbol list or once per strategy inside startChaos's launch loop.
 *
 * @param {object} params
 * @param {string} params.strategyName
 * @param {string[]} params.symbols
 * @param {object} params.savedSettings
 * @param {object} params.riskOverride
 * @param {number} params.leverage
 * @returns {object} { [symbol]: resolvedParams, default: resolvedParams }
 */
function buildRiskParamsCascade({ strategyName, symbols, savedSettings, riskOverride, leverage }) {
  const riskParams = {}
  for (const symbol of symbols) {
    riskParams[symbol] = resolveStrategyRiskParams(strategyName, symbol, savedSettings, {
      ...riskOverride,
      leverage: Number(leverage) || 1,
    })
  }
  riskParams.default = resolveStrategyRiskParams(strategyName, null, savedSettings, {
    ...riskOverride,
    leverage: Number(leverage) || 1,
  })
  return riskParams
}

// Re-derive per-symbol aggregates for a session from the tradeRecords
// collection (the engine is the sole writer). Returns a { symbol: {...} } map.
// Plan 5 Step 5.5 (ENG-11): sums via $toDecimal/Decimal128, not $toDouble —
// a session can accumulate many trade records, and summing that many IEEE-754
// doubles in one aggregation pass is the exact same compounding-float-error
// shape the engine-side `add_money()` fix addresses, just executed by Mongo
// instead of Python. Decimal128 sums exactly, with no term-count-dependent
// drift. Converted back to plain JS numbers before returning/storing —
// deliberately NOT stringified — every existing consumer (SessionCard.jsx's
// `a + s.realisedPnl` reduce, `notional / leverage` margin calc) does real
// numeric arithmetic on these fields and would silently break on a string
// (JS `0 + "12.34"` concatenates instead of adding). This is a precision fix
// at the aggregation boundary, not a type/contract change.
async function computeSymbolStats(sessionId) {
  const rows = await TradeRecord.aggregate([
    { $match: { sessionId: String(sessionId) } },
    { $sort: { exitTime: 1 } },
    {
      $group: {
        _id: '$symbol',
        trades: { $sum: 1 },
        qty: { $sum: { $toDecimal: '$qty' } },
        notional: { $sum: { $multiply: [{ $toDecimal: '$qty' }, { $toDecimal: '$entryPrice' }] } },
        realisedPnl: { $sum: { $toDecimal: '$netPnl' } },
        leverage: { $last: '$leverage' },
      },
    },
  ])
  const stats = {}
  for (const r of rows) {
    stats[r._id] = {
      trades: r.trades,
      qty: Number(r.qty.toString()),
      notional: Number(r.notional.toString()),
      realisedPnl: Number(r.realisedPnl.toString()),
      leverage: r.leverage || null,
    }
  }
  return stats
}

/**
 * PATCH /internal/algo/sessions/:id/stats (called by Engine) — apply a
 * stats update (seq guard, DB fields) and fan it out to the user's
 * Socket.IO room + outbound webhooks. `io` is injected rather than required
 * here so this stays testable without a live Socket.IO server — the
 * controller is the only caller and already holds a live instance via
 * `getIO()`.
 *
 * Pure extraction of the former `algo.controller.js#handleEngineStats` body
 * (minus the outer try/catch → `next(err)`, which stays in the controller).
 * Same status codes, same event shapes, same fire-and-forget webhook calls.
 *
 * @param {object} params
 * @param {string} params.id
 * @param {object} params.body
 * @param {import('socket.io').Server} params.io
 * @returns {Promise<{ success: boolean, rejected?: string }>}
 */
async function processEngineStatsUpdate({ id, body, io }) {
  const { pnl, openPositions, status, event, eventData, positionDetails, seq } = body

  // Plan 8 Step 8.2 (SEC-10): `eventData.symbol` and every `positionDetails`
  // key end up as a Mongo dot-path segment below (`positionDetails.${symbol}`,
  // `lastSeqBySymbol.${symbol}` via $set/$unset) — whitelist them against the
  // real Binance symbol shape before they ever reach a path-building template
  // literal, so a malformed/adversarial symbol (containing '.', '$', or an
  // operator-shaped key) can't be written into an arbitrary document field.
  if (eventData && eventData.symbol !== undefined && !isValidSymbolFormat(eventData.symbol)) {
    throw new ApiError(400, 'VALIDATION_ERROR', `Invalid symbol format: ${JSON.stringify(eventData.symbol)}`)
  }
  if (positionDetails && typeof positionDetails === 'object') {
    for (const sym of Object.keys(positionDetails)) {
      if (!isValidSymbolFormat(sym)) {
        throw new ApiError(400, 'VALIDATION_ERROR', `Invalid symbol format in positionDetails: ${JSON.stringify(sym)}`)
      }
    }
  }

  // Plan 5 Step 5.1 (SYS-2): reject a stale position mutation racing a
  // newer one for the same symbol (e.g. a delayed/retried engine PATCH
  // arriving after a later one already landed). Scoped narrowly to the
  // symbol-mutating position events that carry a `seq` — other fields
  // (status, generic pnl/log updates) are never guarded by this check.
  const seqSymbol = eventData && eventData.symbol
  if (typeof seq === 'number' && seqSymbol && ['position:open', 'position:close', 'position:adjust'].includes(event)) {
    const existing = await LiveSession.findById(id).select('lastSeqBySymbol').lean()
    const lastSeq = existing && existing.lastSeqBySymbol ? existing.lastSeqBySymbol[seqSymbol] : undefined
    if (typeof lastSeq === 'number' && seq <= lastSeq) {
      console.warn(`[AlgoBot] Rejected stale stats update for session ${id} symbol ${seqSymbol}: seq=${seq} <= lastSeq=${lastSeq}`)
      return { success: true, rejected: 'stale_seq' }
    }
  }

  const updateData = {}
  if (typeof seq === 'number' && seqSymbol) updateData[`lastSeqBySymbol.${seqSymbol}`] = seq
  if (pnl !== undefined) updateData.pnl = String(pnl)
  if (openPositions !== undefined) updateData.openPositions = openPositions
  if (status && ['running', 'stopping', 'stopped', 'error'].includes(status)) {
    updateData.status = status
    if (status === 'stopped') updateData.stoppedAt = new Date()
    if (status === 'error' && body.errorMessage) updateData.errorMessage = body.errorMessage
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
    return { success: true }
  }

  // Emit Socket.IO events
  try {
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
      }).catch((dbErr) => {
        console.error(`[AlgoBot] Failed to persist position:open log/snapshot for session ${id}:`, dbErr.message)
      })

      // Plan 14 / F3: fire-and-forget, never awaited/blocking.
      dispatchWebhook(String(session.userId), 'entry_fill', {
        sessionId: id,
        strategy: session.strategyName,
        symbol: eventData.symbol,
        side: eventData.side,
        qty: eventData.qty,
        entryPrice: eventData.price,
        leverage: eventData.leverage,
      })
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
      }).catch((dbErr) => {
        console.error(`[AlgoBot] Failed to persist position:close log/snapshot for session ${id}:`, dbErr.message)
      })

      // Plan 14 / F3: fire-and-forget, never awaited/blocking. `session`
      // here is the pre-`$unset` snapshot fetched above (a plain JS object,
      // unaffected by the DB write that just ran), so positionDetails for
      // this symbol is still the entry-side data we need for the payload.
      const closedPos = session.positionDetails && session.positionDetails[eventData.symbol]
      const exitWebhookPayload = {
        sessionId: id,
        strategy: session.strategyName,
        symbol: eventData.symbol,
        side: closedPos ? closedPos.side : undefined,
        qty: closedPos ? closedPos.qty : undefined,
        entryPrice: closedPos ? closedPos.price : undefined,
        exitPrice: eventData.exitPrice,
        pnl: eventData.pnl,
        exitReason: eventData.exitReason,
      }
      dispatchWebhook(String(session.userId), 'exit_fill', exitWebhookPayload)
      if (eventData.exitReason === 'liquidation') {
        dispatchWebhook(String(session.userId), 'liquidation', exitWebhookPayload)
      }

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
      const errMsg = body.errorMessage || session?.errorMessage || 'Unknown strategy error'
      io.to(userRoom).emit('algo:session:log', {
        sessionId: id,
        timestamp: new Date().toISOString(),
        type: 'error',
        message: errMsg
      })
      // Plan 14 / F3: fire-and-forget, never awaited/blocking.
      dispatchWebhook(String(session.userId), 'session_error', {
        sessionId: id,
        strategy: session.strategyName,
        error: errMsg,
      })
      // Release all symbol locks for errored sessions
      if (session?.symbols) {
        for (const sym of session.symbols) {
          await releaseSymbolLock(sym, id).catch((lockErr) => {
            console.error(`[AlgoBot] Error-status lock release failed for ${sym} (session ${id}):`, lockErr.message)
          })
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
      }).catch((dbErr) => {
        console.error(`[AlgoBot] Failed to persist log entry for session ${id}:`, dbErr.message)
      })
    }

    if (event === 'risk_breach' && eventData) {
      // Plan 22 Step 22.1: Session Risk Governor breach — engine already
      // decided the new trading_state (per DECISIONS.md #23's
      // breach_action config) and, if applicable, auto-flattened. This
      // block just persists/broadcasts it, mirroring setTradingState's
      // shape so the UI's existing tradingState handling picks it up
      // without any new client-side code.
      const newState = ['active', 'reducing', 'halted'].includes(eventData.newState)
        ? eventData.newState
        : 'reducing'
      await LiveSession.findByIdAndUpdate(id, { tradingState: newState }).catch((dbErr) => {
        console.error(`[AlgoBot] Failed to persist tradingState=${newState} for session ${id}:`, dbErr.message)
      })
      io.to(userRoom).emit('algo:session:update', { sessionId: id, tradingState: newState })
      const breachLog = {
        sessionId: id,
        timestamp: new Date().toISOString(),
        type: 'error',
        message: `Risk governor breach (${eventData.checkName}): ${eventData.reason} — trading state -> ${newState}`,
      }
      io.to(userRoom).emit('algo:session:log', breachLog)
      await LiveSession.findByIdAndUpdate(id, {
        $push: { logs: { $each: [{ type: breachLog.type, message: breachLog.message }], $slice: -100 } }
      }).catch((dbErr) => {
        console.error(`[AlgoBot] Failed to persist risk_breach log for session ${id}:`, dbErr.message)
      })

      // Plan 14 / F3: fire-and-forget, never awaited/blocking.
      dispatchWebhook(String(session.userId), 'risk_breach', {
        sessionId: id,
        strategy: session.strategyName,
        checkName: eventData.checkName,
        reason: eventData.reason,
        newState,
      })
    }

    if (event === 'stopped') {
      // Plan 14 / F3: fire-and-forget, never awaited/blocking.
      dispatchWebhook(String(session.userId), 'session_stop', {
        sessionId: id,
        strategy: session.strategyName,
      })

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
          await releaseSymbolLock(sym, id).catch((lockErr) => {
            console.error(`[AlgoBot] Stopped-session lock release failed for ${sym} (session ${id}):`, lockErr.message)
          })
        }
      }
    }
  } catch (socketErr) {
    console.error('[AlgoBot] Socket.IO emit error:', socketErr.message)
  }

  return { success: true }
}

module.exports = {
  resolveBinanceCredentials,
  checkCapitalOverCommit,
  checkConcurrentBotCap,
  buildRiskParamsCascade,
  computeSymbolStats,
  processEngineStatsUpdate,
}
