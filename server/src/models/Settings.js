const mongoose = require('mongoose')

const settingsSchema = new mongoose.Schema(
  {
    _id: { type: String, default: 'global' },
    mode: {
      type: String,
      enum: ['testnet', 'mainnet'],
      default: 'testnet',
    },
  },
  { timestamps: true }
)

module.exports = mongoose.model('Settings', settingsSchema)
