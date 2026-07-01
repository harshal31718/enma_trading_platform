const mongoose = require('mongoose')

const settingsSchema = new mongoose.Schema(
  {
    userId: { type: String, required: true, unique: true, index: true },
    encryptedApiKey:    { type: String, default: '' },
    encryptedApiSecret: { type: String, default: '' },
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
    minEdgeMult:        { type: Number, default: 0.0,   min: 0,      max: 10  }, // Cost Model minimum edge multiplier

    // ── Chaos Mode settings (testnet stress-test) ────────────────────────────
    // Caps and launch defaults for the Chaos Mode Wizard (chaos_mode_upgrade.md D5).
    chaosMaxStrategies:    { type: Number, default: 10,    min: 1,   max: 20    }, // hard cap on strategies per chaos run
    chaosMaxManualSymbols: { type: Number, default: 5,     min: 0,   max: 20    }, // max hand-picked symbols per strategy
    chaosDefaultCapital:   { type: Number, default: 500,   min: 1                }, // per-strategy capital pre-fill
    chaosDefaultLeverage:  { type: Number, default: 50,    min: 1,   max: 125   }, // leverage pre-fill
    chaosDefaultTimeframe: {
      type: String,
      default: '1m',
      enum: ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d'],
    },

    // ── Global Hard Constraints (Safety Circuit Breakers) ───────────────────
    globalHardLimits: {
      maxLeverageAllowed:   { type: Number, default: 50,    min: 1,    max: 125 },
      maxSessionDrawdown:   { type: Number, default: 0.30,  min: 0.05, max: 0.90 },
      maxRiskPctPerTrade:   { type: Number, default: 0.05,  min: 0.001,max: 0.20 },
      cooldownPeriodHours:  { type: Number, default: 12,    min: 1,    max: 72   },
    },

    // ── Strategy-Specific Custom Rules ────────────────────────────────────────
    // Keyed by Strategy Name (e.g., "AdaptiveTrend", "MicroScalper")
    strategyOverrides: {
      type: Map,
      of: new mongoose.Schema({
        riskPct:            { type: Number, min: 0.0001, max: 1   },
        riskRewardRatio:    { type: Number, min: 0.1,    max: 100 },
        maxSessionDrawdown: { type: Number, min: 0.01,   max: 1   },
        liqBufferPct:       { type: Number, min: 0,      max: 0.5 },
        minEdgeMult:        { type: Number, min: 0,      max: 10  },
        customAtrMult:      { type: Number }, // Strategy specific stop mults
      }, { _id: false }),
      default: {}
    },

    // ── Symbol-Specific Risk Parameters ─────────────────────────────────────
    // Keyed by Symbol Name (e.g., "BTCUSDT", "SOLUSDT")
    symbolOverrides: {
      type: Map,
      of: new mongoose.Schema({
        maxLeverage:        { type: Number, min: 1, max: 125 },
        volatilityMultiplier: { type: Number, default: 1.0 }, // scaling factor for ATR stops
        maxExposureNotional:{ type: Number, min: 100 },       // max dollar size allowed
      }, { _id: false }),
      default: {}
    },
  },
  { timestamps: true }
)

module.exports = mongoose.model('Settings', settingsSchema)
