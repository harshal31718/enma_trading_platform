/**
 * Plan 5 Step 5.5 (ENG-11): `computeSymbolStats` (`algo.controller.js`)
 * aggregates via real MongoDB $sum/$toDecimal — Decimal128 exact-decimal
 * summation itself is a documented MongoDB server feature, not something
 * this test re-proves. What this test guards is the code around it: the
 * pipeline shape sent to Mongo, and that Decimal128 results are converted
 * to plain JS numbers before being returned (SessionCard.jsx's
 * `a + s.realisedPnl` reduce does real numeric arithmetic on this field —
 * a leftover Decimal128 object or a string would silently break it: object
 * concatenation or "0" + "12.34" string concatenation instead of addition).
 *
 * mongodb-memory-server (declared in package.json for exactly this kind of
 * test) cannot run in this container — there is no official MongoDB build
 * for Alpine, the server image's base (confirmed while writing this test:
 * `UnknownLinuxDistro: Unknown/unsupported linux "alpine"`). Mocking
 * `TradeRecord.aggregate` with realistic Decimal128-shaped stand-ins (an
 * object exposing `.toString()`, exactly Mongoose's own return shape) is
 * the next-best hermetic check available in this environment.
 */
// algo.controller.js transitively requires ../services/symbolLock ->
// ../config/redis, which opens a real ioredis connection at module-load
// time unless mocked (same open-handle-hangs-Jest fix as
// symbolLock.test.js / reconciliation.test.js earlier this session).
jest.mock('../../config/redis', () => new (require('ioredis-mock'))())
jest.mock('../../services/engineClient', () => ({ post: jest.fn(), get: jest.fn() }))
jest.mock('../../models/TradeRecord', () => ({ aggregate: jest.fn() }))

const TradeRecord = require('../../models/TradeRecord')
const { computeSymbolStats } = require('../algo.controller')

// Stand-in for a BSON Decimal128 as returned by mongoose's aggregate() —
// the real object's only contract computeSymbolStats relies on is toString().
function fakeDecimal128(value) {
  return { toString: () => String(value) }
}

describe('computeSymbolStats (Plan 5.5 Decimal128 aggregation)', () => {
  afterEach(() => jest.clearAllMocks())

  test('converts Decimal128-shaped aggregation results to plain numbers', async () => {
    TradeRecord.aggregate.mockResolvedValue([
      { _id: 'BTCUSDT', trades: 3, qty: fakeDecimal128('3.00000000'), notional: fakeDecimal128('150.5'), realisedPnl: fakeDecimal128('12.34'), leverage: 10 },
    ])

    const stats = await computeSymbolStats('sess1')

    expect(typeof stats.BTCUSDT.qty).toBe('number')
    expect(typeof stats.BTCUSDT.notional).toBe('number')
    expect(typeof stats.BTCUSDT.realisedPnl).toBe('number')
    expect(stats.BTCUSDT.qty).toBe(3)
    expect(stats.BTCUSDT.notional).toBe(150.5)
    expect(stats.BTCUSDT.realisedPnl).toBe(12.34)
    expect(stats.BTCUSDT.trades).toBe(3)
    expect(stats.BTCUSDT.leverage).toBe(10)
  })

  test('the exact SessionCard.jsx consumption shape: numeric addition, not string concatenation', async () => {
    TradeRecord.aggregate.mockResolvedValue([
      { _id: 'BTCUSDT', trades: 1, qty: fakeDecimal128('1'), notional: fakeDecimal128('100'), realisedPnl: fakeDecimal128('12.34'), leverage: null },
    ])

    const stats = await computeSymbolStats('sess1')

    expect(0 + stats.BTCUSDT.realisedPnl).toBe(12.34) // would be "012.34" if this regressed to a string
  })

  test('groups multiple symbols independently', async () => {
    TradeRecord.aggregate.mockResolvedValue([
      { _id: 'BTCUSDT', trades: 2, qty: fakeDecimal128('2'), notional: fakeDecimal128('200'), realisedPnl: fakeDecimal128('10'), leverage: 5 },
      { _id: 'ETHUSDT', trades: 1, qty: fakeDecimal128('1'), notional: fakeDecimal128('50'), realisedPnl: fakeDecimal128('-5'), leverage: 3 },
    ])

    const stats = await computeSymbolStats('sess1')

    expect(stats.BTCUSDT.realisedPnl).toBe(10)
    expect(stats.ETHUSDT.realisedPnl).toBe(-5)
  })

  test('null leverage falls back to null, not 0 or undefined', async () => {
    TradeRecord.aggregate.mockResolvedValue([
      { _id: 'BTCUSDT', trades: 1, qty: fakeDecimal128('1'), notional: fakeDecimal128('100'), realisedPnl: fakeDecimal128('0'), leverage: null },
    ])

    const stats = await computeSymbolStats('sess1')

    expect(stats.BTCUSDT.leverage).toBeNull()
  })

  test('the aggregation pipeline sums via $toDecimal, not $toDouble (the ENG-11 fix)', async () => {
    TradeRecord.aggregate.mockResolvedValue([])

    await computeSymbolStats('sess1')

    const pipeline = TradeRecord.aggregate.mock.calls[0][0]
    const groupStage = pipeline.find(stage => stage.$group)
    expect(JSON.stringify(groupStage)).toContain('$toDecimal')
    expect(JSON.stringify(groupStage)).not.toContain('$toDouble')
  })

  test('scopes the match stage to the given sessionId', async () => {
    TradeRecord.aggregate.mockResolvedValue([])

    await computeSymbolStats('sess_specific')

    const pipeline = TradeRecord.aggregate.mock.calls[0][0]
    const matchStage = pipeline.find(stage => stage.$match)
    expect(matchStage.$match.sessionId).toBe('sess_specific')
  })
})
