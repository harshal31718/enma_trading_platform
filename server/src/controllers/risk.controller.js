const Settings = require('../models/Settings')
const Strategy = require('../models/Strategy')
const BacktestResult = require('../models/BacktestResult')
const ApiResponse = require('../utils/ApiResponse')
const ApiError = require('../utils/ApiError')
const redis = require('../config/redis')
const engineClient = require('../services/engineClient')

async function _getOrCreateSettings(userId) {
  return Settings.findOneAndUpdate(
    { userId },
    { $setOnInsert: { userId } },
    { upsert: true, new: true }
  )
}

/**
 * GET /api/v1/risk/settings
 * Retrieves hierarchical risk limits and overrides.
 */
async function getRiskSettings(req, res, next) {
  try {
    const settings = await _getOrCreateSettings(req.user.id)
    res.json(ApiResponse.success({
      globalHardLimits: settings.globalHardLimits || {},
      strategyOverrides: settings.strategyOverrides || {},
      symbolOverrides: settings.symbolOverrides || {},
    }))
  } catch (err) {
    next(err)
  }
}

/**
 * PUT /api/v1/risk/settings
 * Updates hierarchical risk limits and overrides.
 */
async function updateRiskSettings(req, res, next) {
  try {
    const settings = await _getOrCreateSettings(req.user.id)
    const { globalHardLimits, strategyOverrides, symbolOverrides } = req.body

    // 1. Update Global Hard Limits
    if (globalHardLimits) {
      const prevGovernor = settings.globalHardLimits || {}
      // Plan 22 Step 22.7: Session Risk Governor knobs — all optional
      // (null = not configured = the governor's own default). `!== undefined`
      // still lets an explicit `null` in the payload clear a previously-set
      // value back to "off", matching the client form's blank-input semantics.
      const numOrNull = (v, prev) => (v !== undefined ? (v === null || v === '' ? null : Number(v)) : prev)

      settings.globalHardLimits = {
        maxLeverageAllowed: globalHardLimits.maxLeverageAllowed !== undefined ? Number(globalHardLimits.maxLeverageAllowed) : settings.globalHardLimits.maxLeverageAllowed,
        maxSessionDrawdown: globalHardLimits.maxSessionDrawdown !== undefined ? Number(globalHardLimits.maxSessionDrawdown) : settings.globalHardLimits.maxSessionDrawdown,
        maxRiskPctPerTrade: globalHardLimits.maxRiskPctPerTrade !== undefined ? Number(globalHardLimits.maxRiskPctPerTrade) : settings.globalHardLimits.maxRiskPctPerTrade,
        cooldownPeriodHours: globalHardLimits.cooldownPeriodHours !== undefined ? Number(globalHardLimits.cooldownPeriodHours) : settings.globalHardLimits.cooldownPeriodHours,
        maxDailyLossPct: numOrNull(globalHardLimits.maxDailyLossPct, prevGovernor.maxDailyLossPct ?? null),
        maxMarginUtilization: numOrNull(globalHardLimits.maxMarginUtilization, prevGovernor.maxMarginUtilization ?? null),
        varLimitPct: numOrNull(globalHardLimits.varLimitPct, prevGovernor.varLimitPct ?? null),
        cvarLimitPct: numOrNull(globalHardLimits.cvarLimitPct, prevGovernor.cvarLimitPct ?? null),
        correlationCap: {
          rho: numOrNull(globalHardLimits.correlationCap?.rho, prevGovernor.correlationCap?.rho ?? null),
          maxClusterExposurePct: globalHardLimits.correlationCap?.maxClusterExposurePct !== undefined
            ? Number(globalHardLimits.correlationCap.maxClusterExposurePct)
            : (prevGovernor.correlationCap?.maxClusterExposurePct ?? 0.4),
        },
        allocation: globalHardLimits.allocation !== undefined ? globalHardLimits.allocation : (prevGovernor.allocation ?? 'equal'),
        breachAction: globalHardLimits.breachAction !== undefined ? globalHardLimits.breachAction : (prevGovernor.breachAction ?? 'reducing'),
        autoFlattenOnHalt: globalHardLimits.autoFlattenOnHalt !== undefined ? Boolean(globalHardLimits.autoFlattenOnHalt) : (prevGovernor.autoFlattenOnHalt ?? false),
      }

      // Basic validations
      if (settings.globalHardLimits.maxLeverageAllowed < 1 || settings.globalHardLimits.maxLeverageAllowed > 125) {
        throw new ApiError(400, 'VALIDATION_ERROR', 'maxLeverageAllowed must be between 1 and 125')
      }
      if (settings.globalHardLimits.maxSessionDrawdown < 0.05 || settings.globalHardLimits.maxSessionDrawdown > 0.90) {
        throw new ApiError(400, 'VALIDATION_ERROR', 'maxSessionDrawdown must be between 0.05 and 0.90')
      }
      if (settings.globalHardLimits.maxRiskPctPerTrade < 0.001 || settings.globalHardLimits.maxRiskPctPerTrade > 0.20) {
        throw new ApiError(400, 'VALIDATION_ERROR', 'maxRiskPctPerTrade must be between 0.001 and 0.20')
      }
      if (settings.globalHardLimits.cooldownPeriodHours < 1 || settings.globalHardLimits.cooldownPeriodHours > 72) {
        throw new ApiError(400, 'VALIDATION_ERROR', 'cooldownPeriodHours must be between 1 and 72')
      }
      const g = settings.globalHardLimits
      if (g.maxDailyLossPct !== null && (g.maxDailyLossPct < 0 || g.maxDailyLossPct > 1)) {
        throw new ApiError(400, 'VALIDATION_ERROR', 'maxDailyLossPct must be between 0 and 1')
      }
      if (g.maxMarginUtilization !== null && (g.maxMarginUtilization < 0.01 || g.maxMarginUtilization > 1)) {
        throw new ApiError(400, 'VALIDATION_ERROR', 'maxMarginUtilization must be between 0.01 and 1')
      }
      if (g.varLimitPct !== null && (g.varLimitPct < 0 || g.varLimitPct > 1)) {
        throw new ApiError(400, 'VALIDATION_ERROR', 'varLimitPct must be between 0 and 1')
      }
      if (g.cvarLimitPct !== null && (g.cvarLimitPct < 0 || g.cvarLimitPct > 1)) {
        throw new ApiError(400, 'VALIDATION_ERROR', 'cvarLimitPct must be between 0 and 1')
      }
      if (g.correlationCap.rho !== null && (g.correlationCap.rho < 0 || g.correlationCap.rho > 1)) {
        throw new ApiError(400, 'VALIDATION_ERROR', 'correlationCap.rho must be between 0 and 1')
      }
      if (g.correlationCap.maxClusterExposurePct < 0 || g.correlationCap.maxClusterExposurePct > 1) {
        throw new ApiError(400, 'VALIDATION_ERROR', 'correlationCap.maxClusterExposurePct must be between 0 and 1')
      }
      if (!['equal', 'inverse_vol'].includes(g.allocation)) {
        throw new ApiError(400, 'VALIDATION_ERROR', 'allocation must be "equal" or "inverse_vol"')
      }
      if (!['reducing', 'halted'].includes(g.breachAction)) {
        throw new ApiError(400, 'VALIDATION_ERROR', 'breachAction must be "reducing" or "halted"')
      }
    }

    // 2. Update Strategy Overrides
    if (strategyOverrides) {
      const strategies = await Strategy.find({}).lean()
      const validNames = new Set(strategies.map(s => s.name))

      settings.strategyOverrides.clear()

      for (const [name, rules] of Object.entries(strategyOverrides)) {
        if (rules === null) continue
        if (!validNames.has(name)) {
          throw new ApiError(400, 'VALIDATION_ERROR', `Strategy ${name} is not a valid strategy name.`)
        }
        
        // Ensure rules conform to ranges
        const r = rules || {}
        const cleanedRules = {}
        if (r.riskPct !== undefined) {
          cleanedRules.riskPct = Number(r.riskPct)
          if (cleanedRules.riskPct < 0.0001 || cleanedRules.riskPct > 1) {
            throw new ApiError(400, 'VALIDATION_ERROR', `${name}: riskPct must be between 0.0001 and 1`)
          }
        }
        if (r.riskRewardRatio !== undefined) {
          cleanedRules.riskRewardRatio = Number(r.riskRewardRatio)
          if (cleanedRules.riskRewardRatio < 0.1 || cleanedRules.riskRewardRatio > 100) {
            throw new ApiError(400, 'VALIDATION_ERROR', `${name}: riskRewardRatio must be between 0.1 and 100`)
          }
        }
        if (r.maxSessionDrawdown !== undefined) {
          cleanedRules.maxSessionDrawdown = Number(r.maxSessionDrawdown)
          if (cleanedRules.maxSessionDrawdown < 0.01 || cleanedRules.maxSessionDrawdown > 1) {
            throw new ApiError(400, 'VALIDATION_ERROR', `${name}: maxSessionDrawdown must be between 0.01 and 1`)
          }
        }
        if (r.liqBufferPct !== undefined) {
          cleanedRules.liqBufferPct = Number(r.liqBufferPct)
          if (cleanedRules.liqBufferPct < 0 || cleanedRules.liqBufferPct > 0.5) {
            throw new ApiError(400, 'VALIDATION_ERROR', `${name}: liqBufferPct must be between 0 and 0.5`)
          }
        }
        if (r.minEdgeMult !== undefined) {
          cleanedRules.minEdgeMult = Number(r.minEdgeMult)
          if (cleanedRules.minEdgeMult < 0 || cleanedRules.minEdgeMult > 10) {
            throw new ApiError(400, 'VALIDATION_ERROR', `${name}: minEdgeMult must be between 0 and 10`)
          }
        }
        if (r.customAtrMult !== undefined) {
          cleanedRules.customAtrMult = Number(r.customAtrMult)
        }

        settings.strategyOverrides.set(name, cleanedRules)
      }
    }

    // 3. Update Symbol Overrides
    if (symbolOverrides) {
      settings.symbolOverrides.clear()

      for (const [sym, rules] of Object.entries(symbolOverrides)) {
        if (rules === null) continue
        
        const r = rules || {}
        const cleanedRules = {}
        if (r.maxLeverage !== undefined) {
          cleanedRules.maxLeverage = Number(r.maxLeverage)
          if (cleanedRules.maxLeverage < 1 || cleanedRules.maxLeverage > 125) {
            throw new ApiError(400, 'VALIDATION_ERROR', `${sym}: maxLeverage must be between 1 and 125`)
          }
        }
        if (r.volatilityMultiplier !== undefined) {
          cleanedRules.volatilityMultiplier = Number(r.volatilityMultiplier)
          if (cleanedRules.volatilityMultiplier < 0) {
            throw new ApiError(400, 'VALIDATION_ERROR', `${sym}: volatilityMultiplier must be non-negative`)
          }
        }
        if (r.maxExposureNotional !== undefined) {
          cleanedRules.maxExposureNotional = Number(r.maxExposureNotional)
          if (cleanedRules.maxExposureNotional < 100) {
            throw new ApiError(400, 'VALIDATION_ERROR', `${sym}: maxExposureNotional must be >= 100`)
          }
        }

        settings.symbolOverrides.set(sym, cleanedRules)
      }
    }

    await settings.save()

    res.json(ApiResponse.success({
      globalHardLimits: settings.globalHardLimits || {},
      strategyOverrides: settings.strategyOverrides || {},
      symbolOverrides: settings.symbolOverrides || {},
    }))
  } catch (err) {
    next(err)
  }
}

/**
 * GET /api/v1/risk/live-metrics
 * Retrieves live portfolio risk metrics, proxying to the engine with a 10s Redis cache.
 */
async function getLiveMetrics(req, res, next) {
  try {
    const cacheKey = `risk:live-metrics:${req.user.id}`
    const cached = await redis.get(cacheKey)
    if (cached) {
      return res.json(ApiResponse.success(JSON.parse(cached)))
    }

    const response = await engineClient.get('/risk/live-metrics', {
      headers: req.binanceHeaders
    })

    const liveData = response.data.data
    await redis.set(cacheKey, JSON.stringify(liveData), 'EX', 10)

    res.json(ApiResponse.success(liveData))
  } catch (err) {
    next(new ApiError(503, 'ENGINE_UNAVAILABLE', `Could not fetch live metrics from engine: ${err.message}`))
  }
}

/**
 * GET /api/v1/risk/backtest/:id/simulation
 * Triggers or retrieves leverage sensitivity and Monte Carlo simulations for a completed backtest.
 */
async function getBacktestSimulation(req, res, next) {
  try {
    const { id: jobId } = req.params

    const backtest = await BacktestResult.findOne({ jobId }).lean()
    if (!backtest) {
      throw new ApiError(404, 'NOT_FOUND', 'Backtest not found')
    }

    if (backtest.status !== 'completed') {
      throw new ApiError(400, 'BAD_REQUEST', 'Backtest must be completed to run simulations')
    }

    const response = await engineClient.post('/backtest/run/leverage-sensitivity', {
      jobId
    })

    res.json(ApiResponse.success(response.data.data))
  } catch (err) {
    next(new ApiError(503, 'ENGINE_UNAVAILABLE', `Simulation failed: ${err.message}`))
  }
}

module.exports = { getRiskSettings, updateRiskSettings, getLiveMetrics, getBacktestSimulation }
