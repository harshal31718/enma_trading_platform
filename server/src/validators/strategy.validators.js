const { z } = require('zod')

// POST /api/v1/strategies — createStrategy previously destructured req.body
// with zero validation before forwarding it to the engine (SEC-10 gap).
const createStrategySchema = z.object({
  name: z.string().trim().min(1).max(100),
  description: z.string().max(2000).optional(),
  sourceName: z.string().trim().min(1).max(100).optional(),
  template: z.string().trim().min(1).max(100).optional(),
})

module.exports = { createStrategySchema }
