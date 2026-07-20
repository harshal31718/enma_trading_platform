// Plan 7 Step 7.1 (SRV-1): unit tests for the shared logic pulled out of
// startSession/startChaos (algo.controller.js) — credential resolution,
// capital over-commit checking, concurrent-bot-cap counting, and the
// per-symbol risk-params cascade. Behavior-preserving extraction, so these
// tests assert the SAME contracts the inline blocks they replaced had.
jest.mock('../engineClient', () => ({ get: jest.fn(), post: jest.fn() }))
jest.mock('../../models/Settings', () => ({ findOne: jest.fn() }))
jest.mock('../../models/LiveSession', () => ({
  find: jest.fn(), countDocuments: jest.fn(), findById: jest.fn(), findByIdAndUpdate: jest.fn(),
}))
jest.mock('../../models/TradeRecord', () => ({ aggregate: jest.fn() }))
jest.mock('../../utils/encryption', () => ({ decrypt: jest.fn() }))
jest.mock('../../utils/risk', () => ({
  resolveStrategyRiskParams: jest.fn((strategyName, symbol) => ({ strategyName, symbol })),
}))
// processEngineStatsUpdate pulls in symbolLock -> config/redis, which opens a
// real ioredis connection at module-load time unless mocked (same
// open-handle-hangs-Jest fix as symbolLock.test.js). Mocking symbolLock
// directly (rather than config/redis) also gives releaseSymbolLock a
// controllable jest.fn() for the error/stopped-event tests below.
jest.mock('../symbolLock', () => ({ releaseSymbolLock: jest.fn().mockResolvedValue(undefined) }))
jest.mock('../../utils/webhook', () => ({ dispatchWebhook: jest.fn() }))

const engineClient = require('../engineClient')
const Settings = require('../../models/Settings')
const LiveSession = require('../../models/LiveSession')
const TradeRecord = require('../../models/TradeRecord')
const { decrypt } = require('../../utils/encryption')
const { resolveStrategyRiskParams } = require('../../utils/risk')
const { releaseSymbolLock } = require('../symbolLock')
const { dispatchWebhook } = require('../../utils/webhook')
const {
  resolveBinanceCredentials, checkCapitalOverCommit, checkConcurrentBotCap, buildRiskParamsCascade,
  processEngineStatsUpdate,
} = require('../algoSessionService')

beforeEach(() => {
  jest.clearAllMocks()
  decrypt.mockImplementation((v) => `decrypted:${v}`)
})

describe('resolveBinanceCredentials', () => {
  test('throws NO_CREDENTIALS when Settings has no key/secret', async () => {
    Settings.findOne.mockReturnValue({ lean: () => Promise.resolve({}) })
    await expect(resolveBinanceCredentials('u1')).rejects.toMatchObject({
      statusCode: 400, code: 'NO_CREDENTIALS',
    })
  })

  test('throws NO_CREDENTIALS when Settings document itself is missing', async () => {
    Settings.findOne.mockReturnValue({ lean: () => Promise.resolve(null) })
    await expect(resolveBinanceCredentials('u1')).rejects.toMatchObject({ code: 'NO_CREDENTIALS' })
  })

  test('returns decrypted credentials + the raw settings doc when present', async () => {
    Settings.findOne.mockReturnValue({
      lean: () => Promise.resolve({ encryptedApiKey: 'ek', encryptedApiSecret: 'es', takerFee: 0.001 }),
    })
    const result = await resolveBinanceCredentials('u1')
    expect(result).toEqual({
      savedSettings: { encryptedApiKey: 'ek', encryptedApiSecret: 'es', takerFee: 0.001 },
      apiKey: 'decrypted:ek',
      apiSecret: 'decrypted:es',
    })
  })
})

describe('checkCapitalOverCommit', () => {
  function mockRunningSessions(sessions) {
    LiveSession.find.mockReturnValue({ lean: () => Promise.resolve(sessions) })
  }

  test('not over-commit when requested + reserved fits under available balance', async () => {
    mockRunningSessions([{ capital: '100' }])
    engineClient.get.mockResolvedValue({ data: { data: { availableBalance: 1000 } } })
    const result = await checkCapitalOverCommit({
      userId: 'u1', requestedCapital: 500, apiKey: 'k', apiSecret: 's',
    })
    expect(result.checked).toBe(true)
    expect(result.overCommit).toBe(false)
    expect(result.reservedCapital).toBe(100)
    expect(result.totalCommitted).toBe(600)
  })

  test('flags over-commit when requested + reserved exceeds available balance', async () => {
    mockRunningSessions([{ capital: '900' }])
    engineClient.get.mockResolvedValue({ data: { data: { availableBalance: 1000 } } })
    const result = await checkCapitalOverCommit({
      userId: 'u1', requestedCapital: 500, apiKey: 'k', apiSecret: 's',
    })
    expect(result.checked).toBe(true)
    expect(result.overCommit).toBe(true)
    expect(result.totalCommitted).toBe(1400)
    expect(result.availableBalance).toBe(1000)
  })

  test('never guesses — a failed balance fetch yields checked:false, not a false accept/reject', async () => {
    mockRunningSessions([])
    engineClient.get.mockRejectedValue(new Error('network blip'))
    const result = await checkCapitalOverCommit({
      userId: 'u1', requestedCapital: 500, apiKey: 'k', apiSecret: 's',
    })
    expect(result.checked).toBe(false)
    expect(result.overCommit).toBe(false)
    expect(result.availableBalance).toBeNull()
  })

  test('non-numeric stored capital on other sessions is treated as 0, not NaN', async () => {
    mockRunningSessions([{ capital: 'not-a-number' }, { capital: '50' }])
    engineClient.get.mockResolvedValue({ data: { data: { availableBalance: 1000 } } })
    const result = await checkCapitalOverCommit({
      userId: 'u1', requestedCapital: 100, apiKey: 'k', apiSecret: 's',
    })
    expect(result.reservedCapital).toBe(50)
  })
})

describe('checkConcurrentBotCap', () => {
  test('atCap is false with slots remaining', async () => {
    LiveSession.countDocuments.mockResolvedValue(3)
    const result = await checkConcurrentBotCap({ userId: 'u1', maxConcurrentBots: 10 })
    expect(result).toEqual({ runningCount: 3, availableSlots: 7, atCap: false })
  })

  test('atCap is true exactly at the limit (matches startSession\'s ">=" semantics)', async () => {
    LiveSession.countDocuments.mockResolvedValue(10)
    const result = await checkConcurrentBotCap({ userId: 'u1', maxConcurrentBots: 10 })
    expect(result.atCap).toBe(true)
    expect(result.availableSlots).toBe(0)
  })

  test('atCap is true over the limit', async () => {
    LiveSession.countDocuments.mockResolvedValue(12)
    const result = await checkConcurrentBotCap({ userId: 'u1', maxConcurrentBots: 10 })
    expect(result.atCap).toBe(true)
    expect(result.availableSlots).toBe(-2)
  })
})

describe('buildRiskParamsCascade', () => {
  test('builds one entry per symbol plus a default entry, threading leverage/override through', () => {
    const result = buildRiskParamsCascade({
      strategyName: 'MicroScalper',
      symbols: ['BTCUSDT', 'ETHUSDT'],
      savedSettings: { some: 'settings' },
      riskOverride: { riskPct: 0.02 },
      leverage: 5,
    })
    expect(Object.keys(result)).toEqual(['BTCUSDT', 'ETHUSDT', 'default'])
    expect(resolveStrategyRiskParams).toHaveBeenCalledWith(
      'MicroScalper', 'BTCUSDT', { some: 'settings' }, { riskPct: 0.02, leverage: 5 },
    )
    expect(resolveStrategyRiskParams).toHaveBeenCalledWith(
      'MicroScalper', null, { some: 'settings' }, { riskPct: 0.02, leverage: 5 },
    )
  })

  test('leverage defaults to 1 when not a finite number', () => {
    buildRiskParamsCascade({
      strategyName: 'X', symbols: ['BTCUSDT'], savedSettings: {}, riskOverride: {}, leverage: undefined,
    })
    expect(resolveStrategyRiskParams).toHaveBeenCalledWith('X', 'BTCUSDT', {}, { leverage: 1 })
  })
})

describe('processEngineStatsUpdate', () => {
  // Mirrors the write-call shapes the real Mongoose query object supports —
  // `await findByIdAndUpdate(...)` directly (writes) and
  // `await findByIdAndUpdate(...).lean()` (the one read at the top).
  function fakeWriteQuery(result) {
    const p = Promise.resolve(result)
    p.lean = () => Promise.resolve(result)
    return p
  }
  function fakeFindByIdQuery(result) {
    return { select: () => ({ lean: () => Promise.resolve(result) }), lean: () => Promise.resolve(result) }
  }
  function makeIo() {
    const emit = jest.fn()
    const io = { to: jest.fn(() => ({ emit })), emit }
    return io
  }
  const baseSession = {
    _id: 's1', userId: 'u1', status: 'running', pnl: '10', openPositions: 1,
    capital: '1000', strategyName: 'MicroScalper', symbols: ['BTCUSDT'],
  }

  beforeEach(() => {
    LiveSession.findById.mockReturnValue(fakeFindByIdQuery(null))
    LiveSession.findByIdAndUpdate.mockImplementation(() => fakeWriteQuery(baseSession))
    TradeRecord.aggregate.mockResolvedValue([])
  })

  test('stale seq is rejected without touching the DB write or emitting', async () => {
    LiveSession.findById.mockReturnValue(fakeFindByIdQuery({ lastSeqBySymbol: { BTCUSDT: 5 } }))
    const io = makeIo()
    const result = await processEngineStatsUpdate({
      id: 's1', io,
      body: { seq: 5, event: 'position:open', eventData: { symbol: 'BTCUSDT' } },
    })
    expect(result).toEqual({ success: true, rejected: 'stale_seq' })
    expect(LiveSession.findByIdAndUpdate).not.toHaveBeenCalled()
    expect(io.to).not.toHaveBeenCalled()
  })

  test('a newer seq than lastSeq is accepted (not rejected)', async () => {
    LiveSession.findById.mockReturnValue(fakeFindByIdQuery({ lastSeqBySymbol: { BTCUSDT: 5 } }))
    const io = makeIo()
    const result = await processEngineStatsUpdate({
      id: 's1', io,
      body: { seq: 6, event: 'position:open', eventData: { symbol: 'BTCUSDT', side: 'long', qty: 1, price: 100 } },
    })
    expect(result).toEqual({ success: true })
  })

  test('session not found after update short-circuits before any socket emit', async () => {
    LiveSession.findByIdAndUpdate.mockImplementation(() => fakeWriteQuery(null))
    const io = makeIo()
    const result = await processEngineStatsUpdate({ id: 's1', io, body: { pnl: '5' } })
    expect(result).toEqual({ success: true })
    expect(io.to).not.toHaveBeenCalled()
  })

  test('always emits algo:session:update with status/pnl/openPositions', async () => {
    const io = makeIo()
    await processEngineStatsUpdate({ id: 's1', io, body: { pnl: '10' } })
    expect(io.to).toHaveBeenCalledWith('user:u1')
    expect(io.emit).toHaveBeenCalledWith('algo:session:update', {
      sessionId: 's1', status: 'running', pnl: '10', openPositions: 1,
    })
  })

  test('position:open emits open events, persists positionDetails, dispatches entry_fill webhook', async () => {
    const io = makeIo()
    await processEngineStatsUpdate({
      id: 's1', io,
      body: { event: 'position:open', eventData: { symbol: 'BTCUSDT', side: 'long', qty: 1, price: 100, leverage: 10 } },
    })
    expect(io.emit).toHaveBeenCalledWith('algo:position:open', expect.objectContaining({ sessionId: 's1', symbol: 'BTCUSDT' }))
    expect(dispatchWebhook).toHaveBeenCalledWith('u1', 'entry_fill', expect.objectContaining({ symbol: 'BTCUSDT', side: 'long' }))
  })

  test('position:close dispatches exit_fill (+liquidation), pushes trade history, recomputes symbolStats', async () => {
    TradeRecord.aggregate.mockResolvedValue([{ _id: 'BTCUSDT', trades: 1, qty: { toString: () => '1' }, notional: { toString: () => '100' }, realisedPnl: { toString: () => '5' }, leverage: 10 }])
    const io = makeIo()
    await processEngineStatsUpdate({
      id: 's1', io,
      body: { event: 'position:close', eventData: { symbol: 'BTCUSDT', pnl: '5', exitPrice: 105, exitReason: 'liquidation' } },
    })
    expect(dispatchWebhook).toHaveBeenCalledWith('u1', 'exit_fill', expect.objectContaining({ symbol: 'BTCUSDT', pnl: '5' }))
    expect(dispatchWebhook).toHaveBeenCalledWith('u1', 'liquidation', expect.objectContaining({ symbol: 'BTCUSDT' }))
    expect(io.emit).toHaveBeenCalledWith('algo:session:update', expect.objectContaining({
      sessionId: 's1', symbolStats: { BTCUSDT: { trades: 1, qty: 1, notional: 100, realisedPnl: 5, leverage: 10 } },
    }))
  })

  test('status:error emits an error log, dispatches session_error, and releases every symbol lock', async () => {
    const io = makeIo()
    await processEngineStatsUpdate({ id: 's1', io, body: { status: 'error', errorMessage: 'boom' } })
    expect(io.emit).toHaveBeenCalledWith('algo:session:log', expect.objectContaining({ type: 'error', message: 'boom' }))
    expect(dispatchWebhook).toHaveBeenCalledWith('u1', 'session_error', expect.objectContaining({ error: 'boom' }))
    expect(releaseSymbolLock).toHaveBeenCalledWith('BTCUSDT', 's1')
  })

  test('event:log pushes and emits the log entry', async () => {
    const io = makeIo()
    await processEngineStatsUpdate({ id: 's1', io, body: { event: 'log', eventData: { type: 'info', message: 'hi' } } })
    expect(io.emit).toHaveBeenCalledWith('algo:session:log', expect.objectContaining({ type: 'info', message: 'hi' }))
  })

  test('risk_breach updates tradingState, emits update+log, dispatches risk_breach webhook, defaults unknown newState to reducing', async () => {
    const io = makeIo()
    await processEngineStatsUpdate({
      id: 's1', io,
      body: { event: 'risk_breach', eventData: { checkName: 'maxDrawdown', reason: 'breached', newState: 'not_a_real_state' } },
    })
    expect(io.emit).toHaveBeenCalledWith('algo:session:update', { sessionId: 's1', tradingState: 'reducing' })
    expect(dispatchWebhook).toHaveBeenCalledWith('u1', 'risk_breach', expect.objectContaining({ newState: 'reducing' }))
  })

  test('event:stopped dispatches session_stop, recomputes symbolStats, and releases all remaining locks', async () => {
    LiveSession.findById.mockReturnValue(fakeFindByIdQuery({ symbols: ['BTCUSDT', 'ETHUSDT'] }))
    const io = makeIo()
    await processEngineStatsUpdate({ id: 's1', io, body: { event: 'stopped' } })
    expect(dispatchWebhook).toHaveBeenCalledWith('u1', 'session_stop', expect.objectContaining({ sessionId: 's1' }))
    expect(releaseSymbolLock).toHaveBeenCalledWith('BTCUSDT', 's1')
    expect(releaseSymbolLock).toHaveBeenCalledWith('ETHUSDT', 's1')
  })

  test('a socket emit throwing is caught — the response is still {success:true}, never propagated', async () => {
    const io = { to: jest.fn(() => { throw new Error('socket boom') }) }
    const result = await processEngineStatsUpdate({ id: 's1', io, body: { pnl: '10' } })
    expect(result).toEqual({ success: true })
  })

  test('positionDetails on the body is copied into the update, per-symbol', async () => {
    const io = makeIo()
    await processEngineStatsUpdate({
      id: 's1', io,
      body: { positionDetails: { BTCUSDT: { side: 'long', qty: 1 } } },
    })
    expect(LiveSession.findByIdAndUpdate).toHaveBeenCalledWith(
      's1', expect.objectContaining({ positionDetails: { BTCUSDT: { side: 'long', qty: 1 } } }), { new: true },
    )
  })

  test('a symbolStats aggregation failure on position:close is logged, not thrown', async () => {
    TradeRecord.aggregate.mockRejectedValue(new Error('mongo down'))
    const io = makeIo()
    const result = await processEngineStatsUpdate({
      id: 's1', io,
      body: { event: 'position:close', eventData: { symbol: 'BTCUSDT', pnl: '5', exitPrice: 105, exitReason: 'tp' } },
    })
    expect(result).toEqual({ success: true })
  })

  test('a symbolStats aggregation failure on stopped is logged, not thrown', async () => {
    LiveSession.findById.mockReturnValue(fakeFindByIdQuery({ symbols: [] }))
    TradeRecord.aggregate.mockRejectedValue(new Error('mongo down'))
    const io = makeIo()
    const result = await processEngineStatsUpdate({ id: 's1', io, body: { event: 'stopped' } })
    expect(result).toEqual({ success: true })
  })
})
