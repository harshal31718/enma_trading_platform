const mongoose = require('mongoose')

const TradeOrderSchema = new mongoose.Schema(
  {
    userId:        { type: String, index: true },
    orderId:       { type: String, required: true, unique: true, index: true },
    clientOrderId: { type: String, index: true },
    symbol:        { type: String, required: true, index: true },
    status:        { type: String, required: true, index: true },
    price:         { type: String },
    avgPrice:      { type: String },
    origQty:       { type: String },
    executedQty:   { type: String },
    side:          { type: String, required: true },
    type:          { type: String, required: true },
    timeInForce:   { type: String },
    stopPrice:     { type: String },
    time:          { type: Date, required: true, index: true },
    updateTime:    { type: Date },
    reduceOnly:    { type: Boolean },
    postOnly:      { type: Boolean },
    isAlgo:        { type: Boolean, default: false },
  },
  { timestamps: false, collection: 'tradeOrders' }
)

TradeOrderSchema.index({ symbol: 1, time: -1 })

module.exports = mongoose.model('TradeOrder', TradeOrderSchema)
