// Resolves the risk-model parameters for a backtest or live bot run.
//
// Precedence per field: per-run override (from the client) → saved global Risk
// setting → hardcoded fallback. Values are clamped to the same ranges enforced
// by the Settings schema, then mapped to the engine's snake_case contract
// (risk_pct, rrr, max_session_dd, liq_buffer_pct) consumed by
// backtest_runner.py and live_bot_manager.py.

// camelCase client/settings field → { engine key, fallback, min, max }
const RISK_FIELDS = {
  riskPct:            { engineKey: 'risk_pct',       fallback: 0.01,  min: 0.0001, max: 1   },
  riskRewardRatio:    { engineKey: 'rrr',            fallback: 2.0,   min: 0.1,    max: 100 },
  maxSessionDrawdown: { engineKey: 'max_session_dd', fallback: 0.20,  min: 0.01,   max: 1   },
  liqBufferPct:       { engineKey: 'liq_buffer_pct', fallback: 0.005, min: 0,      max: 0.5 },
  minEdgeMult:        { engineKey: 'min_edge_mult',  fallback: 0.0,   min: 0,      max: 10  },
}

const clamp = (n, min, max) => Math.min(max, Math.max(min, n))

/**
 * @param {object} savedSettings  Lean Settings doc (global risk defaults). May be {}.
 * @param {object} [override]     Per-run camelCase overrides from the client. May be undefined.
 * @returns {object} engine risk_params dict with snake_case keys (all fields present).
 */
function resolveModelParams(savedSettings = {}, override = {}) {
  const ovr = override || {}
  const out = {}
  for (const [field, rule] of Object.entries(RISK_FIELDS)) {
    // Pick the first source that yields a finite number.
    let val = Number(ovr[field])
    if (!isFinite(val)) val = Number(savedSettings[field])
    if (!isFinite(val)) val = rule.fallback
    out[rule.engineKey] = clamp(val, rule.min, rule.max)
  }
  return out
}

const resolveRiskParams = resolveModelParams;

/**
 * Resolves final risk parameters for a backtest or live session symbol.
 * Handles the cascading priority: Wizard Override -> Strategy Override -> Symbol Override -> Global defaults.
 * Clamps output values by Global Hard Limits.
 */
function resolveStrategyRiskParams(strategyName, symbol, savedSettings = {}, wizardOverride = {}) {
  // Mongoose Maps come back as plain objects after .lean() — use bracket access
  const strategyRules = (savedSettings.strategyOverrides || {})[strategyName] || {};
  const symbolRules   = (savedSettings.symbolOverrides   || {})[symbol]       || {};
  const hardLimits    = savedSettings.globalHardLimits   || {};

  // Normalise override keys (accepts camelCase or snake_case from client)
  const normOvr = normaliseKeys(wizardOverride);
  const out = {};
  
  // Resolve base fields and map to engine's snake_case contract
  for (const [camelField, rule] of Object.entries(RISK_FIELDS)) {
    let val = normOvr[camelField];
    if (val == null || !isFinite(Number(val))) val = strategyRules[camelField];
    if (val == null || !isFinite(Number(val))) val = symbolRules[camelField];
    if (val == null || !isFinite(Number(val))) val = savedSettings[camelField]; // top-level defaults
    if (val == null || !isFinite(Number(val))) val = rule.fallback;
    val = Number(val);
    
    // Clamp by Global Hard Limits (using correct schema keys)
    if (camelField === 'riskPct' && isFinite(hardLimits.maxRiskPctPerTrade)) {
      val = Math.min(val, hardLimits.maxRiskPctPerTrade);
    }
    if (camelField === 'maxSessionDrawdown' && isFinite(hardLimits.maxSessionDrawdown)) {
      val = Math.min(val, hardLimits.maxSessionDrawdown);
    }
    
    out[rule.engineKey] = clamp(val, rule.min, rule.max);
  }
  
  // Resolve leverage specifically (independent path - no RISK_FIELDS entry)
  let lev = Number(normOvr.leverage);
  if (!isFinite(lev)) lev = Number(symbolRules.maxLeverage);
  if (!isFinite(lev)) lev = Number(savedSettings.defaultLeverage);
  if (!isFinite(lev)) lev = 1;
  
  if (isFinite(hardLimits.maxLeverageAllowed)) {
    lev = Math.min(lev, hardLimits.maxLeverageAllowed);
  }
  out.leverage = clamp(lev, 1, 125);
  
  // Custom settings passed through to engine
  out.volatility_multiplier = Number(symbolRules.volatilityMultiplier ?? 1.0);
  out.max_exposure_notional = Number(symbolRules.maxExposureNotional ?? Infinity);
  out.custom_atr_mult       = strategyRules.customAtrMult != null ? Number(strategyRules.customAtrMult) : null;

  return out;
}

function normaliseKeys(obj = {}) {
  const out = {};
  for (const [k, v] of Object.entries(obj)) {
    const camel = k.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
    out[camel] = v;
    out[k] = v;
  }
  return out;
}

module.exports = {
  resolveModelParams,
  resolveRiskParams,
  resolveStrategyRiskParams,
  clamp,
  RISK_FIELDS
}
