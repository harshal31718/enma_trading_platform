const { v4: uuidv4 } = require('uuid')
const simulationQueue = require('../services/simulationQueue')
const optimizationQueue = require('../services/optimizationQueue')
const pboQueue = require('../services/pboQueue')
const LabResult = require('../models/LabResult')
const BacktestResult = require('../models/BacktestResult')
const Strategy = require('../models/Strategy')
const ApiResponse = require('../utils/ApiResponse')
const ApiError = require('../utils/ApiError')
const engineClient = require('../services/engineClient')
const { buildMonteCarloConfig, buildWalkForwardConfig, buildPBOConfig, computeConfigHash } = require('../utils/labConfig')

// POST /api/v1/lab/simulations
async function runMonteCarlo(req, res, next) {
  try {
    const { sourceJobId } = req.body
    if (!sourceJobId) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'sourceJobId is required')
    }

    // Ownership + existence check — a jobId belonging to another user, or
    // one that never completed, cannot be simulated.
    const parent = await BacktestResult.findOne({ userId: req.user.id, jobId: sourceJobId })
      .select('status')
      .lean()
    if (!parent) {
      throw new ApiError(404, 'NOT_FOUND', 'Source backtest not found')
    }
    if (parent.status !== 'completed') {
      throw new ApiError(400, 'VALIDATION_ERROR', 'Source backtest has not completed successfully')
    }

    let config
    try {
      config = buildMonteCarloConfig(req.body)
    } catch (e) {
      throw new ApiError(400, 'VALIDATION_ERROR', e.message)
    }

    const configHash = computeConfigHash(sourceJobId, config)

    // configHash cache short-circuit (Plan 10 §3.2 / Phase 1 acceptance:
    // "re-submitting identical config returns cached").
    const cached = await LabResult.findOne({
      userId: req.user.id,
      sourceJobId,
      configHash,
      type: 'monte_carlo',
      status: 'completed',
    }).lean()
    if (cached) {
      return res.status(200).json(ApiResponse.success({ labId: cached.labId, status: cached.status, cached: true }))
    }

    const labId = uuidv4()

    await LabResult.create({
      userId: req.user.id,
      labId,
      type: 'monte_carlo',
      sourceJobId,
      config,
      configHash,
      status: 'queued',
    })

    await simulationQueue.add('run', {
      simId: labId,
      sourceJobId,
      userId: req.user.id,
      config,
      configHash,
    }, { jobId: labId })

    res.status(202).json(ApiResponse.success({ labId, status: 'queued' }))
  } catch (err) {
    next(err)
  }
}

// GET /api/v1/lab/simulations/:simId
async function getSimulation(req, res, next) {
  try {
    const { simId } = req.params
    const lab = await LabResult.findOne({ userId: req.user.id, labId: simId }).lean()
    if (!lab) throw new ApiError(404, 'NOT_FOUND', 'Simulation not found')
    res.json(ApiResponse.success(lab))
  } catch (err) {
    next(err)
  }
}

// GET /api/v1/lab/simulations?sourceJobId=...&limit=20
async function listSimulations(req, res, next) {
  try {
    const { sourceJobId } = req.query
    const parsedLimit = parseInt(req.query.limit, 10)
    const limit = Math.min(isNaN(parsedLimit) ? 20 : parsedLimit, 100)

    const filter = { userId: req.user.id, type: 'monte_carlo' }
    if (sourceJobId) filter.sourceJobId = sourceJobId

    const labs = await LabResult.find(filter)
      .select('-results')
      .sort({ createdAt: -1 })
      .limit(limit)
      .lean()

    res.json(ApiResponse.success({ simulations: labs }))
  } catch (err) {
    next(err)
  }
}

// POST /api/v1/lab/optimizations — Plan 10 Phase 3a (walk-forward).
// Unlike Monte Carlo, an optimization isn't derived from a completed
// backtest's jobId — it's a standalone run over a strategy+symbol+range —
// so there's no parent-ownership check to make (the run itself is scoped
// to req.user.id like every other LabResult).
async function runOptimization(req, res, next) {
  try {
    // Client sends strategyId (same convention as POST /api/v1/backtest) —
    // resolve to the engine's filePath here rather than trusting a raw
    // path from the client.
    const { strategyId } = req.body
    if (!strategyId) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'strategyId is required')
    }
    const strategy = await Strategy.findById(strategyId).lean()
    if (!strategy) {
      throw new ApiError(404, 'NOT_FOUND', 'Strategy not found')
    }

    let config
    try {
      config = buildWalkForwardConfig({ ...req.body, strategyFile: strategy.filePath })
    } catch (e) {
      throw new ApiError(400, 'VALIDATION_ERROR', e.message)
    }

    // Identity key for the configHash cache: what this run is ABOUT (Plan 10
    // §3.2 idempotency — same strategy+range+grid+fold-config -> cached).
    const identityKey = `${config.strategyFile}:${config.symbol}:${config.timeframe}:${config.startDate}:${config.endDate}`
    const configHash = computeConfigHash(identityKey, config)

    const cached = await LabResult.findOne({
      userId: req.user.id,
      configHash,
      type: 'optimization',
      status: 'completed',
    }).lean()
    if (cached) {
      return res.status(200).json(ApiResponse.success({ labId: cached.labId, status: cached.status, cached: true }))
    }

    const labId = uuidv4()

    await LabResult.create({
      userId: req.user.id,
      labId,
      type: 'optimization',
      config,
      configHash,
      status: 'queued',
    })

    await optimizationQueue.add('run', {
      labId,
      userId: req.user.id,
      config,
      configHash,
    }, { jobId: labId })

    res.status(202).json(ApiResponse.success({ labId, status: 'queued' }))
  } catch (err) {
    next(err)
  }
}

// GET /api/v1/lab/optimizations/:labId
async function getOptimization(req, res, next) {
  try {
    const { labId } = req.params
    const lab = await LabResult.findOne({ userId: req.user.id, labId, type: 'optimization' }).lean()
    if (!lab) throw new ApiError(404, 'NOT_FOUND', 'Optimization not found')
    res.json(ApiResponse.success(lab))
  } catch (err) {
    next(err)
  }
}

// GET /api/v1/lab/optimizations?limit=20
async function listOptimizations(req, res, next) {
  try {
    const parsedLimit = parseInt(req.query.limit, 10)
    const limit = Math.min(isNaN(parsedLimit) ? 20 : parsedLimit, 100)

    const labs = await LabResult.find({ userId: req.user.id, type: 'optimization' })
      .select('-results')
      .sort({ createdAt: -1 })
      .limit(limit)
      .lean()

    res.json(ApiResponse.success({ optimizations: labs }))
  } catch (err) {
    next(err)
  }
}

// GET /api/v1/lab/objectives — thin proxy to the engine's existing
// GET /optimize/objectives (Node had no route for this at all before Phase
// 3c's wizard needed it — the objective list itself isn't user data, so no
// ownership/auth logic beyond the standard JWT gate applies).
async function listObjectives(req, res, next) {
  try {
    const response = await engineClient.get('/optimize/objectives')
    res.json(ApiResponse.success(response.data.data))
  } catch (err) {
    next(new ApiError(503, 'ENGINE_UNAVAILABLE', `Could not fetch objectives from engine: ${err.message}`))
  }
}

// POST /api/v1/lab/pbo — Probability of Backtest Overfitting (CSCV). Same
// standalone-run shape as runOptimization (strategyId -> filePath resolution,
// no parent-jobId ownership check) — PBO is its own full-range optimization
// pass, not derived from an existing job.
async function runPBO(req, res, next) {
  try {
    const { strategyId } = req.body
    if (!strategyId) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'strategyId is required')
    }
    const strategy = await Strategy.findById(strategyId).lean()
    if (!strategy) {
      throw new ApiError(404, 'NOT_FOUND', 'Strategy not found')
    }

    let config
    try {
      config = buildPBOConfig({ ...req.body, strategyFile: strategy.filePath })
    } catch (e) {
      throw new ApiError(400, 'VALIDATION_ERROR', e.message)
    }

    const identityKey = `${config.strategyFile}:${config.symbol}:${config.timeframe}:${config.startDate}:${config.endDate}`
    const configHash = computeConfigHash(identityKey, config)

    const cached = await LabResult.findOne({
      userId: req.user.id,
      configHash,
      type: 'pbo',
      status: 'completed',
    }).lean()
    if (cached) {
      return res.status(200).json(ApiResponse.success({ labId: cached.labId, status: cached.status, cached: true }))
    }

    const labId = uuidv4()

    await LabResult.create({
      userId: req.user.id,
      labId,
      type: 'pbo',
      config,
      configHash,
      status: 'queued',
    })

    await pboQueue.add('run', {
      labId,
      userId: req.user.id,
      config,
      configHash,
    }, { jobId: labId })

    res.status(202).json(ApiResponse.success({ labId, status: 'queued' }))
  } catch (err) {
    next(err)
  }
}

// GET /api/v1/lab/pbo/:labId
async function getPBO(req, res, next) {
  try {
    const { labId } = req.params
    const lab = await LabResult.findOne({ userId: req.user.id, labId, type: 'pbo' }).lean()
    if (!lab) throw new ApiError(404, 'NOT_FOUND', 'PBO run not found')
    res.json(ApiResponse.success(lab))
  } catch (err) {
    next(err)
  }
}

// GET /api/v1/lab/pbo?limit=20
async function listPBO(req, res, next) {
  try {
    const parsedLimit = parseInt(req.query.limit, 10)
    const limit = Math.min(isNaN(parsedLimit) ? 20 : parsedLimit, 100)

    const labs = await LabResult.find({ userId: req.user.id, type: 'pbo' })
      .select('-results')
      .sort({ createdAt: -1 })
      .limit(limit)
      .lean()

    res.json(ApiResponse.success({ runs: labs }))
  } catch (err) {
    next(err)
  }
}

module.exports = {
  runMonteCarlo,
  getSimulation,
  listSimulations,
  runOptimization,
  getOptimization,
  listOptimizations,
  listObjectives,
  runPBO,
  getPBO,
  listPBO,
}
