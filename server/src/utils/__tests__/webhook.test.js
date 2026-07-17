jest.mock('axios')
jest.mock('../../models/Settings')

const axios = require('axios')
const Settings = require('../../models/Settings')
const { dispatchWebhook, sendTestWebhook, VALID_EVENTS } = require('../webhook')

// Plan 14 / fixes-queue F3: dispatchWebhook must NEVER throw and must NEVER
// block the trade path that calls it — a disabled config, an unsubscribed
// event, or a permanently-failing endpoint must all resolve quietly. Mirrors
// the "never throw" contract already established for record_trade/append_event
// on the engine side (Plan 5.1/5.2).

function _mockSettingsFindOne(webhook) {
  Settings.findOne.mockReturnValue({
    select: () => ({
      lean: async () => (webhook === undefined ? null : { webhook }),
    }),
  })
}

describe('dispatchWebhook', () => {
  beforeEach(() => {
    jest.clearAllMocks()
  })

  test('no-op when webhook is disabled', async () => {
    _mockSettingsFindOne({ enabled: false, url: 'https://example.com/hook', events: ['exit_fill'] })
    await dispatchWebhook('user1', 'exit_fill', { symbol: 'BTCUSDT' })
    expect(axios.post).not.toHaveBeenCalled()
  })

  test('no-op when no url is configured', async () => {
    _mockSettingsFindOne({ enabled: true, url: '', events: ['exit_fill'] })
    await dispatchWebhook('user1', 'exit_fill', { symbol: 'BTCUSDT' })
    expect(axios.post).not.toHaveBeenCalled()
  })

  test('no-op when the event is not in the subscribed events list', async () => {
    _mockSettingsFindOne({ enabled: true, url: 'https://example.com/hook', events: ['session_error'] })
    await dispatchWebhook('user1', 'exit_fill', { symbol: 'BTCUSDT' })
    expect(axios.post).not.toHaveBeenCalled()
  })

  test('no-op when Settings document does not exist for the user', async () => {
    _mockSettingsFindOne(undefined)
    await dispatchWebhook('user1', 'exit_fill', { symbol: 'BTCUSDT' })
    expect(axios.post).not.toHaveBeenCalled()
  })

  test('dispatches a JSON POST when enabled and event is subscribed', async () => {
    _mockSettingsFindOne({
      enabled: true, url: 'https://example.com/hook', format: 'json',
      events: ['exit_fill'], retries: 2, timeoutMs: 5000,
    })
    axios.post.mockResolvedValueOnce({ status: 200 })

    await dispatchWebhook('user1', 'exit_fill', { symbol: 'BTCUSDT', pnl: '12.34' })

    expect(axios.post).toHaveBeenCalledTimes(1)
    const [url, body, config] = axios.post.mock.calls[0]
    expect(url).toBe('https://example.com/hook')
    expect(body).toMatchObject({ event: 'exit_fill', symbol: 'BTCUSDT', pnl: '12.34' })
    expect(body.ts).toEqual(expect.any(String))
    expect(config).toMatchObject({ timeout: 5000, headers: { 'Content-Type': 'application/json' } })
  })

  test('dispatches a form-encoded POST when format is "form"', async () => {
    _mockSettingsFindOne({
      enabled: true, url: 'https://example.com/hook', format: 'form',
      events: ['exit_fill'], retries: 0, timeoutMs: 5000,
    })
    axios.post.mockResolvedValueOnce({ status: 200 })

    await dispatchWebhook('user1', 'exit_fill', { symbol: 'BTCUSDT' })

    expect(axios.post).toHaveBeenCalledTimes(1)
    const [, body] = axios.post.mock.calls[0]
    expect(body).toBeInstanceOf(URLSearchParams)
    expect(body.get('symbol')).toBe('BTCUSDT')
    expect(body.get('event')).toBe('exit_fill')
  })

  test('a failing endpoint retries up to the configured count, then swallows the error (never throws)', async () => {
    _mockSettingsFindOne({
      enabled: true, url: 'https://example.com/hook', format: 'json',
      events: ['exit_fill'], retries: 2, timeoutMs: 5000,
    })
    axios.post.mockRejectedValue(new Error('ECONNREFUSED'))

    await expect(
      dispatchWebhook('user1', 'exit_fill', { symbol: 'BTCUSDT' })
    ).resolves.toBeUndefined()

    // retries: 2 => 1 initial attempt + 2 retries = 3 total calls
    expect(axios.post).toHaveBeenCalledTimes(3)
  })

  test('succeeds on a later attempt without retrying further once it lands', async () => {
    _mockSettingsFindOne({
      enabled: true, url: 'https://example.com/hook', format: 'json',
      events: ['exit_fill'], retries: 2, timeoutMs: 5000,
    })
    axios.post
      .mockRejectedValueOnce(new Error('timeout'))
      .mockResolvedValueOnce({ status: 200 })

    await dispatchWebhook('user1', 'exit_fill', { symbol: 'BTCUSDT' })
    expect(axios.post).toHaveBeenCalledTimes(2)
  })

  test('never throws even if the Settings lookup itself fails', async () => {
    Settings.findOne.mockImplementation(() => { throw new Error('mongo down') })
    await expect(
      dispatchWebhook('user1', 'exit_fill', { symbol: 'BTCUSDT' })
    ).resolves.toBeUndefined()
    expect(axios.post).not.toHaveBeenCalled()
  })

  test('an empty events array means "no events subscribed", not "unfiltered"', async () => {
    _mockSettingsFindOne({ enabled: true, url: 'https://example.com/hook', events: [] })
    await dispatchWebhook('user1', 'exit_fill', { symbol: 'BTCUSDT' })
    expect(axios.post).not.toHaveBeenCalled()
  })
})

describe('sendTestWebhook', () => {
  beforeEach(() => {
    jest.clearAllMocks()
  })

  test('throws when no url is provided', async () => {
    await expect(sendTestWebhook({ url: '', format: 'json', timeoutMs: 5000 })).rejects.toThrow(/No webhook URL/)
    expect(axios.post).not.toHaveBeenCalled()
  })

  test('posts a single "status" event and resolves on success', async () => {
    axios.post.mockResolvedValueOnce({ status: 200 })
    await sendTestWebhook({ url: 'https://example.com/hook', format: 'json', timeoutMs: 5000 })
    expect(axios.post).toHaveBeenCalledTimes(1)
    const [url, body] = axios.post.mock.calls[0]
    expect(url).toBe('https://example.com/hook')
    expect(body).toMatchObject({ event: 'status' })
  })

  test('surfaces (does not swallow) a delivery failure to the caller', async () => {
    axios.post.mockRejectedValueOnce(new Error('ECONNREFUSED'))
    await expect(
      sendTestWebhook({ url: 'https://example.com/hook', format: 'json', timeoutMs: 5000 })
    ).rejects.toThrow('ECONNREFUSED')
    // No retry loop for the test path — exactly one attempt.
    expect(axios.post).toHaveBeenCalledTimes(1)
  })
})

describe('VALID_EVENTS', () => {
  test('exports the six lifecycle events the plan defines', () => {
    expect(VALID_EVENTS).toEqual(
      expect.arrayContaining(['entry_fill', 'exit_fill', 'liquidation', 'session_start', 'session_stop', 'session_error'])
    )
    expect(VALID_EVENTS).toHaveLength(6)
  })
})
