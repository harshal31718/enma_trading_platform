const {
  validateCapitalValue,
  sumReservedCapital,
  checkCapitalAgainstBalance,
} = require('../capitalGate')

// Plan 22 Step 22.1 (B-11/B-12): capital integrity gate. Decided 2026-07-17
// (DECISIONS.md #23, Part F Q5) — hard reject bad values always, warn+confirm
// on over-commit vs the real wallet balance (testnet).

describe('validateCapitalValue', () => {
  test('accepts a positive numeric string', () => {
    expect(validateCapitalValue('1000')).toEqual({ valid: true, value: 1000, error: null })
  })

  test('accepts a positive number', () => {
    expect(validateCapitalValue(500.5)).toEqual({ valid: true, value: 500.5, error: null })
  })

  test('rejects a non-numeric string', () => {
    const result = validateCapitalValue('not-a-number')
    expect(result.valid).toBe(false)
    expect(result.value).toBeNull()
    expect(result.error).toMatch(/finite number/)
  })

  test('rejects zero', () => {
    const result = validateCapitalValue(0)
    expect(result.valid).toBe(false)
    expect(result.error).toMatch(/greater than zero/)
  })

  test('rejects a negative value', () => {
    const result = validateCapitalValue(-500)
    expect(result.valid).toBe(false)
    expect(result.error).toMatch(/greater than zero/)
  })

  test('rejects Infinity', () => {
    const result = validateCapitalValue(Infinity)
    expect(result.valid).toBe(false)
  })

  test('rejects null/undefined', () => {
    expect(validateCapitalValue(null).valid).toBe(false)
    expect(validateCapitalValue(undefined).valid).toBe(false)
  })

  test('rejects an empty string (the old !capital presence check would already catch this, belt and braces)', () => {
    expect(validateCapitalValue('').valid).toBe(false)
  })
})

describe('sumReservedCapital', () => {
  test('sums numeric capital across sessions', () => {
    const sessions = [{ capital: '1000' }, { capital: '500' }, { capital: 250 }]
    expect(sumReservedCapital(sessions)).toBe(1750)
  })

  test('empty/undefined list sums to zero', () => {
    expect(sumReservedCapital([])).toBe(0)
    expect(sumReservedCapital(undefined)).toBe(0)
  })

  test('a malformed stored capital value degrades to 0 rather than NaN-poisoning the sum', () => {
    const sessions = [{ capital: '1000' }, { capital: 'garbage' }, { capital: 500 }]
    expect(sumReservedCapital(sessions)).toBe(1500)
  })
})

describe('checkCapitalAgainstBalance', () => {
  test('flags over-commit when requested + reserved exceeds available balance', () => {
    const result = checkCapitalAgainstBalance({
      requestedCapital: 1000,
      reservedCapital: 5000,
      availableBalance: 5500,
    })
    expect(result).toEqual({
      checked: true,
      overCommit: true,
      totalCommitted: 6000,
      availableBalance: 5500,
    })
  })

  test('does not flag when requested + reserved is within balance', () => {
    const result = checkCapitalAgainstBalance({
      requestedCapital: 1000,
      reservedCapital: 2000,
      availableBalance: 5000,
    })
    expect(result.overCommit).toBe(false)
    expect(result.checked).toBe(true)
  })

  test('exactly at the balance boundary is NOT an over-commit (>, not >=)', () => {
    const result = checkCapitalAgainstBalance({
      requestedCapital: 3000,
      reservedCapital: 2000,
      availableBalance: 5000,
    })
    expect(result.overCommit).toBe(false)
  })

  test('null availableBalance (fetch failed) short-circuits to unchecked, never guesses overCommit=true', () => {
    const result = checkCapitalAgainstBalance({
      requestedCapital: 1000,
      reservedCapital: 5000,
      availableBalance: null,
    })
    expect(result.checked).toBe(false)
    expect(result.overCommit).toBe(false)
    expect(result.totalCommitted).toBe(6000) // still computed, just not compared
  })

  test('Chaos-style multiplied requestedCapital (capital x strategyCount) is over-commit-checkable the same way', () => {
    const perStrategyCapital = 500
    const strategyCount = 15
    const result = checkCapitalAgainstBalance({
      requestedCapital: perStrategyCapital * strategyCount, // 7500
      reservedCapital: 0,
      availableBalance: 5000,
    })
    expect(result.overCommit).toBe(true)
    expect(result.totalCommitted).toBe(7500)
  })
})
