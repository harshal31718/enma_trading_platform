const { resolveModelParams, resolveStrategyRiskParams, clamp } = require('../risk')

describe('clamp', () => {
  test('clamps below min and above max', () => {
    expect(clamp(-5, 0, 10)).toBe(0)
    expect(clamp(15, 0, 10)).toBe(10)
    expect(clamp(5, 0, 10)).toBe(5)
  })
})

describe('resolveModelParams', () => {
  test('falls back to hardcoded defaults when nothing is provided', () => {
    const out = resolveModelParams({}, {})
    expect(out.risk_pct).toBeCloseTo(0.01)
    expect(out.rrr).toBeCloseTo(2.0)
    expect(out.max_session_dd).toBeCloseTo(0.20)
  })

  test('per-run override takes precedence over saved settings', () => {
    const out = resolveModelParams({ riskPct: 0.05 }, { riskPct: 0.02 })
    expect(out.risk_pct).toBeCloseTo(0.02)
  })

  test('saved settings are used when no override is given', () => {
    const out = resolveModelParams({ riskPct: 0.05 }, {})
    expect(out.risk_pct).toBeCloseTo(0.05)
  })

  test('non-finite override values are ignored, falling through to settings/defaults', () => {
    const out = resolveModelParams({ riskPct: 0.05 }, { riskPct: 'not-a-number' })
    expect(out.risk_pct).toBeCloseTo(0.05)
  })

  test('values are clamped to the field range even when explicitly overridden', () => {
    const out = resolveModelParams({}, { riskPct: 5 }) // max is 1
    expect(out.risk_pct).toBeLessThanOrEqual(1)
  })
})

describe('resolveStrategyRiskParams', () => {
  test('precedence: wizard override > strategy override > symbol override > global default', () => {
    const settings = {
      riskPct: 0.01,
      strategyOverrides: { MyStrat: { riskPct: 0.02 } },
      symbolOverrides: { BTCUSDT: { riskPct: 0.03 } },
    }
    const out = resolveStrategyRiskParams('MyStrat', 'BTCUSDT', settings, { riskPct: 0.04 })
    expect(out.risk_pct).toBeCloseTo(0.04)
  })

  test('falls back to symbol override when no wizard/strategy override present', () => {
    const settings = {
      symbolOverrides: { BTCUSDT: { riskPct: 0.03 } },
    }
    const out = resolveStrategyRiskParams('MyStrat', 'BTCUSDT', settings, {})
    expect(out.risk_pct).toBeCloseTo(0.03)
  })

  test('global hard limit caps riskPct even if a lower-precedence source requests more', () => {
    const settings = {
      globalHardLimits: { maxRiskPctPerTrade: 0.02 },
    }
    const out = resolveStrategyRiskParams('MyStrat', 'BTCUSDT', settings, { riskPct: 0.5 })
    expect(out.risk_pct).toBeLessThanOrEqual(0.02)
  })

  test('leverage resolves independently and is clamped to [1, 125]', () => {
    const settings = {}
    const out = resolveStrategyRiskParams('MyStrat', 'BTCUSDT', settings, { leverage: 500 })
    expect(out.leverage).toBe(125)
  })

  test('leverage hard limit caps an explicit override', () => {
    const settings = { globalHardLimits: { maxLeverageAllowed: 10 } }
    const out = resolveStrategyRiskParams('MyStrat', 'BTCUSDT', settings, { leverage: 50 })
    expect(out.leverage).toBeLessThanOrEqual(10)
  })

  test('accepts snake_case override keys as well as camelCase', () => {
    const out = resolveStrategyRiskParams('MyStrat', 'BTCUSDT', {}, { risk_pct: 0.07 })
    expect(out.risk_pct).toBeCloseTo(0.07)
  })
})
