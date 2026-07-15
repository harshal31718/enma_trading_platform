const requireInternalKey = require('../requireInternalKey')

describe('requireInternalKey (SEC-1 / SEC-8)', () => {
  const ORIGINAL = process.env.INTERNAL_API_KEY
  afterEach(() => { process.env.INTERNAL_API_KEY = ORIGINAL })

  test('rejects with 500 when INTERNAL_API_KEY is not configured on the server', () => {
    delete process.env.INTERNAL_API_KEY
    const req = { headers: {} }
    const next = jest.fn()
    requireInternalKey(req, {}, next)
    expect(next).toHaveBeenCalledWith(expect.objectContaining({ statusCode: 500 }))
  })

  test('rejects with 401 when no key header is present', () => {
    process.env.INTERNAL_API_KEY = 'correct-secret'
    const req = { headers: {} }
    const next = jest.fn()
    requireInternalKey(req, {}, next)
    expect(next).toHaveBeenCalledWith(expect.objectContaining({ statusCode: 401 }))
  })

  test('rejects with 401 on a wrong key', () => {
    process.env.INTERNAL_API_KEY = 'correct-secret'
    const req = { headers: { 'x-internal-key': 'wrong-secret' } }
    const next = jest.fn()
    requireInternalKey(req, {}, next)
    expect(next).toHaveBeenCalledWith(expect.objectContaining({ statusCode: 401 }))
  })

  test('rejects with 401 on a key of different length (no crash)', () => {
    process.env.INTERNAL_API_KEY = 'correct-secret'
    const req = { headers: { 'x-internal-key': 'short' } }
    const next = jest.fn()
    expect(() => requireInternalKey(req, {}, next)).not.toThrow()
    expect(next).toHaveBeenCalledWith(expect.objectContaining({ statusCode: 401 }))
  })

  test('calls next() with no error on the correct key', () => {
    process.env.INTERNAL_API_KEY = 'correct-secret'
    const req = { headers: { 'x-internal-key': 'correct-secret' } }
    const next = jest.fn()
    requireInternalKey(req, {}, next)
    expect(next).toHaveBeenCalledWith()
  })
})
