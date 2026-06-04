const mongoose = require('mongoose')

const BacktestResultSchema = new mongoose.Schema(
  {
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
    status: { type: String, enum: ['queued', 'running', 'completed', 'failed'], default: 'queued' },
    error: { type: String },
    metrics: { type: mongoose.Schema.Types.Mixed },
    trades: { type: mongoose.Schema.Types.Mixed },
    equityCurve: { type: mongoose.Schema.Types.Mixed },
  },
  { timestamps: true, collection: 'backtestResults' }
)

BacktestResultSchema.index({ status: 1 })
BacktestResultSchema.index({ symbol: 1 })
BacktestResultSchema.index({ strategyId: 1, createdAt: -1 })

module.exports = mongoose.model('BacktestResult', BacktestResultSchema)
