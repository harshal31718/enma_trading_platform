const Settings = require('../models/Settings')
const ApiResponse = require('../utils/ApiResponse')
const ApiError = require('../utils/ApiError')

// Fields exposed by the exchange settings API (excludes `mode` which lives on trade routes)
const EXCHANGE_FIELDS = [
  'takerFee', 'makerFee',
  'slippagePct', 'fundingEnabled', 'fundingRate',
  'defaultCapital', 'defaultLeverage',
  'defaultBotCapital', 'defaultBotLeverage',
  'riskPct', 'riskRewardRatio', 'maxSessionDrawdown', 'liqBufferPct', 'minEdgeMult',
  // Chaos Mode settings (D5)
  'chaosMaxStrategies', 'chaosMaxManualSymbols', 'chaosDefaultCapital', 'chaosDefaultLeverage',
  'chaosDefaultTimeframe',
]

// Validation ranges matching the Mongoose schema
const FIELD_RULES = {
  takerFee:              { min: 0,      max: 0.01  },
  makerFee:              { min: 0,      max: 0.01  },
  slippagePct:           { min: 0,      max: 0.05  },
  fundingRate:           { min: 0,      max: 0.01  },
  defaultCapital:        { min: 1                  },
  defaultLeverage:       { min: 1,      max: 125   },
  defaultBotCapital:     { min: 1                  },
  defaultBotLeverage:    { min: 1,      max: 125   },
  riskPct:               { min: 0.0001, max: 1     },
  riskRewardRatio:       { min: 0.1,    max: 100   },
  maxSessionDrawdown:    { min: 0.01,   max: 1     },
  liqBufferPct:          { min: 0,      max: 0.5   },
  minEdgeMult:           { min: 0,      max: 10    },
  // Chaos Mode fields (numeric; chaosDefaultTimeframe handled separately)
  chaosMaxStrategies:    { min: 1,      max: 20    },
  chaosMaxManualSymbols: { min: 0,      max: 20    },
  chaosDefaultCapital:   { min: 1                  },
  chaosDefaultLeverage:  { min: 1,      max: 125   },
}

const CHAOS_TIMEFRAME_ALLOWLIST = ['1m','3m','5m','15m','30m','1h','2h','4h','6h','8h','12h','1d']

async function _getOrCreate() {
  let settings = await Settings.findById('global')
  if (!settings) settings = await Settings.create({ _id: 'global' })
  return settings
}

async function getExchangeSettings(req, res, next) {
  try {
    const settings = await _getOrCreate()
    const data = {}
    for (const field of EXCHANGE_FIELDS) {
      data[field] = settings[field]
    }
    res.json(ApiResponse.success(data))
  } catch (err) {
    next(err)
  }
}

async function updateExchangeSettings(req, res, next) {
  try {
    const updates = {}

    for (const field of EXCHANGE_FIELDS) {
      if (!(field in req.body)) continue

      const val = req.body[field]

      // ── Boolean special-case ─────────────────────────────────────────────────
      if (field === 'fundingEnabled') {
        if (typeof val !== 'boolean') {
          throw new ApiError(400, 'VALIDATION_ERROR', `${field} must be a boolean`)
        }
        updates[field] = val
        continue
      }

      // ── String allowlist special-case (chaosDefaultTimeframe) ───────────────
      if (field === 'chaosDefaultTimeframe') {
        if (!CHAOS_TIMEFRAME_ALLOWLIST.includes(val)) {
          throw new ApiError(400, 'VALIDATION_ERROR',
            `chaosDefaultTimeframe must be one of: ${CHAOS_TIMEFRAME_ALLOWLIST.join(', ')}`)
        }
        updates[field] = val
        continue
      }

      // ── Numeric fields ───────────────────────────────────────────────────────
      const num = Number(val)
      if (!isFinite(num)) {
        throw new ApiError(400, 'VALIDATION_ERROR', `${field} must be a number`)
      }
      const rules = FIELD_RULES[field] || {}
      if (rules.min !== undefined && num < rules.min) {
        throw new ApiError(400, 'VALIDATION_ERROR', `${field} must be >= ${rules.min}`)
      }
      if (rules.max !== undefined && num > rules.max) {
        throw new ApiError(400, 'VALIDATION_ERROR', `${field} must be <= ${rules.max}`)
      }
      if (['defaultLeverage', 'defaultBotLeverage', 'chaosMaxStrategies', 'chaosMaxManualSymbols', 'chaosDefaultLeverage'].includes(field) && !Number.isInteger(num)) {
        throw new ApiError(400, 'VALIDATION_ERROR', `${field} must be an integer`)
      }
      updates[field] = num
    }

    if (Object.keys(updates).length === 0) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'No valid fields to update')
    }

    const settings = await Settings.findByIdAndUpdate(
      'global',
      { $set: updates },
      { new: true, upsert: true }
    )

    const data = {}
    for (const field of EXCHANGE_FIELDS) {
      data[field] = settings[field]
    }
    res.json(ApiResponse.success(data))
  } catch (err) {
    next(err)
  }
}

module.exports = { getExchangeSettings, updateExchangeSettings }
