// Plan 7 Step 7.2 (SRV-5): the shared engineClient axios instance used to
// default every call to a 1-hour timeout — meaning a request-path call
// (place order, start session) held its Express connection open for up to
// an hour if the engine ever hung. This test locks in the fix: a sane
// request-path default, plus an explicit long-job constant the 4 BullMQ
// workers opt into per-call for genuinely long backtest/simulation/
// optimization/PBO runs.
const engineClient = require('../engineClient')

describe('engineClient timeout configuration (Plan 7 Step 7.2 / SRV-5)', () => {
  test('the default (request-path) timeout is short, not the old 1-hour budget', () => {
    expect(engineClient.defaults.timeout).toBe(30 * 1000)
  })

  test('LONG_JOB_TIMEOUT_MS is exposed for workers to opt into explicitly', () => {
    expect(engineClient.LONG_JOB_TIMEOUT_MS).toBe(60 * 60 * 1000)
  })

  test('no engine call inherits the 1-hour budget by default', () => {
    expect(engineClient.defaults.timeout).toBeLessThan(engineClient.LONG_JOB_TIMEOUT_MS)
  })
})
