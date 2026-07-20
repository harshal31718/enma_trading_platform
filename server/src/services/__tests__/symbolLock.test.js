/**
 * Plan 8.6 (SYS-7) verification: two sessions on one account must not both
 * hold the same symbol. `symbolLock.js`'s atomic Redis `SET NX` is the
 * mechanism `algo.controller.js`'s startSession/startChaos already lean on
 * for this (checked 2026-07-18 while scoping 8.6) — this test proves the
 * primitive itself is race-safe, independent of the full controller.
 */
jest.mock('../../config/redis', () => new (require('ioredis-mock'))())

const {
  lockSymbol, releaseSymbolLock, isSymbolFree, getSymbolLock,
  assertSymbolNotBotLocked, assertSymbolLockedByBotSession,
} = require('../symbolLock')

describe('symbolLock — same-symbol overlap rejection (Plan 8.6)', () => {
  const SYMBOL = 'BTCUSDT'

  afterEach(async () => {
    await releaseSymbolLock(SYMBOL)
  })

  test('a second session cannot lock a symbol the first session already holds', async () => {
    await lockSymbol(SYMBOL, 'bot', 'session-A')
    await expect(lockSymbol(SYMBOL, 'bot', 'session-B')).rejects.toMatchObject({ statusCode: 409, code: 'SYMBOL_LOCKED' })
  })

  test('the lock records which session owns it, for the rejection message', async () => {
    await lockSymbol(SYMBOL, 'bot', 'session-A')
    const lock = await getSymbolLock(SYMBOL)
    expect(lock.sessionId).toBe('session-A')
    expect(lock.reason).toBe('bot')
  })

  test('a session cannot release a lock it does not own (no accidental unlock by a losing session)', async () => {
    await lockSymbol(SYMBOL, 'bot', 'session-A')
    await releaseSymbolLock(SYMBOL, 'session-B') // no-op, mismatched sessionId
    expect(await isSymbolFree(SYMBOL)).toBe(false)
  })

  test('after the owning session releases, a new session can acquire the symbol', async () => {
    await lockSymbol(SYMBOL, 'bot', 'session-A')
    await releaseSymbolLock(SYMBOL, 'session-A')
    expect(await isSymbolFree(SYMBOL)).toBe(true)
    await expect(lockSymbol(SYMBOL, 'bot', 'session-B')).resolves.toBeUndefined()
  })

  test('two concurrent lock attempts for the same symbol: exactly one wins', async () => {
    const results = await Promise.allSettled([
      lockSymbol(SYMBOL, 'bot', 'session-A'),
      lockSymbol(SYMBOL, 'bot', 'session-B'),
    ])
    const fulfilled = results.filter(r => r.status === 'fulfilled')
    const rejected = results.filter(r => r.status === 'rejected')
    expect(fulfilled).toHaveLength(1)
    expect(rejected).toHaveLength(1)
    expect(rejected[0].reason).toMatchObject({ statusCode: 409, code: 'SYMBOL_LOCKED' })
  })
})

// Plan 7 Step 7.1 (SRV-1) third slice: manual-trading (trade.controller.js)
// and engine-callback (algo.controller.js) guards, extracted out of 3x/4x
// identical inline duplication. Behavior-preserving — same 409/SYMBOL_LOCKED
// shape, same message text, the inline `if (...) throw/return next(...)`
// blocks they replaced.
describe('assertSymbolNotBotLocked (manual-trading guard)', () => {
  const SYMBOL = 'BTCUSDT'
  afterEach(async () => { await releaseSymbolLock(SYMBOL) })

  test('resolves (no throw) when the symbol is unlocked', async () => {
    await expect(assertSymbolNotBotLocked(SYMBOL)).resolves.toBeUndefined()
  })

  test('resolves when the symbol is manually locked (only bot locks block manual trading)', async () => {
    await lockSymbol(SYMBOL, 'manual')
    await expect(assertSymbolNotBotLocked(SYMBOL)).resolves.toBeUndefined()
  })

  test('throws 409 SYMBOL_LOCKED with the "close through the bot page" message by default', async () => {
    await lockSymbol(SYMBOL, 'bot', 'session-A')
    await expect(assertSymbolNotBotLocked(SYMBOL)).rejects.toMatchObject({
      statusCode: 409, code: 'SYMBOL_LOCKED',
      message: `Symbol ${SYMBOL} is locked by an active bot session. Close it through the bot page or wait for the bot to close it.`,
    })
  })

  test('throws the "cannot be closed manually" message when closing:true', async () => {
    await lockSymbol(SYMBOL, 'bot', 'session-A')
    await expect(assertSymbolNotBotLocked(SYMBOL, { closing: true })).rejects.toMatchObject({
      statusCode: 409, code: 'SYMBOL_LOCKED',
      message: `Symbol ${SYMBOL} is locked by an active bot session and cannot be closed manually.`,
    })
  })
})

describe('assertSymbolLockedByBotSession (engine-callback ownership guard)', () => {
  const SYMBOL = 'ETHUSDT'
  afterEach(async () => { await releaseSymbolLock(SYMBOL) })

  test('resolves when the lock belongs to this exact bot session', async () => {
    await lockSymbol(SYMBOL, 'bot', 'session-A')
    await expect(assertSymbolLockedByBotSession(SYMBOL, 'session-A')).resolves.toBeUndefined()
  })

  test('throws when the symbol has no lock at all', async () => {
    await expect(assertSymbolLockedByBotSession(SYMBOL, 'session-A')).rejects.toMatchObject({
      statusCode: 409, code: 'SYMBOL_LOCKED', message: `Symbol ${SYMBOL} is not locked by this bot session.`,
    })
  })

  test('throws when the lock belongs to a different bot session', async () => {
    await lockSymbol(SYMBOL, 'bot', 'session-A')
    await expect(assertSymbolLockedByBotSession(SYMBOL, 'session-B')).rejects.toMatchObject({
      statusCode: 409, code: 'SYMBOL_LOCKED',
    })
  })

  test('throws when the lock is a manual (not bot) lock', async () => {
    await lockSymbol(SYMBOL, 'manual')
    await expect(assertSymbolLockedByBotSession(SYMBOL, 'session-A')).rejects.toMatchObject({
      statusCode: 409, code: 'SYMBOL_LOCKED',
    })
  })
})
