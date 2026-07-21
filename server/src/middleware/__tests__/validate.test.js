const { z } = require('zod')
const validate = require('../validate')

function makeReqRes(body) {
  const req = { body }
  const res = {}
  const next = jest.fn()
  return { req, res, next }
}

describe('validate middleware', () => {
  const schema = z.object({
    name: z.string().min(1),
    count: z.number().optional(),
  })

  test('calls next() with no error and replaces req.body with the parsed data on success', () => {
    const { req, res, next } = makeReqRes({ name: 'x', count: 5 })
    validate(schema)(req, res, next)
    expect(next).toHaveBeenCalledWith()
    expect(req.body).toEqual({ name: 'x', count: 5 })
  })

  test('calls next(ApiError) with a 400 VALIDATION_ERROR on a missing required field', () => {
    const { req, res, next } = makeReqRes({})
    validate(schema)(req, res, next)
    expect(next).toHaveBeenCalledTimes(1)
    const err = next.mock.calls[0][0]
    expect(err.statusCode).toBe(400)
    expect(err.code).toBe('VALIDATION_ERROR')
    expect(err.message).toMatch(/name/)
  })

  test('calls next(ApiError) on a wrong-typed field', () => {
    const { req, res, next } = makeReqRes({ name: 'x', count: 'not-a-number' })
    validate(schema)(req, res, next)
    const err = next.mock.calls[0][0]
    expect(err.statusCode).toBe(400)
    expect(err.code).toBe('VALIDATION_ERROR')
  })

  test('validates req.query when source is set to "query"', () => {
    const req = { query: { limit: 'abc' } }
    const next = jest.fn()
    validate(z.object({ limit: z.string() }), 'query')(req, {}, next)
    expect(next).toHaveBeenCalledWith()
    expect(req.query).toEqual({ limit: 'abc' })
  })
})
