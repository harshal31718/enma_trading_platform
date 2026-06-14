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
}

const clamp = (n, min, max) => Math.min(max, Math.max(min, n))

/**
 * @param {object} savedSettings  Lean Settings doc (global risk defaults). May be {}.
 * @param {object} [override]     Per-run camelCase overrides from the client. May be undefined.
 * @returns {object} engine risk_params dict with snake_case keys (all fields present).
 */
function resolveRiskParams(savedSettings = {}, override = {}) {
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

module.exports = { resolveRiskParams, RISK_FIELDS }
