const mongoose = require('mongoose')

const TradeTransactionSchema = new mongoose.Schema(
  {
    userId:     { type: String, index: true },
    tranId:     { type: String, required: true, unique: true, index: true },
    symbol:     { type: String, index: true },
    incomeType: { type: String, required: true, index: true },
    income:     { type: String, required: true },
    asset:      { type: String, required: true },
    time:       { type: Date, required: true, index: true },
  },
  { timestamps: false, collection: 'tradeTransactions' }
)

TradeTransactionSchema.index({ symbol: 1, time: -1 })

module.exports = mongoose.model('TradeTransaction', TradeTransactionSchema)
