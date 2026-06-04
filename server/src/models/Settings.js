const mongoose = require('mongoose')
const { encrypt, decrypt } = require('../utils/encryption')

const settingsSchema = new mongoose.Schema(
  {
    _id: { type: String, default: 'global' },
    binanceApiKey: {
      type: String,
      default: '',
      get: decrypt,
      set: encrypt,
    },
    binanceApiSecret: {
      type: String,
      default: '',
      get: decrypt,
      set: encrypt,
    },
    paperTrading: { type: Boolean, default: true },
  },
  {
    timestamps: true,
    toJSON: { getters: true },
    toObject: { getters: true },
  }
)

module.exports = mongoose.model('Settings', settingsSchema)
