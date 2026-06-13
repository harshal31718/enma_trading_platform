const mongoose = require('mongoose')

const TradeExecutionSchema = new mongoose.Schema(
  {
    id:              { type: String, required: true, unique: true, index: true },
    orderId:         { type: String, required: true, index: true },
    symbol:          { type: String, required: true, index: true },
    side:            { type: String, required: true },
    price:           { type: String, required: true },
    qty:             { type: String, required: true },
    commission:      { type: String },
    commissionAsset: { type: String },
    time:            { type: Date, required: true, index: true },
    realizedPnl:     { type: String },
    maker:           { type: Boolean },
  },
  { timestamps: false, collection: 'tradeExecutions' }
)

TradeExecutionSchema.index({ symbol: 1, time: -1 })

module.exports = mongoose.model('TradeExecution', TradeExecutionSchema)
