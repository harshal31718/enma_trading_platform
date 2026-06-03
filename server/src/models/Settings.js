const mongoose = require('mongoose')

const settingsSchema = new mongoose.Schema(
  {
    _id: { type: String, default: 'global' },
    binanceApiKey: { type: String, default: '' },
    binanceApiSecret: { type: String, default: '' },
    paperTrading: { type: Boolean, default: true },
  },
  { timestamps: true }
)

module.exports = mongoose.model('Settings', settingsSchema)
