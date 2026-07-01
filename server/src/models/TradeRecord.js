const mongoose = require('mongoose')

const TradeRecordSchema = new mongoose.Schema(
  {
    userId:           { type: String, required: false, index: true },
    tradeId:          { type: String, required: true, unique: true, index: true },
    source:           { type: String, enum: ['bot', 'manual'], required: true, index: true },
    executedBy:       { type: String, required: true, index: true },
    symbol:           { type: String, required: true, index: true },
    side:             { type: String, enum: ['long', 'short'], required: true },
    qty:              { type: String, required: true },

    entryPrice:       { type: String, required: true },
    exitPrice:        { type: String, required: true },
    slOrderPrice:     { type: String },
    tpOrderPrice:     { type: String },
    margin:           { type: String },
    liquidationPrice: { type: String },
    leverage:         { type: Number },

    netPnl:           { type: String, required: true },
    pnlPct:           { type: String },
    fee:              { type: String },
    exitReason:       { type: String, required: true },
    entryTag:         { type: String },
    exitTag:          { type: String },

    sessionId:        { type: String, index: true },
    strategyName:     { type: String },

    entryTime:        { type: Date, required: true },
    exitTime:         { type: Date, required: true, index: -1 },
    createdAt:        { type: Date, required: true },
  },
  { timestamps: false, collection: 'tradeRecords' }
)

TradeRecordSchema.index({ exitTime: -1 })
TradeRecordSchema.index({ symbol: 1, exitTime: -1 })
TradeRecordSchema.index({ source: 1, exitTime: -1 })
TradeRecordSchema.index({ executedBy: 1, exitTime: -1 })

module.exports = mongoose.model('TradeRecord', TradeRecordSchema)