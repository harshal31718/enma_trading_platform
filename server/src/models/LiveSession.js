const mongoose = require('mongoose')

const liveSessionSchema = new mongoose.Schema({
  strategyId: { type: mongoose.Schema.Types.ObjectId, ref: 'Strategy', required: true },
  strategyName: { type: String, required: true },
  symbols: [{ type: String, required: true }],
  timeframe: { type: String, required: true },
  params: { type: Object, default: {} },
  // Risk model params this session runs with (snake_case keys, e.g. risk_pct, rrr).
  riskParams: { type: Object, default: {} },
  mode: { type: String, enum: ['paper', 'live'], default: 'paper' },
  status: {
    type: String,
    enum: ['starting', 'running', 'stopping', 'stopped', 'error'],
    default: 'starting',
  },
  capital: { type: String, required: true },
  leverage: { type: Number, default: 1 },
  createdAt: { type: Date, default: Date.now },
  stoppedAt: { type: Date },
  errorMessage: { type: String },
  pnl: { type: String, default: '0' },
  openPositions: [{ type: String }],
  // Runtime fields written by handleEngineStats
  totalTrades: { type: Number, default: 0 },
  tradeHistory: {
    type: [{ timestamp: { type: Date }, balance: { type: String } }],
    default: [],
  },
  logs: {
    type: [
      {
        type: { type: String, default: 'info' },
        message: { type: String, required: true },
        timestamp: { type: Date, default: Date.now },
      },
    ],
    default: [],
  },
})

liveSessionSchema.index({ status: 1 })
liveSessionSchema.index({ createdAt: -1 })

module.exports = mongoose.model('LiveSession', liveSessionSchema)
