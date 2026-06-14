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

    // ── Risk model defaults (Tier 2) ─────────────────────────────────────────
    // Stored as raw fractions/ratios. Pre-fill the backtest form and bot
    // wizard; either run can override per-run. Mapped to the engine's
    // snake_case risk_params (risk_pct, rrr, max_session_dd, liq_buffer_pct).
    riskPct:            { type: Number, default: 0.01,  min: 0.0001, max: 1   }, // fraction of equity risked per trade
    riskRewardRatio:    { type: Number, default: 2.0,   min: 0.1,    max: 100 }, // reward:risk multiple for take-profit
    maxSessionDrawdown: { type: Number, default: 0.20,  min: 0.01,   max: 1   }, // equity drawdown that halts new entries
    liqBufferPct:       { type: Number, default: 0.005, min: 0,      max: 0.5 }, // min gap between stop-loss and liquidation
  },
  { timestamps: true }
)

module.exports = mongoose.model('Settings', settingsSchema)
