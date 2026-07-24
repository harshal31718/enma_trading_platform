// Plan 6 Step 6.5 (ENG-16): eventStreamConsumer.js consumes the engine's
// algo:events Redis Stream in place of the old fire-and-forget HTTP PATCH.
// Requiring the module opens a real ioredis connection at module-load time
// (mirrors socketEmitter.js's own "separate connection" convention) unless
// mocked — same gotcha documented in reconciliation.test.js/symbolLock.test.js.
// ioredis-mock doesn't implement XGROUP/XREADGROUP/XACK (confirmed by hand
// against the running server container), so these tests exercise the pure
// applyEntry/processBatch logic directly with injected fakes rather than
// going through the real consumer-group commands.
jest.mock('ioredis', () => require('ioredis-mock'))
jest.mock('../algoSessionService', () => ({ processEngineStatsUpdate: jest.fn() }))
jest.mock('../../config/socket', () => ({ getIO: jest.fn(() => 'fake-io') }))

const { processEngineStatsUpdate } = require('../algoSessionService')
const { _internal } = require('../eventStreamConsumer')
const { applyEntry, processBatch, claimStalePending, STREAM_KEY, GROUP_NAME, CONSUMER_NAME } = _internal

beforeEach(() => {
  processEngineStatsUpdate.mockClear()
})

describe('applyEntry', () => {
  test('parses flat ioredis stream fields and calls processEngineStatsUpdate', async () => {
    const fields = ['sessionId', 'sess1', 'payload', JSON.stringify({ pnl: 5, event: 'log' })]
    await applyEntry('1234-0', fields)

    expect(processEngineStatsUpdate).toHaveBeenCalledTimes(1)
    expect(processEngineStatsUpdate).toHaveBeenCalledWith({
      id: 'sess1',
      body: { pnl: 5, event: 'log' },
      io: 'fake-io',
    })
  })

  test('skips (does not call processEngineStatsUpdate) when sessionId is missing', async () => {
    const fields = ['payload', JSON.stringify({ pnl: 5 })]
    await applyEntry('1234-0', fields)
    expect(processEngineStatsUpdate).not.toHaveBeenCalled()
  })

  test('skips when payload is missing', async () => {
    const fields = ['sessionId', 'sess1']
    await applyEntry('1234-0', fields)
    expect(processEngineStatsUpdate).not.toHaveBeenCalled()
  })

  test('skips without throwing when payload is unparseable JSON', async () => {
    const fields = ['sessionId', 'sess1', 'payload', '{not-json']
    await expect(applyEntry('1234-0', fields)).resolves.toBeUndefined()
    expect(processEngineStatsUpdate).not.toHaveBeenCalled()
  })

  test('propagates a processEngineStatsUpdate failure to the caller', async () => {
    processEngineStatsUpdate.mockRejectedValueOnce(new Error('mongo down'))
    const fields = ['sessionId', 'sess1', 'payload', JSON.stringify({ pnl: 1 })]
    await expect(applyEntry('1234-0', fields)).rejects.toThrow('mongo down')
  })
})

describe('processBatch', () => {
  function fakeClient() {
    return { xack: jest.fn().mockResolvedValue(1) }
  }

  test('acks every entry that applies successfully', async () => {
    const client = fakeClient()
    const entries = [
      ['1-0', ['sessionId', 'sessA', 'payload', JSON.stringify({ event: 'log' })]],
      ['2-0', ['sessionId', 'sessB', 'payload', JSON.stringify({ event: 'log' })]],
    ]
    await processBatch(entries, client)

    expect(processEngineStatsUpdate).toHaveBeenCalledTimes(2)
    expect(client.xack).toHaveBeenCalledTimes(2)
    expect(client.xack).toHaveBeenNthCalledWith(1, STREAM_KEY, GROUP_NAME, '1-0')
    expect(client.xack).toHaveBeenNthCalledWith(2, STREAM_KEY, GROUP_NAME, '2-0')
  })

  test('does not ack an entry whose apply failed, but still processes the rest', async () => {
    const client = fakeClient()
    processEngineStatsUpdate
      .mockRejectedValueOnce(new Error('mongo down'))
      .mockResolvedValueOnce({ success: true })
    const entries = [
      ['1-0', ['sessionId', 'sessA', 'payload', JSON.stringify({ event: 'log' })]],
      ['2-0', ['sessionId', 'sessB', 'payload', JSON.stringify({ event: 'log' })]],
    ]
    await processBatch(entries, client)

    expect(processEngineStatsUpdate).toHaveBeenCalledTimes(2)
    // Only the second entry (which succeeded) gets acked — the first stays
    // in the pending list for redelivery.
    expect(client.xack).toHaveBeenCalledTimes(1)
    expect(client.xack).toHaveBeenCalledWith(STREAM_KEY, GROUP_NAME, '2-0')
  })

  test('acks a malformed entry (skip-and-ack, not retry-forever)', async () => {
    const client = fakeClient()
    const entries = [['1-0', ['payload', JSON.stringify({ event: 'log' })]]] // no sessionId
    await processBatch(entries, client)

    expect(processEngineStatsUpdate).not.toHaveBeenCalled()
    expect(client.xack).toHaveBeenCalledWith(STREAM_KEY, GROUP_NAME, '1-0')
  })
})

describe('claimStalePending', () => {
  // Regression: this consumer's name used to be process.pid-based, so every
  // nodemon restart in this dev environment abandoned the prior process's
  // pending entries under a name no future process would ever read again —
  // confirmed live via XPENDING showing entries stuck under a dead
  // consumer name. XAUTOCLAIM reassigns entries regardless of which
  // consumer (dead or alive) currently holds them, fixing that.

  test('claims entries from a single XAUTOCLAIM page and processes them', async () => {
    const entries = [['1-0', ['sessionId', 'sessA', 'payload', JSON.stringify({ event: 'log' })]]]
    const client = {
      xautoclaim: jest.fn().mockResolvedValue(['0', entries]),
      xack: jest.fn().mockResolvedValue(1),
    }

    await claimStalePending(client)

    expect(client.xautoclaim).toHaveBeenCalledWith(
      STREAM_KEY, GROUP_NAME, CONSUMER_NAME, expect.any(Number), '0', 'COUNT', expect.any(Number)
    )
    expect(processEngineStatsUpdate).toHaveBeenCalledTimes(1)
    expect(client.xack).toHaveBeenCalledWith(STREAM_KEY, GROUP_NAME, '1-0')
  })

  test('pages through multiple XAUTOCLAIM cursors until the cursor returns to 0', async () => {
    const page1 = [['1-0', ['sessionId', 'sessA', 'payload', JSON.stringify({ event: 'log' })]]]
    const page2 = [['2-0', ['sessionId', 'sessB', 'payload', JSON.stringify({ event: 'log' })]]]
    const client = {
      xautoclaim: jest.fn()
        .mockResolvedValueOnce(['17-0', page1])   // more pages follow
        .mockResolvedValueOnce(['0', page2]),      // final page
      xack: jest.fn().mockResolvedValue(1),
    }

    await claimStalePending(client)

    expect(client.xautoclaim).toHaveBeenCalledTimes(2)
    expect(client.xautoclaim.mock.calls[1][4]).toBe('17-0') // second call continues from the first cursor
    expect(processEngineStatsUpdate).toHaveBeenCalledTimes(2)
    expect(client.xack).toHaveBeenCalledWith(STREAM_KEY, GROUP_NAME, '1-0')
    expect(client.xack).toHaveBeenCalledWith(STREAM_KEY, GROUP_NAME, '2-0')
  })

  test('does nothing when there is no stale-pending backlog', async () => {
    const client = {
      xautoclaim: jest.fn().mockResolvedValue(['0', []]),
      xack: jest.fn(),
    }

    await claimStalePending(client)

    expect(processEngineStatsUpdate).not.toHaveBeenCalled()
    expect(client.xack).not.toHaveBeenCalled()
  })
})
