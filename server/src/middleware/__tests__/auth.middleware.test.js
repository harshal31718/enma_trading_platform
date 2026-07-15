jest.mock('jsonwebtoken')
jest.mock('../../models/User')

const jwt = require('jsonwebtoken')
const User = require('../../models/User')
const { verifyJWT, requireAdmin, requireAlgoAccess } = require('../auth.middleware')

function mockRes() {
  return {}
}

describe('verifyJWT', () => {
  const OLD_ENV = process.env.JWT_SECRET
  beforeAll(() => { process.env.JWT_SECRET = 'test-secret' })
  afterAll(() => { process.env.JWT_SECRET = OLD_ENV })
  afterEach(() => jest.clearAllMocks())

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
