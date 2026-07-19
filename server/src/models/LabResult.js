const mongoose = require('mongoose')

// Engine-owned results/status (same ownership rule as BacktestResult: server
// creates the queued doc + updates status/error only, engine writes the full
// `results` object). `type: 'monte_carlo'` (Plan 10 Phase 1), `'optimization'`
// (Plan 10 Phase 3a, walk-forward), and `'pbo'` (Probability of Backtest
// Overfitting / CSCV — the last Plan 10 item, a full-range optimizer run
// scored via combinatorial subsampling, deliberately NOT a walk-forward
// variant) are all live.
const LabResultSchema = new mongoose.Schema(
  {
    userId: { type: String, required: true, index: true },
    labId: { type: String, required: true, unique: true, index: true },
    type: { type: String, enum: ['monte_carlo', 'optimization', 'pbo'], required: true },
    sourceJobId: { type: String, index: true }, // parent backtest jobId (monte_carlo)
    // Full config, always — never re-derived from an unpersisted parent
    // field (the QNT-17 bug class this plan exists to avoid).
    config: { type: mongoose.Schema.Types.Mixed, required: true },
    configHash: { type: String, required: true, index: true },
    status: { type: String, enum: ['queued', 'running', 'completed', 'failed', 'cancelled'], default: 'queued' },
    error: { type: String },
    // Engine-owned — server never writes this field.
    results: { type: mongoose.Schema.Types.Mixed },
    completedAt: { type: Date },
  },
  { timestamps: true, collection: 'labResults' }
)

// Cache lookup for "re-submitting identical config returns cached" (Plan 10
// Phase 1 acceptance criterion).
LabResultSchema.index({ userId: 1, sourceJobId: 1, configHash: 1, type: 1 })
LabResultSchema.index({ userId: 1, createdAt: -1 })

module.exports = mongoose.model('LabResult', LabResultSchema)
