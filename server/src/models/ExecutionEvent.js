const mongoose = require('mongoose')

// Plan 5 Step 5.1 (SYS-2/SRV-3): read-only projection of the engine's
// append-only execution event log. Engine (`services/event_log.py`) is the
// sole writer — server only reads, same ownership pattern as TradeRecord.
// Not yet used as the live-state source of truth (see event_log.py's module
// docstring) — this model exists for audit/debugging queries and as the
// foundation Step 5.6's restart-recovery will read from.
const ExecutionEventSchema = new mongoose.Schema(
  {
    sessionId:     { type: String, required: true, index: true },
    symbol:        { type: String, required: true, index: true },
    seq:           { type: Number, required: true },
    eventType:     { type: String, required: true },
    clientOrderId: { type: String },
    payload:       { type: mongoose.Schema.Types.Mixed },
    createdAt:     { type: Date, required: true },
  },
  { timestamps: false, collection: 'executionEvents' }
)

ExecutionEventSchema.index({ sessionId: 1, symbol: 1, seq: 1 })

module.exports = mongoose.model('ExecutionEvent', ExecutionEventSchema)
