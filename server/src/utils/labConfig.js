const crypto = require('crypto')

const MAX_RUNS = 20_000
const DEFAULT_RUNS = 5_000

// Normalizes + validates a Monte Carlo robustness-run request body into the
// exact config shape persisted on LabResult.config and forwarded to the
// engine (Plan 10 §3.2). Rejects, does not clamp, invalid enum/type input —
// clamps only the numeric runs bound (Plan 10 §3.3's documented cap).
function buildMonteCarloConfig(input = {}) {
  const mode = input.mode ?? 'block'
  if (mode !== 'block' && mode !== 'iid') {
    throw new Error(`mode must be 'block' or 'iid', got '${mode}'`)
  }

  const runsNum = Number(input.runs ?? DEFAULT_RUNS)
  if (!Number.isFinite(runsNum) || runsNum < 1) {
    throw new Error('runs must be a positive number')
  }
  const runs = Math.min(Math.round(runsNum), MAX_RUNS)

  let blockLen = null
  if (input.blockLen !== undefined && input.blockLen !== null && input.blockLen !== '') {
    const blockLenNum = Number(input.blockLen)
    if (!Number.isFinite(blockLenNum) || blockLenNum < 1) {
      throw new Error('blockLen must be a positive integer when provided')
    }
    blockLen = Math.round(blockLenNum)
  }

  const ruinThresholdPctNum = Number(input.ruinThresholdPct ?? 30.0)
  if (!Number.isFinite(ruinThresholdPctNum) || ruinThresholdPctNum <= 0 || ruinThresholdPctNum > 100) {
    throw new Error('ruinThresholdPct must be a number between 0 and 100')
  }

  let seed = null
  if (input.seed !== undefined && input.seed !== null && input.seed !== '') {
    const seedNum = Number(input.seed)
    if (!Number.isFinite(seedNum)) {
      throw new Error('seed must be a number when provided')
    }
    seed = Math.round(seedNum)
  }

  return { mode, runs, blockLen, ruinThresholdPct: ruinThresholdPctNum, seed }
}

// Plan 10 Phase 3a — walk-forward optimization config. Same "reject, don't
// clamp invalid input" stance as buildMonteCarloConfig, except the numeric
// caps (nFolds, maxCombinations) which are documented, clamped bounds.
const MAX_N_FOLDS = 12
const DEFAULT_N_FOLDS = 4
const DEFAULT_TRAIN_RATIO = 0.7
const MAX_MAX_COMBINATIONS = 500 // Plan 10 §5.8 concurrency/compute guardrail
const MAX_N_TRIALS = 500 // Plan 10 Phase 3b — bayesian's per-fold trial count,
// same guardrail stance as MAX_MAX_COMBINATIONS (grid's per-fold combo count)
const DEFAULT_N_TRIALS = 50
const MAX_MC_TOP_K = 10 // Plan 10 Phase 4a — must match engine walk_forward.py's own
// MAX_MC_TOP_K exactly: each extra candidate is one more full OOS backtest per fold,
// engine re-clamps defensively but this is the first line of defense
const DEFAULT_MC_TOP_K = 3

function buildWalkForwardConfig(input = {}) {
  const required = ['strategyFile', 'exchange', 'symbol', 'timeframe', 'startDate', 'endDate', 'capital', 'paramGrid']
  for (const key of required) {
    if (input[key] === undefined || input[key] === null || input[key] === '') {
      throw new Error(`${key} is required`)
    }
  }
  if (typeof input.paramGrid !== 'object' || Array.isArray(input.paramGrid) || Object.keys(input.paramGrid).length === 0) {
    throw new Error('paramGrid must be a non-empty object')
  }

  // Plan 10 Phase 4b (risk_pct/leverage search) — opt-in, `undefined` when
  // absent = zero behavior change for every existing run. 2026-07-19
  // decision: a SEPARATE grid (not tagged/prefixed keys merged into
  // paramGrid) restricted to exactly `risk_pct`/`leverage`, cartesian-
  // multiplied against paramGrid inside the engine's own
  // `_build_combined_grid` — validated only for shape here (each entry
  // needs either `values` or `min`/`max`, same loose contract paramGrid
  // itself already has, since `_expand_param_range` on the engine side does
  // the real per-key validation). The combinatorial-explosion risk this
  // decision flagged is bounded downstream by `maxCombinations` below
  // (already clamped to MAX_MAX_COMBINATIONS) — `_build_combined_grid`
  // samples over the TRUE combined total, so a wide risk_leverage_grid
  // can't bypass that cap.
  let riskLeverageGrid
  if (input.riskLeverageGrid !== undefined && input.riskLeverageGrid !== null) {
    if (typeof input.riskLeverageGrid !== 'object' || Array.isArray(input.riskLeverageGrid)) {
      throw new Error('riskLeverageGrid must be an object')
    }
    const allowedKeys = ['risk_pct', 'leverage']
    const keys = Object.keys(input.riskLeverageGrid)
    if (keys.length === 0) {
      throw new Error('riskLeverageGrid must not be empty when provided')
    }
    for (const key of keys) {
      if (!allowedKeys.includes(key)) {
        throw new Error(`riskLeverageGrid keys must be one of ${allowedKeys.join(', ')}, got '${key}'`)
      }
      if (Object.prototype.hasOwnProperty.call(input.paramGrid, key)) {
        // Would silently collide inside the engine's combined grid namespace
        // split otherwise — fail loud here instead of guessing which one wins.
        throw new Error(`riskLeverageGrid key '${key}' collides with a paramGrid key of the same name`)
      }
      const spec = input.riskLeverageGrid[key]
      if (typeof spec !== 'object' || spec === null || Array.isArray(spec)) {
        throw new Error(`riskLeverageGrid.${key} must be an object (range or values spec)`)
      }
      const hasValues = Array.isArray(spec.values) && spec.values.length > 0
      const hasRange = spec.min !== undefined && spec.max !== undefined
      if (!hasValues && !hasRange) {
        throw new Error(`riskLeverageGrid.${key} must specify either 'values' or 'min'/'max'`)
      }
    }
    riskLeverageGrid = input.riskLeverageGrid
  }

  const mode = input.mode ?? 'rolling'
  if (mode !== 'rolling' && mode !== 'anchored') {
    throw new Error(`mode must be 'rolling' or 'anchored', got '${mode}'`)
  }

  const method = input.method ?? 'grid'
  if (method !== 'grid' && method !== 'bayesian') {
    throw new Error(`method must be 'grid' or 'bayesian', got '${method}'`)
  }

  const nTrialsNum = Number(input.nTrials ?? DEFAULT_N_TRIALS)
  if (!Number.isFinite(nTrialsNum) || nTrialsNum < 1) {
    throw new Error('nTrials must be a positive number')
  }
  const nTrials = Math.min(Math.round(nTrialsNum), MAX_N_TRIALS)

  let seed = null
  if (input.seed !== undefined && input.seed !== null && input.seed !== '') {
    const seedNum = Number(input.seed)
    if (!Number.isFinite(seedNum)) {
      throw new Error('seed must be a number when provided')
    }
    seed = Math.round(seedNum)
  }

  const objective = input.objective ?? 'sharpe'

  const nFoldsNum = Number(input.nFolds ?? DEFAULT_N_FOLDS)
  if (!Number.isFinite(nFoldsNum) || nFoldsNum < 1) {
    throw new Error('nFolds must be a positive number')
  }
  const nFolds = Math.min(Math.round(nFoldsNum), MAX_N_FOLDS)

  const trainRatioNum = Number(input.trainRatio ?? DEFAULT_TRAIN_RATIO)
  if (!Number.isFinite(trainRatioNum) || trainRatioNum <= 0 || trainRatioNum >= 1) {
    throw new Error('trainRatio must be a number between 0 and 1 (exclusive)')
  }

  const maxCombinationsNum = Number(input.maxCombinations ?? 0)
  if (!Number.isFinite(maxCombinationsNum) || maxCombinationsNum < 0) {
    throw new Error('maxCombinations must be a non-negative number')
  }
  const maxCombinations = maxCombinationsNum > 0
    ? Math.min(Math.round(maxCombinationsNum), MAX_MAX_COMBINATIONS)
    : MAX_MAX_COMBINATIONS // 0 ("full grid") is dangerous here — a fold-x-grid product without
    // a cap can mean thousands of backtests; unlike the old sync /optimize/run
    // (which lets 0="all combos" through), the job-based Lab path always caps.

  const minTradesNum = Number(input.minTrades ?? 0)
  if (!Number.isFinite(minTradesNum) || minTradesNum < 0) {
    throw new Error('minTrades must be a non-negative number')
  }

  // Plan 10 Phase 4a — MC-scored trial selection (opt-in, default off, zero
  // behavior change otherwise). Was fully built engine-side
  // (walk_forward.py/_mc_score_fold) but never reached this validator, so it
  // was unreachable from the API — fixed here.
  const mcScoring = !!input.mcScoring
  const mcTopKNum = Number(input.mcTopK ?? DEFAULT_MC_TOP_K)
  if (!Number.isFinite(mcTopKNum) || mcTopKNum < 1) {
    throw new Error('mcTopK must be a positive number')
  }
  const mcTopK = Math.min(Math.round(mcTopKNum), MAX_MC_TOP_K)

  const leverageNum = Number(input.leverage ?? 10)
  const capitalNum = Number(input.capital)
  if (!Number.isFinite(capitalNum) || capitalNum <= 0) {
    throw new Error('capital must be a positive number')
  }

  return {
    strategyFile: input.strategyFile,
    exchange: input.exchange,
    symbol: input.symbol,
    timeframe: input.timeframe,
    startDate: input.startDate,
    endDate: input.endDate,
    capital: capitalNum,
    leverage: Number.isFinite(leverageNum) ? Math.round(leverageNum) : 10,
    feeRate: input.feeRate != null ? Number(input.feeRate) : undefined,
    slippagePct: input.slippagePct != null ? Number(input.slippagePct) : null,
    fundingEnabled: !!input.fundingEnabled,
    fundingRate: input.fundingRate != null ? Number(input.fundingRate) : null,
    riskParams: input.riskParams ?? {},
    objective,
    paramGrid: input.paramGrid,
    riskLeverageGrid,
    mode,
    method,
    nTrials: method === 'bayesian' ? nTrials : undefined,
    seed: method === 'bayesian' ? seed : undefined,
    nFolds,
    trainRatio: trainRatioNum,
    maxCombinations,
    minTrades: Math.round(minTradesNum),
    mcScoring,
    mcTopK: mcScoring ? mcTopK : undefined,
  }
}

// Deterministic regardless of key insertion order — sorts keys before
// hashing so `{mode:'block',runs:5000}` and `{runs:5000,mode:'block'}` hash
// identically (both come from buildMonteCarloConfig's fixed key order in
// practice, but this makes the guarantee explicit rather than incidental).
function computeConfigHash(sourceJobId, config) {
  const sortedKeys = Object.keys(config).sort()
  const canonical = JSON.stringify({ sourceJobId, ...Object.fromEntries(sortedKeys.map((k) => [k, config[k]])) })
  return crypto.createHash('sha256').update(canonical).digest('hex')
}

module.exports = {
  buildMonteCarloConfig,
  buildWalkForwardConfig,
  computeConfigHash,
  MAX_RUNS,
  DEFAULT_RUNS,
  MAX_N_FOLDS,
  MAX_MAX_COMBINATIONS,
  MAX_N_TRIALS,
  MAX_MC_TOP_K,
  DEFAULT_MC_TOP_K,
}
