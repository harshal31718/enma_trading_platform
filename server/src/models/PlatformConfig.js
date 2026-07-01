const mongoose = require('mongoose')

const platformConfigSchema = new mongoose.Schema({
  _id: { type: String },
  allowedEmails: [
    {
      email: { type: String, lowercase: true },
      addedBy: { type: String },
      addedAt: { type: Date, default: Date.now },
    },
  ],
})

module.exports = mongoose.model('PlatformConfig', platformConfigSchema)
