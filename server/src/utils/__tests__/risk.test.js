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

  describe('Plan 22 Step 22.7: Session Risk Governor knobs (global-only)', () => {
    test('governor fields are omitted entirely when globalHardLimits is unset', () => {
      const out = resolveStrategyRiskParams('MyStrat', 'BTCUSDT', {}, {})
      expect(out.max_daily_loss_pct).toBeUndefined()
      expect(out.max_margin_utilization).toBeUndefined()
      expect(out.var_limit_pct).toBeUndefined()
      expect(out.cvar_limit_pct).toBeUndefined()
      expect(out.correlation_cap).toBeUndefined()
      expect(out.allocation).toBeUndefined()
      expect(out.breach_action).toBeUndefined()
      expect(out.auto_flatten_on_halt).toBeUndefined()
    })

    test('passes through maxDailyLossPct/maxMarginUtilization/varLimitPct/cvarLimitPct as snake_case', () => {
      const settings = {
        globalHardLimits: {
          maxDailyLossPct: 0.1, maxMarginUtilization: 0.75, varLimitPct: 0.05, cvarLimitPct: 0.08,
        },
      }
      const out = resolveStrategyRiskParams('MyStrat', 'BTCUSDT', settings, {})
      expect(out.max_daily_loss_pct).toBeCloseTo(0.1)
      expect(out.max_margin_utilization).toBeCloseTo(0.75)
      expect(out.var_limit_pct).toBeCloseTo(0.05)
      expect(out.cvar_limit_pct).toBeCloseTo(0.08)
    })

    test('correlationCap sub-object passes through with a default maxClusterExposurePct', () => {
      const settings = { globalHardLimits: { correlationCap: { rho: 0.8 } } }
      const out = resolveStrategyRiskParams('MyStrat', 'BTCUSDT', settings, {})
      expect(out.correlation_cap).toEqual({ rho: 0.8, max_cluster_exposure_pct: 0.4 })
    })

    test('correlationCap omitted entirely when rho is not set (off by default)', () => {
      const settings = { globalHardLimits: { correlationCap: { maxClusterExposurePct: 0.5 } } }
      const out = resolveStrategyRiskParams('MyStrat', 'BTCUSDT', settings, {})
      expect(out.correlation_cap).toBeUndefined()
    })

    // Regression (found in live verification 2026-07-19): the client sends rho:null for a
    // blank "off" field. Number(null)===0 previously slipped past isFinite() and armed the
    // cap at rho=0 ("cluster everything"), silently vetoing every live/chaos entry.
    test('correlationCap omitted when rho is null (blank field = off, not rho=0)', () => {
      const settings = { globalHardLimits: { correlationCap: { rho: null, maxClusterExposurePct: 0.4 } } }
      const out = resolveStrategyRiskParams('MyStrat', 'BTCUSDT', settings, {})
      expect(out.correlation_cap).toBeUndefined()
    })

    test('correlationCap omitted when rho is empty string (blank field = off)', () => {
      const settings = { globalHardLimits: { correlationCap: { rho: '', maxClusterExposurePct: 0.4 } } }
      const out = resolveStrategyRiskParams('MyStrat', 'BTCUSDT', settings, {})
      expect(out.correlation_cap).toBeUndefined()
    })

    test('var/cvar/margin/dailyLoss omitted when null (blank = off, not a 0 limit)', () => {
      const settings = {
        globalHardLimits: {
          maxDailyLossPct: null, maxMarginUtilization: null, varLimitPct: null, cvarLimitPct: null,
        },
      }
      const out = resolveStrategyRiskParams('MyStrat', 'BTCUSDT', settings, {})
      expect(out.max_daily_loss_pct).toBeUndefined()
      expect(out.max_margin_utilization).toBeUndefined()
      expect(out.var_limit_pct).toBeUndefined()
      expect(out.cvar_limit_pct).toBeUndefined()
    })

    test('an explicitly-typed 0 is still honored (not treated as unset)', () => {
      const settings = { globalHardLimits: { maxDailyLossPct: 0 } }
      const out = resolveStrategyRiskParams('MyStrat', 'BTCUSDT', settings, {})
      expect(out.max_daily_loss_pct).toBe(0)
    })

    test('allocation passes through only when explicitly "inverse_vol"', () => {
      expect(
        resolveStrategyRiskParams('MyStrat', 'BTCUSDT', { globalHardLimits: { allocation: 'inverse_vol' } }, {}).allocation
      ).toBe('inverse_vol')
      expect(
        resolveStrategyRiskParams('MyStrat', 'BTCUSDT', { globalHardLimits: { allocation: 'equal' } }, {}).allocation
      ).toBeUndefined()
    })

    test('allocation: wizard override takes precedence over the Zone 2 global default', () => {
      const settings = { globalHardLimits: { allocation: 'equal' } }
      const out = resolveStrategyRiskParams('MyStrat', 'BTCUSDT', settings, { allocation: 'inverse_vol' })
      expect(out.allocation).toBe('inverse_vol')
    })

    test('allocation: wizard override of "equal" suppresses a global "inverse_vol" default', () => {
      const settings = { globalHardLimits: { allocation: 'inverse_vol' } }
      const out = resolveStrategyRiskParams('MyStrat', 'BTCUSDT', settings, { allocation: 'equal' })
      expect(out.allocation).toBeUndefined()
    })

    test('breachAction and autoFlattenOnHalt pass through', () => {
      const settings = { globalHardLimits: { breachAction: 'halted', autoFlattenOnHalt: true } }
      const out = resolveStrategyRiskParams('MyStrat', 'BTCUSDT', settings, {})
      expect(out.breach_action).toBe('halted')
      expect(out.auto_flatten_on_halt).toBe(true)
    })

    test('autoFlattenOnHalt=false is omitted, not sent as false', () => {
      const settings = { globalHardLimits: { autoFlattenOnHalt: false } }
      const out = resolveStrategyRiskParams('MyStrat', 'BTCUSDT', settings, {})
      expect(out.auto_flatten_on_halt).toBeUndefined()
    })
  })
})
