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

    // 1. Stop orphaned active sessions (server/engine restarted mid-run)
    const orphanedSessions = await LiveSession.find({
      status: { $in: ['running', 'starting', 'stopping'] }
    }).lean()

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
      }).catch(() => {})

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
          await releaseSymbolLock(symbol).catch(() => {})
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
              await lockSymbol(pos.symbol, 'manual').catch(() => {})
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

module.exports = { reconcileSymbolLocks, reconcileFullAccountPositions }
