const {
  buildMonteCarloConfig,
  buildWalkForwardConfig,
  buildPBOConfig,
  computeConfigHash,
  MAX_RUNS,
  DEFAULT_RUNS,
  MAX_N_FOLDS,
  MAX_MAX_COMBINATIONS,
  MAX_N_TRIALS,
  MAX_MC_TOP_K,
  DEFAULT_MC_TOP_K,
  MIN_N_BLOCKS,
  MAX_N_BLOCKS,
  DEFAULT_N_BLOCKS,
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

  // Plan 10 Phase 4a (MC-scored trial selection) — this validator was the
  // missing link between the fully-built engine feature
  // (walk_forward.py's _mc_score_fold) and the API: mcScoring/mcTopK weren't
  // read from the request body at all before this, so the feature could
  // never actually be enabled end-to-end.
  test('mcScoring defaults to off, mcTopK undefined when off', () => {
    const config = buildWalkForwardConfig(baseWfInput())
    expect(config.mcScoring).toBe(false)
    expect(config.mcTopK).toBeUndefined()
  })

  test('mcScoring=true defaults mcTopK to DEFAULT_MC_TOP_K', () => {
    const config = buildWalkForwardConfig({ ...baseWfInput(), mcScoring: true })
    expect(config.mcScoring).toBe(true)
    expect(config.mcTopK).toBe(DEFAULT_MC_TOP_K)
  })

  test('clamps an explicit mcTopK to the documented cap (must match engine MAX_MC_TOP_K=10)', () => {
    const config = buildWalkForwardConfig({ ...baseWfInput(), mcScoring: true, mcTopK: MAX_MC_TOP_K + 50 })
    expect(config.mcTopK).toBe(MAX_MC_TOP_K)
  })

  test('rejects a non-positive mcTopK', () => {
    expect(() => buildWalkForwardConfig({ ...baseWfInput(), mcScoring: true, mcTopK: 0 })).toThrow(/mcTopK must be/)
  })

  test('mcTopK is ignored (not passed through) when mcScoring is off', () => {
    const config = buildWalkForwardConfig({ ...baseWfInput(), mcScoring: false, mcTopK: 5 })
    expect(config.mcTopK).toBeUndefined()
  })

  // Plan 10 Phase 4b (risk_pct/leverage search) — 2026-07-19 decision: a
  // separate grid restricted to exactly risk_pct/leverage, cartesian-
  // multiplied against paramGrid inside the engine, not tagged/prefixed
  // keys merged into paramGrid itself.
  test('riskLeverageGrid is undefined when not provided (zero behavior change)', () => {
    const config = buildWalkForwardConfig(baseWfInput())
    expect(config.riskLeverageGrid).toBeUndefined()
  })

  test('accepts a valid riskLeverageGrid with values specs', () => {
    const riskLeverageGrid = { risk_pct: { values: [0.01, 0.02] }, leverage: { values: [5, 10, 20] } }
    const config = buildWalkForwardConfig({ ...baseWfInput(), riskLeverageGrid })
    expect(config.riskLeverageGrid).toEqual(riskLeverageGrid)
  })

  test('accepts a valid riskLeverageGrid with a min/max range spec', () => {
    const riskLeverageGrid = { leverage: { min: 5, max: 20, step: 5, type: 'int' } }
    const config = buildWalkForwardConfig({ ...baseWfInput(), riskLeverageGrid })
    expect(config.riskLeverageGrid).toEqual(riskLeverageGrid)
  })

  test('rejects an empty riskLeverageGrid', () => {
    expect(() => buildWalkForwardConfig({ ...baseWfInput(), riskLeverageGrid: {} })).toThrow(/must not be empty/)
  })

  test('rejects a riskLeverageGrid key outside risk_pct/leverage', () => {
    expect(() => buildWalkForwardConfig({
      ...baseWfInput(), riskLeverageGrid: { fast: { values: [1, 2] } },
    })).toThrow(/must be one of risk_pct, leverage/)
  })

  test('rejects a riskLeverageGrid spec with neither values nor min/max', () => {
    expect(() => buildWalkForwardConfig({
      ...baseWfInput(), riskLeverageGrid: { leverage: { step: 5 } },
    })).toThrow(/must specify either/)
  })

  test('rejects a riskLeverageGrid key colliding with a paramGrid key of the same name', () => {
    const input = baseWfInput()
    input.paramGrid = { leverage: { min: 1, max: 5, step: 1, type: 'int' } }
    expect(() => buildWalkForwardConfig({
      ...input, riskLeverageGrid: { leverage: { values: [5, 10] } },
    })).toThrow(/collides with a paramGrid key/)
  })

  test('rejects a non-object riskLeverageGrid', () => {
    expect(() => buildWalkForwardConfig({ ...baseWfInput(), riskLeverageGrid: 'nope' })).toThrow(/must be an object/)
  })
})

// Plan 10 — PBO (Probability of Backtest Overfitting). Deliberately no mode/nFolds/trainRatio
// fields (unlike buildWalkForwardConfig) — PBO runs one full-range optimization pass and does its
// own CSCV block subsampling, not walk-forward's sequential fold splitting.
describe('buildPBOConfig', () => {
  test('requires the same base fields as buildWalkForwardConfig', () => {
    expect(() => buildPBOConfig({})).toThrow(/strategyFile is required/)
  })

  test('defaults method/objective/nBlocks/maxCombinations when nothing else is provided', () => {
    const config = buildPBOConfig(baseWfInput())
    expect(config.method).toBe('grid')
    expect(config.objective).toBe('sharpe')
    expect(config.nBlocks).toBe(DEFAULT_N_BLOCKS)
    expect(config.maxCombinations).toBe(MAX_MAX_COMBINATIONS)
  })

  test('has no mode/nFolds/trainRatio fields — not a walk-forward variant', () => {
    const config = buildPBOConfig(baseWfInput())
    expect(config.mode).toBeUndefined()
    expect(config.nFolds).toBeUndefined()
    expect(config.trainRatio).toBeUndefined()
  })

  test('rejects an odd nBlocks', () => {
    expect(() => buildPBOConfig({ ...baseWfInput(), nBlocks: 7 })).toThrow(/nBlocks must be an even number/)
  })

  test('rejects an nBlocks below MIN_N_BLOCKS', () => {
    expect(() => buildPBOConfig({ ...baseWfInput(), nBlocks: 2 })).toThrow(/nBlocks must be an even number/)
    expect(MIN_N_BLOCKS).toBe(4)
  })

  test('clamps an explicit nBlocks to the documented cap (must match engine MAX_N_BLOCKS=12)', () => {
    const config = buildPBOConfig({ ...baseWfInput(), nBlocks: 100 })
    expect(config.nBlocks).toBe(MAX_N_BLOCKS)
  })

  test('accepts a valid even nBlocks within range', () => {
    const config = buildPBOConfig({ ...baseWfInput(), nBlocks: 10 })
    expect(config.nBlocks).toBe(10)
  })

  test('bayesian method carries nTrials/seed, grid method does not', () => {
    const bayesian = buildPBOConfig({ ...baseWfInput(), method: 'bayesian', nTrials: 80, seed: 7 })
    expect(bayesian.nTrials).toBe(80)
    expect(bayesian.seed).toBe(7)

    const grid = buildPBOConfig({ ...baseWfInput(), method: 'grid', nTrials: 80, seed: 7 })
    expect(grid.nTrials).toBeUndefined()
    expect(grid.seed).toBeUndefined()
  })

  test('rejects an invalid method', () => {
    expect(() => buildPBOConfig({ ...baseWfInput(), method: 'random' })).toThrow(/method must be/)
  })

  // Same riskLeverageGrid validation as buildWalkForwardConfig (Phase 4b) — spot-check it's
  // actually wired here too, not just copy-pasted comments.
  test('accepts a valid riskLeverageGrid', () => {
    const riskLeverageGrid = { risk_pct: { values: [0.01, 0.02] } }
    const config = buildPBOConfig({ ...baseWfInput(), riskLeverageGrid })
    expect(config.riskLeverageGrid).toEqual(riskLeverageGrid)
  })

  test('rejects a riskLeverageGrid key colliding with a paramGrid key', () => {
    const input = baseWfInput()
    input.paramGrid = { leverage: { min: 1, max: 5, step: 1, type: 'int' } }
    expect(() => buildPBOConfig({
      ...input, riskLeverageGrid: { leverage: { values: [5, 10] } },
    })).toThrow(/collides with a paramGrid key/)
  })

  test('rejects a non-positive capital', () => {
    expect(() => buildPBOConfig({ ...baseWfInput(), capital: 0 })).toThrow(/capital must be/)
  })
})
