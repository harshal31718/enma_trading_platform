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

  // Plan 22 Step 22.7: Session Risk Governor knobs — global-only (no
  // strategy/symbol override tier; these are account-wide circuit breakers,
  // not per-symbol risk math like RISK_FIELDS above). Passed through as
  // top-level snake_case keys — `live_bot_manager.py`'s `start_session`
  // governor_cfg cascade already reads each of these as a flat fallback
  // (22.1/22.4/22.5/22.6's own wiring), so no engine-side change is needed
  // here. Omitted entirely when unset/null — the governor's own hardcoded
  // default (on or off, per field) takes over, same as today.
  if (isFinite(Number(hardLimits.maxDailyLossPct))) out.max_daily_loss_pct = Number(hardLimits.maxDailyLossPct);
  if (isFinite(Number(hardLimits.maxMarginUtilization))) out.max_margin_utilization = Number(hardLimits.maxMarginUtilization);
  if (isFinite(Number(hardLimits.varLimitPct))) out.var_limit_pct = Number(hardLimits.varLimitPct);
  if (isFinite(Number(hardLimits.cvarLimitPct))) out.cvar_limit_pct = Number(hardLimits.cvarLimitPct);
  if (isFinite(Number(hardLimits.correlationCap?.rho))) {
    out.correlation_cap = {
      rho: Number(hardLimits.correlationCap.rho),
      max_cluster_exposure_pct: isFinite(Number(hardLimits.correlationCap.maxClusterExposurePct))
        ? Number(hardLimits.correlationCap.maxClusterExposurePct) : 0.4,
    };
  }
  // allocation is the one governor-adjacent field that IS wizard-overridable
  // (Plan 22 Step 22.6's own wording: "wizard dropdown + Chaos settings"),
  // unlike the account-wide circuit breakers above — precedence: wizard
  // override > Zone 2 global default > "equal" (omitted).
  const allocationChoice = normOvr.allocation ?? hardLimits.allocation;
  if (allocationChoice === 'inverse_vol') out.allocation = 'inverse_vol';
  if (hardLimits.breachAction === 'halted' || hardLimits.breachAction === 'reducing') out.breach_action = hardLimits.breachAction;
  if (hardLimits.autoFlattenOnHalt === true) out.auto_flatten_on_halt = true;

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
