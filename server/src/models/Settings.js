const mongoose = require('mongoose')

const settingsSchema = new mongoose.Schema(
  {
    userId: { type: String, required: true, unique: true, index: true },
    // Testnet pair — used for all trading (manual + bots).
    encryptedApiKey:    { type: String, default: '' },
    encryptedApiSecret: { type: String, default: '' },
    // Mainnet pair — READ-ONLY, used only to display the mainnet balance on the
    // Dashboard. Never used for order placement (see requireBinanceCredentials,
    // which pins X-Binance-Mode to testnet). Keys are verified before storage.
    encryptedMainnetApiKey:    { type: String, default: '' },
    encryptedMainnetApiSecret: { type: String, default: '' },
    // Vestigial: trading is pinned to testnet. Retained to avoid a migration.
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
    // Caps and launch defaults for the Chaos Mode Wizard (see DECISIONS.md #16 D5).
    // chaosMaxStrategies REMOVED — superseded by limits.testnet.maxConcurrentBots below.
    chaosMaxManualSymbols: { type: Number, default: 5,     min: 0,   max: 20    }, // max hand-picked symbols per strategy
    chaosDefaultCapital:   { type: Number, default: 500,   min: 1                }, // per-strategy capital pre-fill
    chaosDefaultLeverage:  { type: Number, default: 50,    min: 1,   max: 125   }, // leverage pre-fill
    chaosDefaultTimeframe: {
      type: String,
      default: '1m',
      enum: ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d'],
    },
    // Sum-of-symbols ceiling for one Chaos run (all strategies combined). Testnet-only —
    // no mainnet chaos mode exists or is planned. Top-level (not under `limits` below) —
    // every other layer (settings.controller.js, algo.controller.js, Settings.jsx,
    // ChaosWizard.jsx) reads/writes this as a flat field; keep it that way.
    chaosMaxTotalSymbols: { type: Number, default: 120, min: 1, max: 250 },

    // ── Bot Session Limits (Safety Caps) ──────────────────────────────────────
    // Configurable ceilings on live-session size, enforced by algo.controller.js before
    // a bot/chaos strategy launches. `mainnet` is pure future-proofing — no code path can
    // start a mainnet session today (trading is hard-pinned to testnet everywhere; see
    // live_bot_manager.py, LiveSession.mode always 'paper'). Do not add mainnet enforcement
    // logic against these fields until mainnet live trading actually exists.
    limits: {
      testnet: {
        maxSymbolsPerBot:  { type: Number, default: 15, min: 1, max: 30 },
        maxConcurrentBots: { type: Number, default: 10, min: 1, max: 20 },
      },
      mainnet: {
        maxSymbolsPerBot:  { type: Number, default: 15, min: 1, max: 30 },
        maxConcurrentBots: { type: Number, default: 10, min: 1, max: 20 },
      },
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

    // ── Webhook Notifications (Plan 14 / fixes-queue F3) ─────────────────────
    // Fire-and-forget POST on trade lifecycle events (Discord/Slack/IFTTT).
    // Dispatch lives in server/src/utils/webhook.js — never blocks or throws
    // into the trade path. `events` is opt-in (freqtrade-style default: only
    // the "you should know about this" events, not every entry/exit).
    webhook: {
      enabled:   { type: Boolean, default: false },
      url:       { type: String,  default: '' },
      format:    { type: String,  enum: ['json', 'form'], default: 'json' },
      events: {
        type: [String],
        default: ['exit_fill', 'liquidation', 'session_error', 'risk_breach'],
        enum: ['entry_fill', 'exit_fill', 'liquidation', 'session_start', 'session_stop', 'session_error', 'risk_breach'],
      },
      retries:   { type: Number, default: 2,    min: 0,    max: 5     },
      timeoutMs: { type: Number, default: 5000, min: 1000, max: 30000 },
    },
  },
  { timestamps: true }
)

module.exports = mongoose.model('Settings', settingsSchema)
