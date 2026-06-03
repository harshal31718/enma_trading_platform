const mongoose = require('mongoose')

const strategySchema = new mongoose.Schema({
  name: { type: String, required: true, unique: true },
  description: { type: String, default: '' },
  filePath: { type: String, required: true },
}, { timestamps: true })

strategySchema.index({ name: 1 })

module.exports = mongoose.model('Strategy', strategySchema)
