const { createStrategySchema } = require('../strategy.validators')

describe('createStrategySchema', () => {
  test('accepts a minimal valid body (name only)', () => {
    const result = createStrategySchema.safeParse({ name: 'MyStrategy' })
    expect(result.success).toBe(true)
  })

  test('accepts a full body with description/sourceName/template', () => {
    const result = createStrategySchema.safeParse({
      name: 'MyStrategy', description: 'a test strategy', sourceName: 'MicroScalper', template: 'blank',
    })
    expect(result.success).toBe(true)
  })

  test('rejects a missing name', () => {
    const result = createStrategySchema.safeParse({ description: 'no name' })
    expect(result.success).toBe(false)
  })

  test('rejects an empty name', () => {
    const result = createStrategySchema.safeParse({ name: '' })
    expect(result.success).toBe(false)
  })

  test('rejects a non-string name', () => {
    const result = createStrategySchema.safeParse({ name: 123 })
    expect(result.success).toBe(false)
  })
})
