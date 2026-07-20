// Plan 7 Step 7.1 (SRV-1) fourth slice: unit tests for the shared
// sync-then-read shape pulled out of trade.controller.js's
// getTradeOrders/getTradeExecutions/getTradeTransactions. Behavior-preserving
// extraction, so these assert the same contracts the inline blocks had:
// bulkWrite op shape, degrade-to-synced:false on a failed engine fetch
// (never throw), and the local read always runs regardless of sync outcome.
jest.mock('../engineClient', () => ({ get: jest.fn() }))

const engineClient = require('../engineClient')
const { syncAndListTradeHistory } = require('../tradeHistoryService')

function makeModel(findResult) {
  return {
    modelName: 'FakeModel',
    bulkWrite: jest.fn().mockResolvedValue({}),
    find: jest.fn(() => ({ sort: jest.fn(() => ({ lean: jest.fn().mockResolvedValue(findResult) })) })),
  }
}

describe('syncAndListTradeHistory', () => {
  afterEach(() => jest.clearAllMocks())

  test('bulkWrites one updateOne per engine item, keyed by idField, transformed via `transform`', async () => {
    engineClient.get.mockResolvedValue({
      data: { data: [{ orderId: 'o1', time: 1000 }, { orderId: 'o2', time: 2000 }] },
    })
    const Model = makeModel([])
    await syncAndListTradeHistory({
      Model, engineEndpoint: '/trade/history-orders', headers: { h: 1 }, query: { symbol: 'BTCUSDT' },
      idField: 'orderId', transform: (o) => ({ ...o, time: new Date(o.time) }),
      syncErrorLabel: 'trade orders', readFilter: { userId: 'u1', symbol: 'BTCUSDT' },
    })
    expect(engineClient.get).toHaveBeenCalledWith('/trade/history-orders', {
      headers: { h: 1 }, params: { limit: 100, symbol: 'BTCUSDT' },
    })
    expect(Model.bulkWrite).toHaveBeenCalledWith([
      { updateOne: { filter: { orderId: 'o1' }, update: { $set: { orderId: 'o1', time: new Date(1000) } }, upsert: true } },
      { updateOne: { filter: { orderId: 'o2' }, update: { $set: { orderId: 'o2', time: new Date(2000) } }, upsert: true } },
    ])
  })

  test('skips bulkWrite entirely when the engine returns an empty array', async () => {
    engineClient.get.mockResolvedValue({ data: { data: [] } })
    const Model = makeModel([])
    await syncAndListTradeHistory({
      Model, engineEndpoint: '/e', headers: {}, query: {}, idField: 'id', transform: (x) => x,
      syncErrorLabel: 'x', readFilter: {},
    })
    expect(Model.bulkWrite).not.toHaveBeenCalled()
  })

  test('a malformed (non-array) engine response is treated as no items, not an error', async () => {
    engineClient.get.mockResolvedValue({ data: { data: null } })
    const Model = makeModel([{ id: 'cached' }])
    const result = await syncAndListTradeHistory({
      Model, engineEndpoint: '/e', headers: {}, query: {}, idField: 'id', transform: (x) => x,
      syncErrorLabel: 'x', readFilter: {},
    })
    expect(Model.bulkWrite).not.toHaveBeenCalled()
    expect(result.synced).toBe(true)
    expect(result.items).toEqual([{ id: 'cached' }])
  })

  test('a failed engine fetch degrades to synced:false but still returns the local read (never throws)', async () => {
    engineClient.get.mockRejectedValue(new Error('engine down'))
    const Model = makeModel([{ id: 'local-only' }])
    const result = await syncAndListTradeHistory({
      Model, engineEndpoint: '/e', headers: {}, query: {}, idField: 'id', transform: (x) => x,
      syncErrorLabel: 'executions', readFilter: { userId: 'u1' },
    })
    expect(result).toEqual({ items: [{ id: 'local-only' }], synced: false })
    expect(Model.bulkWrite).not.toHaveBeenCalled()
  })

  test('a bulkWrite failure also degrades to synced:false rather than throwing', async () => {
    engineClient.get.mockResolvedValue({ data: { data: [{ id: 'x1', time: 1 }] } })
    const Model = makeModel([])
    Model.bulkWrite.mockRejectedValue(new Error('mongo write failed'))
    const result = await syncAndListTradeHistory({
      Model, engineEndpoint: '/e', headers: {}, query: {}, idField: 'id', transform: (x) => x,
      syncErrorLabel: 'x', readFilter: {},
    })
    expect(result.synced).toBe(false)
  })

  test('reads from the local collection with exactly the given readFilter, sorted by time desc', async () => {
    const Model = makeModel([{ id: 'a' }])
    engineClient.get.mockResolvedValue({ data: { data: [] } })
    const sortSpy = jest.fn(() => ({ lean: jest.fn().mockResolvedValue([{ id: 'a' }]) }))
    Model.find = jest.fn(() => ({ sort: sortSpy }))
    await syncAndListTradeHistory({
      Model, engineEndpoint: '/e', headers: {}, query: {}, idField: 'id', transform: (x) => x,
      syncErrorLabel: 'x', readFilter: { userId: 'u1', symbol: 'ETHUSDT' },
    })
    expect(Model.find).toHaveBeenCalledWith({ userId: 'u1', symbol: 'ETHUSDT' })
    expect(sortSpy).toHaveBeenCalledWith({ time: -1 })
  })
})
