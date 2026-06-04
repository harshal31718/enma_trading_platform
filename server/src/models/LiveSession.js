const mongoose = require('mongoose')

const liveSessionSchema = new mongoose.Schema(
  {
    strategyId: { type: mongoose.Schema.Types.ObjectId, ref: 'Strategy', required: true },
    strategyName: { type: String, required: true },
    symbols: { type: [String], required: true },
    timeframe: { type: String, required: true },
    params: { type: mongoose.Schema.Types.Mixed, default: {} },
    mode: { type: String, enum: ['paper', 'live'], default: 'paper' },
    status: {
      type: String,
      enum: ['starting', 'running', 'stopping', 'stopped', 'error'],
      default: 'starting',
    },
    capital: { type: String, required: true },
    leverage: { type: Number, default: 1 },
    stoppedAt: { type: Date },
    errorMessage: { type: String },
    pnl: { type: String, default: '0' },
    openPositions: { type: [String], default: [] },
  },
  { timestamps: true }
)

liveSessionSchema.index({ status: 1 })
liveSessionSchema.index({ createdAt: -1 })

module.exports = mongoose.model('LiveSession', liveSessionSchema)
