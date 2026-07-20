jest.mock('jsonwebtoken')
jest.mock('../../models/User')

const jwt = require('jsonwebtoken')
const User = require('../../models/User')
const { verifyJWT, requireAdmin, requireAlgoAccess, invalidateUserCache, _clearUserCacheForTests } = require('../auth.middleware')

function mockRes() {
  return {}
}

describe('verifyJWT', () => {
  const OLD_ENV = process.env.JWT_SECRET
  beforeAll(() => { process.env.JWT_SECRET = 'test-secret' })
  afterAll(() => { process.env.JWT_SECRET = OLD_ENV })
  afterEach(() => {
    jest.clearAllMocks()
    // The user-lookup cache (Plan 7 Step 7.3) is module-scoped state that
    // outlives any single test — several cases below reuse userId 'abc123'
    // with a different User.findById mock each time, so a stale cache entry
    // from a prior test would silently short-circuit the next one.
    _clearUserCacheForTests()
  })

  test('rejects with 401 when no cookie is present', async () => {
    const req = { cookies: {} }
    const next = jest.fn()
    await verifyJWT(req, mockRes(), next)
    expect(next).toHaveBeenCalledWith(expect.objectContaining({ statusCode: 401 }))
  })

  test('rejects with 401 when the JWT is invalid/expired', async () => {
    jwt.verify.mockImplementation(() => { throw new Error('invalid token') })
    const req = { cookies: { enma_jwt: 'garbage' } }
    const next = jest.fn()
    await verifyJWT(req, mockRes(), next)
    expect(next).toHaveBeenCalledWith(expect.objectContaining({ statusCode: 401 }))
  })

  test('rejects with 401 when the decoded user no longer exists', async () => {
    jwt.verify.mockReturnValue({ userId: 'abc123' })
    User.findById.mockReturnValue({ lean: () => Promise.resolve(null) })
    const req = { cookies: { enma_jwt: 'valid' } }
    const next = jest.fn()
    await verifyJWT(req, mockRes(), next)
    expect(next).toHaveBeenCalledWith(expect.objectContaining({ statusCode: 401 }))
  })

  test('rejects with 401 when the user is inactive', async () => {
    jwt.verify.mockReturnValue({ userId: 'abc123' })
    User.findById.mockReturnValue({
      lean: () => Promise.resolve({ _id: 'abc123', isActive: false }),
    })
    const req = { cookies: { enma_jwt: 'valid' } }
    const next = jest.fn()
    await verifyJWT(req, mockRes(), next)
    expect(next).toHaveBeenCalledWith(expect.objectContaining({ statusCode: 401 }))
  })

  test('attaches req.user and calls next() with no error on a valid token', async () => {
    jwt.verify.mockReturnValue({ userId: 'abc123' })
    User.findById.mockReturnValue({
      lean: () => Promise.resolve({ _id: { toString: () => 'abc123' }, isActive: true, role: 'user' }),
    })
    const req = { cookies: { enma_jwt: 'valid' } }
    const next = jest.fn()
    await verifyJWT(req, mockRes(), next)
    expect(next).toHaveBeenCalledWith() // called with no arguments = success
    expect(req.user.id).toBe('abc123')
  })

  // Plan 7 Step 7.3 (SRV-4): infra failure (DB down) must be distinguishable
  // from auth failure (bad token) — a 401 here would send a client through
  // a useless re-login loop when the real problem is Mongo being unreachable.
  test('rejects with 503, not 401, when the DB lookup itself throws (infra failure)', async () => {
    jwt.verify.mockReturnValue({ userId: 'abc123' })
    User.findById.mockReturnValue({ lean: () => Promise.reject(new Error('Mongo unreachable')) })
    const req = { cookies: { enma_jwt: 'valid' } }
    const next = jest.fn()
    await verifyJWT(req, mockRes(), next)
    expect(next).toHaveBeenCalledWith(expect.objectContaining({ statusCode: 503, code: 'SERVICE_UNAVAILABLE' }))
  })

  test('a bad token still yields 401, not 503 — the two failure modes stay distinct', async () => {
    jwt.verify.mockImplementation(() => { throw new Error('jwt malformed') })
    const req = { cookies: { enma_jwt: 'garbage' } }
    const next = jest.fn()
    await verifyJWT(req, mockRes(), next)
    expect(next).toHaveBeenCalledWith(expect.objectContaining({ statusCode: 401 }))
    expect(User.findById).not.toHaveBeenCalled()
  })

  describe('short-TTL user cache', () => {
    test('a second request for the same user within the TTL skips User.findById', async () => {
      jwt.verify.mockReturnValue({ userId: 'abc123' })
      User.findById.mockReturnValue({
        lean: () => Promise.resolve({ _id: { toString: () => 'abc123' }, isActive: true, role: 'user' }),
      })
      const req1 = { cookies: { enma_jwt: 'valid' } }
      await verifyJWT(req1, mockRes(), jest.fn())
      expect(User.findById).toHaveBeenCalledTimes(1)

      const req2 = { cookies: { enma_jwt: 'valid' } }
      const next2 = jest.fn()
      await verifyJWT(req2, mockRes(), next2)
      expect(User.findById).toHaveBeenCalledTimes(1) // still 1 — served from cache
      expect(next2).toHaveBeenCalledWith()
      expect(req2.user.id).toBe('abc123')
    })

    test('two concurrent requests never share the same req.user object reference', async () => {
      jwt.verify.mockReturnValue({ userId: 'abc123' })
      User.findById.mockReturnValue({
        lean: () => Promise.resolve({ _id: { toString: () => 'abc123' }, isActive: true, role: 'user' }),
      })
      const req1 = { cookies: { enma_jwt: 'valid' } }
      const req2 = { cookies: { enma_jwt: 'valid' } }
      await verifyJWT(req1, mockRes(), jest.fn())
      await verifyJWT(req2, mockRes(), jest.fn())
      expect(req1.user).not.toBe(req2.user)
    })

    test('invalidateUserCache forces the next request to re-read from Mongo (grant/revoke applies immediately)', async () => {
      jwt.verify.mockReturnValue({ userId: 'abc123' })
      User.findById.mockReturnValue({
        lean: () => Promise.resolve({ _id: { toString: () => 'abc123' }, isActive: true, algoAccess: { status: 'none' } }),
      })
      await verifyJWT({ cookies: { enma_jwt: 'valid' } }, mockRes(), jest.fn())
      expect(User.findById).toHaveBeenCalledTimes(1)

      invalidateUserCache('abc123')
      User.findById.mockReturnValue({
        lean: () => Promise.resolve({ _id: { toString: () => 'abc123' }, isActive: true, algoAccess: { status: 'granted' } }),
      })
      const req2 = { cookies: { enma_jwt: 'valid' } }
      await verifyJWT(req2, mockRes(), jest.fn())
      expect(User.findById).toHaveBeenCalledTimes(2) // cache bypassed, fresh read
      expect(req2.user.algoAccess.status).toBe('granted')
    })
  })
})

describe('requireAdmin', () => {
  test('passes through for an admin user', () => {
    const req = { user: { role: 'admin' } }
    const next = jest.fn()
    requireAdmin(req, mockRes(), next)
    expect(next).toHaveBeenCalledWith()
  })

  test('rejects with 403 for a non-admin user', () => {
    const req = { user: { role: 'user' } }
    const next = jest.fn()
    requireAdmin(req, mockRes(), next)
    expect(next).toHaveBeenCalledWith(expect.objectContaining({ statusCode: 403 }))
  })
})

describe('requireAlgoAccess', () => {
  test('admins always pass regardless of algoAccess status', () => {
    const req = { user: { role: 'admin', algoAccess: { status: 'none' } } }
    const next = jest.fn()
    requireAlgoAccess(req, mockRes(), next)
    expect(next).toHaveBeenCalledWith()
  })

  test('a granted non-admin user passes', () => {
    const req = { user: { role: 'user', algoAccess: { status: 'granted' } } }
    const next = jest.fn()
    requireAlgoAccess(req, mockRes(), next)
    expect(next).toHaveBeenCalledWith()
  })

  test('a requested (not yet granted) user is rejected with 403', () => {
    const req = { user: { role: 'user', algoAccess: { status: 'requested' } } }
    const next = jest.fn()
    requireAlgoAccess(req, mockRes(), next)
    expect(next).toHaveBeenCalledWith(expect.objectContaining({ statusCode: 403, code: 'ALGO_ACCESS_REQUIRED' }))
  })

  test('absence of algoAccess is treated as no access', () => {
    const req = { user: { role: 'user' } }
    const next = jest.fn()
    requireAlgoAccess(req, mockRes(), next)
    expect(next).toHaveBeenCalledWith(expect.objectContaining({ statusCode: 403 }))
  })
})
