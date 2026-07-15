const { allocateChaosSymbols } = require('../chaosAllocator')

const CURATED = ['AAA', 'BBB', 'CCC', 'DDD', 'EEE', 'FFF', 'GGG', 'HHH']
const TIER_MAP = [
  { symbol: 'AAA', tier: 'high' },
  { symbol: 'BBB', tier: 'high' },
  { symbol: 'CCC', tier: 'mid' },
  { symbol: 'DDD', tier: 'mid' },
  { symbol: 'EEE', tier: 'low' },
  { symbol: 'FFF', tier: 'low' },
  { symbol: 'GGG', tier: 'low' },
  { symbol: 'HHH', tier: 'low' },
]

describe('chaosAllocator.allocateChaosSymbols', () => {
  test('manual picks are reserved and never reassigned to another strategy', () => {
    const { assignments } = allocateChaosSymbols({
      activeStrategies: ['S1', 'S2'],
      manualPicks: { S1: ['AAA'] },
      curatedSymbols: CURATED,
      maxManualSymbols: 5,
      maxSymbolsPerBot: 4,
      chaosMaxTotalSymbols: 8,
      tierMap: TIER_MAP,
    })
    expect(assignments.S1).toContain('AAA')
    expect(assignments.S2).not.toContain('AAA')
  })

  test('duplicate manual picks across strategies throw a validation error', () => {
    expect(() =>
      allocateChaosSymbols({
        activeStrategies: ['S1', 'S2'],
        manualPicks: { S1: ['AAA'], S2: ['AAA'] },
        curatedSymbols: CURATED,
        maxManualSymbols: 5,
        maxSymbolsPerBot: 4,
        chaosMaxTotalSymbols: 8,
        tierMap: TIER_MAP,
      })
    ).toThrow(expect.objectContaining({ code: 'CHAOS_SYMBOL_DUPLICATE' }))
  })

  test('manual pick of a locked symbol throws a 409 lock error', () => {
    expect(() =>
      allocateChaosSymbols({
        activeStrategies: ['S1'],
        manualPicks: { S1: ['AAA'] },
        lockedSymbols: ['AAA'],
        curatedSymbols: CURATED,
        maxManualSymbols: 5,
        maxSymbolsPerBot: 4,
        chaosMaxTotalSymbols: 8,
        tierMap: TIER_MAP,
      })
    ).toThrow(expect.objectContaining({ code: 'CHAOS_SYMBOL_LOCKED', status: 409 }))
  })

  test('manual picks exceeding the per-bot cap are a hard error, never silently dropped', () => {
    expect(() =>
      allocateChaosSymbols({
        activeStrategies: ['S1'],
        manualPicks: { S1: ['AAA', 'BBB', 'CCC'] },
        curatedSymbols: CURATED,
        maxManualSymbols: 5,
        maxSymbolsPerBot: 2,
        chaosMaxTotalSymbols: 8,
        tierMap: TIER_MAP,
      })
    ).toThrow(expect.objectContaining({ code: 'CHAOS_SYMBOL_PER_BOT_CAP_EXCEEDED' }))
  })

  test('no strategy exceeds maxSymbolsPerBot after round-robin distribution', () => {
    const { assignments } = allocateChaosSymbols({
      activeStrategies: ['S1', 'S2', 'S3'],
      manualPicks: {},
      curatedSymbols: CURATED,
      maxManualSymbols: 5,
      maxSymbolsPerBot: 2,
      chaosMaxTotalSymbols: 8,
      tierMap: TIER_MAP,
    })
    for (const strat of ['S1', 'S2', 'S3']) {
      expect(assignments[strat].length).toBeLessThanOrEqual(2)
    }
  })

  test('run-wide total never exceeds chaosMaxTotalSymbols; excess symbols are dropped, not lost silently', () => {
    const { assignments, dropped } = allocateChaosSymbols({
      activeStrategies: ['S1', 'S2'],
      manualPicks: {},
      curatedSymbols: CURATED,
      maxManualSymbols: 5,
      maxSymbolsPerBot: 8,
      chaosMaxTotalSymbols: 3,
      tierMap: TIER_MAP,
    })
    const totalAssigned = Object.values(assignments).reduce((sum, arr) => sum + arr.length, 0)
    expect(totalAssigned).toBeLessThanOrEqual(3)
    expect(totalAssigned + dropped.length).toBe(CURATED.length)
  })

  test('no symbol is ever assigned to more than one strategy', () => {
    const { assignments } = allocateChaosSymbols({
      activeStrategies: ['S1', 'S2', 'S3'],
      manualPicks: { S1: ['AAA'] },
      curatedSymbols: CURATED,
      maxManualSymbols: 5,
      maxSymbolsPerBot: 4,
      chaosMaxTotalSymbols: 8,
      tierMap: TIER_MAP,
    })
    const seen = new Set()
    for (const list of Object.values(assignments)) {
      for (const sym of list) {
        expect(seen.has(sym)).toBe(false)
        seen.add(sym)
      }
    }
  })
})
