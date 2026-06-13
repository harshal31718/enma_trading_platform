const mongoose = require('mongoose')

const settingsSchema = new mongoose.Schema(
  {
    _id: { type: String, default: 'global' },
    mode: {
      type: String,
      enum: ['testnet', 'mainnet'],
      default: 'testnet',
    },

    // ── Trading fees ─────────────────────────────────────────────────────────
    // Stored as raw decimal fractions (0.0005 = 0.05%).
    // Binance USDⓈ-M standard: taker 0.0005, maker 0.0002.
    takerFee:  { type: Number, default: 0.0005, min: 0, max: 0.01 },
    makerFee:  { type: Number, default: 0.0002, min: 0, max: 0.01 },

    // ── Backtest simulation realism ──────────────────────────────────────────
    slippagePct:     { type: Number, default: 0.0005, min: 0,     max: 0.05  },
    fundingEnabled:  { type: Boolean, default: false },
    fundingRate:     { type: Number, default: 0.0001, min: 0,     max: 0.01  },

    // ── Backtest form defaults (pre-fill only, user can override) ────────────
    defaultCapital:  { type: Number, default: 10000,  min: 1                 },
    defaultLeverage: { type: Number, default: 1,      min: 1,    max: 125    },

    // ── Bot wizard defaults ──────────────────────────────────────────────────
    defaultBotCapital:  { type: Number, default: 1000, min: 1                },
    defaultBotLeverage: { type: Number, default: 1,    min: 1,   max: 125    },
  },
  { timestamps: true }
)

module.exports = mongoose.model('Settings', settingsSchema)
