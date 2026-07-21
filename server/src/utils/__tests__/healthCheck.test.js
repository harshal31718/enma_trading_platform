/**
 * Plan 8 Step 8.7 (SEC-8): GET /api/v1/health previously opened (and tore
 * down) a brand-new `ioredis` connection on every single request instead of
 * reusing the shared `config/redis.js` singleton. Tested here directly
 * against the extracted check functions — requiring the full `app.js` pulls
 * in BullMQ queues / socketEmitter.js's own real Redis connection, unrelated
 * heavy machinery for what should be a fast, hermetic unit test.
 */
const { checkMongoHealth, checkRedisHealth } = require('../healthCheck')

describe('checkRedisHealth', () => {
  test('reuses whatever client it is given — calls .ping() on it directly, no new client', async () => {
    const fakeClient = { ping: jest.fn().mockResolvedValue('PONG') }
    const result = await checkRedisHealth(fakeClient)
    expect(result).toBe('connected')
    expect(fakeClient.ping).toHaveBeenCalledTimes(1)
  })

  test('returns "error" when the client rejects', async () => {
    const fakeClient = { ping: jest.fn().mockRejectedValue(new Error('connection refused')) }
    const result = await checkRedisHealth(fakeClient)
    expect(result).toBe('error')
  })

  test('returns "error" (does not hang) when the client never resolves', async () => {
    const fakeClient = { ping: jest.fn(() => new Promise(() => {})) } // never settles
    const result = await checkRedisHealth(fakeClient, 50)
    expect(result).toBe('error')
  })
})

describe('checkMongoHealth', () => {
  test('returns "disconnected" when readyState is not 1', async () => {
    const fakeConnection = { readyState: 0 }
    const result = await checkMongoHealth(fakeConnection)
    expect(result).toBe('disconnected')
  })

  test('returns "connected" when readyState is 1 and ping succeeds', async () => {
    const command = jest.fn().mockResolvedValue({ ok: 1 })
    const fakeConnection = { readyState: 1, db: { admin: () => ({ command }) } }
    const result = await checkMongoHealth(fakeConnection)
    expect(result).toBe('connected')
    expect(command).toHaveBeenCalledWith({ ping: 1 })
  })

  test('returns "error" when readyState is 1 but the ping command fails', async () => {
    const command = jest.fn().mockRejectedValue(new Error('mongo down'))
    const fakeConnection = { readyState: 1, db: { admin: () => ({ command }) } }
    const result = await checkMongoHealth(fakeConnection)
    expect(result).toBe('error')
  })
})
