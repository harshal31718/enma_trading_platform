const mongoose = require('mongoose')

const BacktestTradeSchema = new mongoose.Schema(
  {
    jobId:       { type: String, required: true, index: true },
    tradeIndex:  { type: Number, required: true },  // 1-based sequential id within the backtest
    type:        { type: String, enum: ['long', 'short'] },
    qty:         { type: String },
    entryPrice:  { type: String },
    exitPrice:   { type: String },
    entryAt:     { type: String },
    exitAt:      { type: String },
    exitReason:  { type: String },
    pnl:         { type: String },
    pnlPct:      { type: String },
  },
  { timestamps: false, collection: 'backtestTrades' }
)

// Compound index: fetch all trades for a job ordered by sequence
BacktestTradeSchema.index({ jobId: 1, tradeIndex: 1 })

module.exports = mongoose.model('BacktestTrade', BacktestTradeSchema)
