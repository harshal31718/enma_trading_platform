const mongoose = require('mongoose')

const BacktestLeverageScenarioSchema = new mongoose.Schema(
  {
    sourceJobId: { type: String, required: true, index: true },
    leverage: { type: Number, required: true },
    netProfitPct: { type: String, required: true },
    maxDrawdownPct: { type: String, required: true },
    metrics: { type: mongoose.Schema.Types.Mixed },
    equityCurve: { type: mongoose.Schema.Types.Mixed },
  },
  { timestamps: true, collection: 'backtestLeverageScenarios' }
)

BacktestLeverageScenarioSchema.index({ sourceJobId: 1, leverage: 1 }, { unique: true })

module.exports = mongoose.model('BacktestLeverageScenario', BacktestLeverageScenarioSchema)
