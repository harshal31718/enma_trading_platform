const {
  buildMonteCarloConfig,
  buildWalkForwardConfig,
  computeConfigHash,
  MAX_RUNS,
  DEFAULT_RUNS,
  MAX_N_FOLDS,
  MAX_MAX_COMBINATIONS,
  MAX_N_TRIALS,
} = require('../labConfig')

const baseWfInput = () => ({
  strategyFile: 'strategies/AdaptiveTrend',
  exchange: 'Binance Futures',
  symbol: 'BTCUSDT',
  timeframe: '1h',
  startDate: '2024-01-01T00:00:00Z',
  endDate: '2024-06-01T00:00:00Z',
  capital: 10000,
  paramGrid: { fast: { min: 5, max: 15, step: 5, type: 'int' } },
})

describe('buildMonteCarloConfig', () => {
  test('defaults mode/runs/ruinThresholdPct when nothing is provided', () => {
    const config = buildMonteCarloConfig({})
    expect(config.mode).toBe('block')
    expect(config.runs).toBe(DEFAULT_RUNS)
    expect(config.blockLen).toBeNull()
    expect(config.ruinThresholdPct).toBeCloseTo(30.0)
    expect(config.seed).toBeNull()
  })

  test('accepts iid mode', () => {
    expect(buildMonteCarloConfig({ mode: 'iid' }).mode).toBe('iid')
  })

  test('rejects an invalid mode', () => {
    expect(() => buildMonteCarloConfig({ mode: 'bogus' })).toThrow(/mode must be/)
  })

  test('clamps runs to the documented cap rather than rejecting', () => {
    const config = buildMonteCarloConfig({ runs: MAX_RUNS + 50_000 })
    expect(config.runs).toBe(MAX_RUNS)
  })

  test('rejects non-positive runs', () => {
    expect(() => buildMonteCarloConfig({ runs: 0 })).toThrow(/runs must be/)
    expect(() => buildMonteCarloConfig({ runs: -10 })).toThrow(/runs must be/)
  })

  test('accepts an explicit blockLen', () => {
    expect(buildMonteCarloConfig({ blockLen: 12 }).blockLen).toBe(12)
  })

  test('rejects a non-positive blockLen', () => {
    expect(() => buildMonteCarloConfig({ blockLen: 0 })).toThrow(/blockLen must be/)
  })

  test('rejects ruinThresholdPct out of (0, 100]', () => {
    expect(() => buildMonteCarloConfig({ ruinThresholdPct: 0 })).toThrow(/ruinThresholdPct/)
    expect(() => buildMonteCarloConfig({ ruinThresholdPct: 150 })).toThrow(/ruinThresholdPct/)
  })

  test('accepts an explicit seed for reproducibility', () => {
    expect(buildMonteCarloConfig({ seed: 42 }).seed).toBe(42)
  })
})

describe('computeConfigHash', () => {
  test('is deterministic for the same sourceJobId + config', () => {
    const config = buildMonteCarloConfig({ mode: 'block', runs: 5000 })
    const a = computeConfigHash('job-1', config)
    const b = computeConfigHash('job-1', config)
    expect(a).toBe(b)
  })

  test('is independent of config key insertion order', () => {
    const hashA = computeConfigHash('job-1', { mode: 'block', runs: 5000, blockLen: null, ruinThresholdPct: 30, seed: null })
    const hashB = computeConfigHash('job-1', { seed: null, runs: 5000, ruinThresholdPct: 30, blockLen: null, mode: 'block' })
    expect(hashA).toBe(hashB)
  })

  test('differs when sourceJobId differs', () => {
    const config = buildMonteCarloConfig({})
    expect(computeConfigHash('job-1', config)).not.toBe(computeConfigHash('job-2', config))
  })

  test('differs when config differs', () => {
    const configA = buildMonteCarloConfig({ mode: 'block' })
    const configB = buildMonteCarloConfig({ mode: 'iid' })
    expect(computeConfigHash('job-1', configA)).not.toBe(computeConfigHash('job-1', configB))
  })
})

describe('buildWalkForwardConfig', () => {
  test('defaults mode/nFolds/trainRatio/maxCombinations/minTrades', () => {
    const config = buildWalkForwardConfig(baseWfInput())
    expect(config.mode).toBe('rolling')
    expect(config.nFolds).toBe(4)
    expect(config.trainRatio).toBeCloseTo(0.7)
    expect(config.maxCombinations).toBe(MAX_MAX_COMBINATIONS)
    expect(config.minTrades).toBe(0)
    expect(config.objective).toBe('sharpe')
  })

  test('defaults method to grid, with nTrials/seed left undefined', () => {
    const config = buildWalkForwardConfig(baseWfInput())
    expect(config.method).toBe('grid')
    expect(config.nTrials).toBeUndefined()
    expect(config.seed).toBeUndefined()
  })

  test('accepts method=bayesian with a default nTrials', () => {
    const config = buildWalkForwardConfig({ ...baseWfInput(), method: 'bayesian' })
    expect(config.method).toBe('bayesian')
    expect(config.nTrials).toBe(50)
  })

  test('rejects an invalid method', () => {
    expect(() => buildWalkForwardConfig({ ...baseWfInput(), method: 'bogus' })).toThrow(/method must be/)
  })

  test('clamps nTrials to the documented cap rather than rejecting', () => {
    const config = buildWalkForwardConfig({ ...baseWfInput(), method: 'bayesian', nTrials: MAX_N_TRIALS + 1000 })
    expect(config.nTrials).toBe(MAX_N_TRIALS)
  })

  test('rejects non-positive nTrials', () => {
    expect(() => buildWalkForwardConfig({ ...baseWfInput(), method: 'bayesian', nTrials: 0 })).toThrow(/nTrials must be/)
    expect(() => buildWalkForwardConfig({ ...baseWfInput(), method: 'bayesian', nTrials: -3 })).toThrow(/nTrials must be/)
  })

  test('nTrials is ignored (not passed through) when method=grid', () => {
    const config = buildWalkForwardConfig({ ...baseWfInput(), method: 'grid', nTrials: 200 })
    expect(config.nTrials).toBeUndefined()
  })

  test('accepts an explicit seed for bayesian reproducibility', () => {
    const config = buildWalkForwardConfig({ ...baseWfInput(), method: 'bayesian', seed: 7 })
    expect(config.seed).toBe(7)
  })

  test('rejects a non-numeric seed', () => {
    expect(() => buildWalkForwardConfig({ ...baseWfInput(), method: 'bayesian', seed: 'nope' })).toThrow(/seed must be/)
  })

  test.each(['strategyFile', 'exchange', 'symbol', 'timeframe', 'startDate', 'endDate', 'capital', 'paramGrid'])(
    'rejects missing required field %s',
    (field) => {
      const input = baseWfInput()
      delete input[field]
      expect(() => buildWalkForwardConfig(input)).toThrow(new RegExp(`${field} is required|paramGrid must be`))
    }
  )

  test('rejects an empty paramGrid', () => {
    expect(() => buildWalkForwardConfig({ ...baseWfInput(), paramGrid: {} })).toThrow(/paramGrid must be/)
  })

  test('accepts anchored mode', () => {
    expect(buildWalkForwardConfig({ ...baseWfInput(), mode: 'anchored' }).mode).toBe('anchored')
  })

  test('rejects an invalid mode', () => {
    expect(() => buildWalkForwardConfig({ ...baseWfInput(), mode: 'bogus' })).toThrow(/mode must be/)
  })

  test('clamps nFolds to the documented cap rather than rejecting', () => {
    const config = buildWalkForwardConfig({ ...baseWfInput(), nFolds: MAX_N_FOLDS + 20 })
    expect(config.nFolds).toBe(MAX_N_FOLDS)
  })

  test('rejects trainRatio out of (0, 1)', () => {
    expect(() => buildWalkForwardConfig({ ...baseWfInput(), trainRatio: 0 })).toThrow(/trainRatio/)
    expect(() => buildWalkForwardConfig({ ...baseWfInput(), trainRatio: 1 })).toThrow(/trainRatio/)
  })

  test('maxCombinations=0 (full grid) is replaced by the documented cap, not passed through unbounded', () => {
    const config = buildWalkForwardConfig({ ...baseWfInput(), maxCombinations: 0 })
    expect(config.maxCombinations).toBe(MAX_MAX_COMBINATIONS)
  })

  test('clamps an explicit maxCombinations above the cap', () => {
    const config = buildWalkForwardConfig({ ...baseWfInput(), maxCombinations: MAX_MAX_COMBINATIONS + 1000 })
    expect(config.maxCombinations).toBe(MAX_MAX_COMBINATIONS)
  })

  test('accepts an explicit minTrades filter', () => {
    expect(buildWalkForwardConfig({ ...baseWfInput(), minTrades: 30 }).minTrades).toBe(30)
  })

  test('rejects a negative minTrades', () => {
    expect(() => buildWalkForwardConfig({ ...baseWfInput(), minTrades: -5 })).toThrow(/minTrades/)
  })

  test('rejects a non-object paramGrid', () => {
    expect(() => buildWalkForwardConfig({ ...baseWfInput(), paramGrid: 'nope' })).toThrow(/paramGrid must be/)
  })
})
