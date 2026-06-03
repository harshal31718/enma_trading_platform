const mongoose = require('mongoose')

const candleImportSchema = new mongoose.Schema({
  jobId: { type: String, required: true, unique: true },
  exchange: { type: String, required: true },
  symbol: { type: String, required: true },
  timeframe: { type: String, required: true },
  startDate: { type: String, required: true },
  endDate: { type: String, required: true },
  candleCount: { type: Number, default: 0 },
  status: {
    type: String,
    enum: ['queued', 'running', 'completed', 'failed'],
    default: 'queued',
  },
  error: { type: String },
  importedAt: { type: Date },
}, { timestamps: true })

candleImportSchema.index({ symbol: 1, timeframe: 1, exchange: 1 })

module.exports = mongoose.model('CandleImport', candleImportSchema)
