const mongoose = require('mongoose')

const BacktestResultSchema = new mongoose.Schema(
  {
    userId: { type: String, index: true },
    jobId: { type: String, required: true, unique: true, index: true },
    strategyId: { type: String },
    strategyName: { type: String },
    exchange: { type: String },
    symbol: { type: String },
    timeframe: { type: String },
    startDate: { type: String },
    endDate: { type: String },
    capital: { type: Number },
    leverage: { type: Number },
    feeRate: { type: Number },
    // Risk model params this run used (snake_case keys, e.g. risk_pct, rrr).
    // Server-owned config input — not an engine-written result field.
    riskParams: { type: mongoose.Schema.Types.Mixed },
    // Strategy alpha params (Tier 3) this run used — keyed by PARAMS name.
    // Server-owned config input — not an engine-written result field.
    alphaParams: { type: mongoose.Schema.Types.Mixed },
    status: { type: String, enum: ['queued', 'running', 'completed', 'failed', 'cancelled'], default: 'queued' },
    error: { type: String },
    tradeCount: { type: Number },
    metrics: { type: mongoose.Schema.Types.Mixed },
    trades: { type: mongoose.Schema.Types.Mixed },
    equityCurve: { type: mongoose.Schema.Types.Mixed },
    // Phase 2 — extra curves (A-009 / A-010 / A-011)
    underwaterCurve: { type: mongoose.Schema.Types.Mixed },
    rollingMetricsCurve: { type: mongoose.Schema.Types.Mixed },
    returnsHistogram: { type: mongoose.Schema.Types.Mixed },
    mfeMaeScatter: { type: mongoose.Schema.Types.Mixed },
  },
  { timestamps: true, collection: 'backtestResults' }
)

BacktestResultSchema.index({ status: 1 })
BacktestResultSchema.index({ symbol: 1 })
BacktestResultSchema.index({ strategyId: 1, createdAt: -1 })
BacktestResultSchema.index({ userId: 1, createdAt: -1 })

module.exports = mongoose.model('BacktestResult', BacktestResultSchema)
