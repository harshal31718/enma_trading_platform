const ApiError = require('../utils/ApiError')

// Generic zod schema-validation middleware (SEC-10 / Plan 8 Step 8.2).
// Validates req[source] (default: 'body') against the given zod schema and
// replaces it with the parsed (type-coerced/defaulted) result on success, so
// downstream controllers can trust the shape instead of re-checking it.
// On failure, throws a single ApiError(400, 'VALIDATION_ERROR', ...) that
// flows through the existing errorHandler.js — same response shape every
// other validation failure in this codebase already produces.
function validate(schema, source = 'body') {
  return (req, res, next) => {
    const result = schema.safeParse(req[source])
    if (!result.success) {
      const message = result.error.issues
        .map((issue) => `${issue.path.join('.') || source}: ${issue.message}`)
        .join('; ')
      return next(new ApiError(400, 'VALIDATION_ERROR', message))
    }
    req[source] = result.data
    next()
  }
}

module.exports = validate
