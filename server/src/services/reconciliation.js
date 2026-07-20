const { lockSymbol, releaseSymbolLock, getSymbolLock, getAllLockedSymbols } = require('./symbolLock')
const engineClient = require('./engineClient')
const LiveSession = require('../models/LiveSession')
const Settings = require('../models/Settings')
const { decrypt } = require('../utils/encryption')
const { getIO } = require('../config/socket')

// Resolve a user's testnet Binance headers from their Settings doc — the same
// per-user, AES-encrypted credential store the Settings UI writes to. Never
// reads `.env` (see DECISIONS.md §9: credentials live in MongoDB per user, not
// `.env`). Results are cached for the duration of one reconciliation pass.
// Mode is pinned to testnet (trading is testnet-only; mainnet keys are read-only).
async function _testnetHeadersFor(userId, cache) {
  if (!userId) return null
  if (cache.has(userId)) return cache.get(userId)

  let headers = null
  try {
    const settings = await Settings.findOne({ userId }).lean()
    const apiKey = settings?.encryptedApiKey ? decrypt(settings.encryptedApiKey) : ''
    const apiSecret = settings?.encryptedApiSecret ? decrypt(settings.encryptedApiSecret) : ''
    if (apiKey && apiSecret) {
      headers = {
        'X-Binance-API-Key': apiKey,
        'X-Binance-API-Secret': apiSecret,
        'X-Binance-Mode': 'testnet',
      }
    }
  } catch {
    headers = null
  }

  cache.set(userId, headers)
  return headers
}

// Plan 5 Step 5.6 (ENG-7): opt-in, default OFF (2026-07-18 user decision — see
// workspace/plan/5_live-trading-state-integrity.md). When true, an orphaned
// session (server/engine restarted mid-run) is resumed instead of stopped
// and flattened — the engine rebuilds its position (exchange truth, via the
// existing reconcile Case 1) and its realized PnL (this session's own
// executionEvents log, via the new `resume: true` flag on POST
// /algo/sessions) rather than losing state. Any resume failure for a given
// session (missing credentials, engine rejects the request, network error)
// falls through to the existing stop+flatten path for THAT session only —
// resume is a best-effort upgrade, never a reason to leave a session's real
// exchange positions untracked.
const RESUME_SESSIONS_ON_RESTART = process.env.RESUME_SESSIONS_ON_RESTART === 'true'

// Raw decrypted credentials (not header-shaped) for the engine's POST
// /algo/sessions body — separate cache from _testnetHeadersFor's header
// shape since resume needs api_key/api_secret as plain fields, plus the
// saved taker fee rate (startSession's original call site reads this from
// the same Settings doc; resume must reconstruct it the same way since
// LiveSession itself never persists feeRate).
async function _rawCredsFor(userId, cache) {
  if (!userId) return null
  if (cache.has(userId)) return cache.get(userId)

  let creds = null
  try {
    const settings = await Settings.findOne({ userId }).lean()
    const apiKey = settings?.encryptedApiKey ? decrypt(settings.encryptedApiKey) : ''
    const apiSecret = settings?.encryptedApiSecret ? decrypt(settings.encryptedApiSecret) : ''
    if (apiKey && apiSecret) {
      creds = { apiKey, apiSecret, feeRate: settings?.takerFee ?? 0.0005 }
    }
  } catch {
    creds = null
  }

  cache.set(userId, creds)
  return creds
}

// Attempt to resume one orphaned session. Returns true on success (caller
// must NOT also run the stop+flatten path for it), false on any failure
// (caller falls through to stop+flatten as normal). Deliberately does not
// touch Redis symbol locks either way — if Redis itself survived the
// restart (the common case; only the server/engine process died), this
// session's locks are already exactly where they should be. Re-acquiring
// them here would incorrectly self-collide with the lock this same session
// already holds. The rare double-failure case (Redis *also* lost its data)
// is a known, undocumented-further limitation of this opt-in v1 — a new
// session could theoretically race a resumed one for the same symbol until
// the resumed session's own next candle-loop iteration re-establishes truth
// via the exchange reconcile.
async function _tryResumeSession(session, credsCache) {
  const creds = await _rawCredsFor(session.userId, credsCache)
  if (!creds) return false
  try {
    await engineClient.post('/algo/sessions', {
      session_id: String(session._id),
      strategy_name: session.strategyName,
      symbols: session.symbols,
      timeframe: session.timeframe,
      params: session.params || {},
      capital: String(session.capital),
      leverage: Number(session.leverage) || 1,
      fee_rate: creds.feeRate,
      risk_params: session.riskParams || {},
      user_id: String(session.userId),
      api_key: creds.apiKey,
      api_secret: creds.apiSecret,
      resume: true,
    })
    return true
  } catch (e) {
    console.error(`[Startup] Resume failed for session ${session._id}, falling back to stop+flatten: ${e.message}`)
    return false
  }
}

// Run `task` over `items` with at most `limit` promises in flight at once.
// Keeps startup responsive: a Chaos session can hold hundreds of symbols, and
// firing every close-position call serially (or all at once) stalls the event
// loop long enough to fail the health check.
async function runBounded(items, limit, task) {
  const queue = [...items]
  const workers = Array.from({ length: Math.min(limit, queue.length) }, async () => {
    while (queue.length) {
      await task(queue.shift())
    }
  })
  await Promise.all(workers)
}

async function reconcileSymbolLocks() {
  try {
    // Per-pass cache of userId → decrypted testnet headers (from Settings).
    const headerCache = new Map()

    // 1. Stop orphaned active sessions (server/engine restarted mid-run) —
    //    OR resume them, if RESUME_SESSIONS_ON_RESTART is opted in (5.6).
    let orphanedSessions = await LiveSession.find({
      status: { $in: ['running', 'starting', 'stopping'] }
    }).lean()

    if (RESUME_SESSIONS_ON_RESTART) {
      // A session already mid-stop when the crash happened was stopping on
      // purpose — respect that intent, never resume it. Only running/starting
      // sessions are resume candidates.
      const resumeCandidates = orphanedSessions.filter(s => s.status !== 'stopping')
      const credsCache = new Map()
      const resumedIds = new Set()
      for (const session of resumeCandidates) {
        const resumed = await _tryResumeSession(session, credsCache)
        if (resumed) {
          resumedIds.add(String(session._id))
          await LiveSession.findByIdAndUpdate(session._id, { status: 'running' }).catch((dbErr) => {
            console.error(`[Startup] Failed to persist resumed status for session ${session._id}:`, dbErr.message)
          })
          console.log(`[Startup] Resumed session ${session._id} from event log + exchange state (RESUME_SESSIONS_ON_RESTART)`)
        }
      }
      if (resumedIds.size > 0) {
        try {
          const io = getIO()
          for (const session of resumeCandidates) {
            if (resumedIds.has(String(session._id))) {
              io.to(`user:${session.userId}`).emit('algo:session:update', {
                sessionId: session._id,
                status: 'running',
                pnl: session.pnl || '0',
                openPositions: session.openPositions || [],
              })
            }
          }
        } catch {
          // socket may not be initialized yet, that's fine
        }
      }
      // Everything NOT successfully resumed (resume off for this run, a
      // 'stopping' session, or a resume attempt that failed) falls through
      // to the existing stop+flatten path below, unchanged.
      orphanedSessions = orphanedSessions.filter(s => !resumedIds.has(String(s._id)))
    }

    // Resolve each owner's *actual* open positions once (a session can hold
    // hundreds of symbols; only a handful ever have a live position). Symbols
    // with no position need no close call at all — this is what turned a big
    // Chaos session into a hundreds-of-serial-calls startup storm.
    const openPositionsFor = new Map() // userId -> Set(symbol with nonzero position)
    for (const session of orphanedSessions) {
      const uid = String(session.userId || '')
      if (!uid || openPositionsFor.has(uid)) continue
      const headers = await _testnetHeadersFor(session.userId, headerCache)
      const owned = new Set()
      if (headers) {
        try {
          const posRes = await engineClient.get('/trade/positions', { headers })
          for (const pos of (posRes.data?.data || [])) {
            if (parseFloat(pos.positionAmt) !== 0) owned.add(pos.symbol)
          }
        } catch {
          // Positions fetch failed (engine down, revoked keys) — nothing to close.
        }
      }
      openPositionsFor.set(uid, owned)
    }

    for (const session of orphanedSessions) {
      const headers = await _testnetHeadersFor(session.userId, headerCache)
      const owned = openPositionsFor.get(String(session.userId || '')) || new Set()

      // Locks are cheap Redis ops — release them all concurrently.
      await Promise.allSettled(session.symbols.map(s => releaseSymbolLock(s)))

      // Close only symbols that actually hold a position, bounded so we never
      // fan out hundreds of Binance calls. Track what's still open as closes
      // fail, so we never write a false "all clear" to Mongo below.
      const stillOpen = new Set(session.symbols.filter(s => owned.has(s)))
      if (headers) {
        await runBounded([...stillOpen], 8, (symbol) =>
          engineClient.post('/trade/close-position', { symbol }, { headers })
            .then(() => { owned.delete(symbol); stillOpen.delete(symbol) })
            .catch((e) => console.log(`[Startup] Close failed for ${symbol}: ${e.message}`))
        )
      }

      // Only now write the session's final state — openPositions reflects
      // whatever couldn't be confirmed closed, never a blanket []. Zeroing
      // this before the close attempts is what orphaned real Binance
      // positions: a failed/never-attempted close would silently vanish
      // from tracking the moment the session was marked stopped.
      await LiveSession.findByIdAndUpdate(session._id, {
        status: 'stopped',
        stoppedAt: new Date(),
        openPositions: [...stillOpen],
        positionDetails: {},
      }).catch((dbErr) => {
        console.error(`[Startup] Failed to persist final stopped state for session ${session._id}:`, dbErr.message)
      })

      if (stillOpen.size > 0) {
        console.error(`[Startup] Session ${session._id}: ${stillOpen.size} symbol(s) failed to confirm-close, may still be open on Binance: ${[...stillOpen].join(', ')}`)
      }

      try {
        const io = getIO()
        io.emit('algo:session:update', {
          sessionId: session._id,
          status: 'stopped',
          pnl: session.pnl || '0',
          openPositions: [...stillOpen],
        })
      } catch (wsErr) {
        // socket may not be initialized yet, that's fine
      }
      console.log(`[Startup] Force-stopped orphaned session ${session._id} (${session.symbols.length} symbols)`)
    }

    // 2. Release bot locks whose session no longer exists in MongoDB.
    const allLocks = await getAllLockedSymbols()
    const botLockSessionIds = [...new Set(
      Object.values(allLocks)
        .filter(l => l.reason === 'bot' && l.sessionId)
        .map(l => l.sessionId)
    )]
    if (botLockSessionIds.length > 0) {
      const existingSessions = await LiveSession.find(
        { _id: { $in: botLockSessionIds } },
        { _id: 1 }
      ).lean()
      const existingIds = new Set(existingSessions.map(s => String(s._id)))
      for (const [symbol, lock] of Object.entries(allLocks)) {
        if (lock.reason === 'bot' && lock.sessionId && !existingIds.has(lock.sessionId)) {
          await releaseSymbolLock(symbol).catch((lockErr) => {
            console.error(`[Startup] Stale bot lock release failed for ${symbol} (session ${lock.sessionId}):`, lockErr.message)
          })
          console.log(`[Startup] Released stale bot lock for ${symbol} (session ${lock.sessionId} deleted)`)
        }
      }
    }

    // 3. Re-lock open manual positions, per user, using each user's own
    //    Settings-stored credentials (never `.env`).
    const keyedUsers = await Settings.find(
      { encryptedApiKey: { $ne: '' }, encryptedApiSecret: { $ne: '' } },
      { userId: 1 }
    ).lean()
    for (const { userId } of keyedUsers) {
      const headers = await _testnetHeadersFor(userId, headerCache)
      if (!headers) continue
      try {
        const posRes = await engineClient.get('/trade/positions', { headers })
        const positions = posRes.data?.data || []
        for (const pos of positions) {
          if (parseFloat(pos.positionAmt) !== 0) {
            const existing = await getSymbolLock(pos.symbol)
            if (!existing) {
              await lockSymbol(pos.symbol, 'manual').catch((lockErr) => {
                console.error(`[Startup] Manual re-lock failed for ${pos.symbol} (user ${userId}):`, lockErr.message)
              })
            }
          }
        }
      } catch {
        // Per-user position fetch may fail (revoked keys, etc.) — skip that user.
      }
    }

    console.log('[Startup] Symbol lock reconciliation complete')
  } catch (err) {
    console.error('[Startup] Lock reconciliation failed:', err.message)
  }
}

// Periodic full-account safety net (F-004): compare each user's *actual*
// Binance positions against everything we know about (active sessions'
// openPositions plus any Redis symbol lock, bot or manual) and flag anything
// with no owner. Neither reconcileSymbolLocks() above nor the engine's own
// stop-session close loop can ever fully guarantee zero orphaned positions —
// this is the backstop that notices instead of letting them accumulate
// silently forever. Alert-only by design: auto-closing a real position from
// an unattended background sweep is a financial action with real consequences
// and is not a decision this reconciliation pass should make unilaterally.
async function reconcileFullAccountPositions() {
  try {
    const headerCache = new Map()
    const keyedUsers = await Settings.find(
      { encryptedApiKey: { $ne: '' }, encryptedApiSecret: { $ne: '' } },
      { userId: 1 }
    ).lean()

    for (const { userId } of keyedUsers) {
      const headers = await _testnetHeadersFor(userId, headerCache)
      if (!headers) continue

      let positions = []
      try {
        const posRes = await engineClient.get('/trade/positions', { headers })
        positions = (posRes.data?.data || []).filter((p) => parseFloat(p.positionAmt) !== 0)
      } catch {
        continue // engine down / revoked keys — nothing to reconcile this pass
      }
      if (positions.length === 0) continue

      const activeSessions = await LiveSession.find(
        { userId, status: { $in: ['running', 'starting', 'stopping'] } },
        { openPositions: 1 }
      ).lean()
      const tracked = new Set(activeSessions.flatMap((s) => s.openPositions || []))
      const allLocks = await getAllLockedSymbols()

      const orphans = positions
        .map((p) => p.symbol)
        .filter((symbol) => !tracked.has(symbol) && !allLocks[symbol])

      if (orphans.length > 0) {
        console.error(
          `[Reconciliation] User ${userId}: ${orphans.length} Binance position(s) with no owning session or lock: ${orphans.join(', ')}`
        )
        try {
          getIO().to(`user:${userId}`).emit('algo:orphaned-positions', { symbols: orphans })
        } catch {
          // socket may not be initialized yet, that's fine
        }
      }
    }
  } catch (err) {
    console.error('[Reconciliation] Full-account sweep failed:', err.message)
  }
}

module.exports = { reconcileSymbolLocks, reconcileFullAccountPositions, _tryResumeSession, _rawCredsFor }
