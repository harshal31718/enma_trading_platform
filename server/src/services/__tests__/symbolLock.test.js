/**
 * Plan 8.6 (SYS-7) verification: two sessions on one account must not both
 * hold the same symbol. `symbolLock.js`'s atomic Redis `SET NX` is the
 * mechanism `algo.controller.js`'s startSession/startChaos already lean on
 * for this (checked 2026-07-18 while scoping 8.6) — this test proves the
 * primitive itself is race-safe, independent of the full controller.
 */
jest.mock('../../config/redis', () => new (require('ioredis-mock'))())

const { lockSymbol, releaseSymbolLock, isSymbolFree, getSymbolLock } = require('../symbolLock')

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
