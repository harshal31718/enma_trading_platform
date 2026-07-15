// Plan 3 Step 3.1 (SEC-1): /internal/* routes can place/close real Binance
// orders on the engine's behalf and were previously wide open — anyone who
// could reach the server's port could trigger a trade. Requires a shared
// secret distinct from ENGINE_API_KEY (that key authenticates the other
// direction, Node -> engine) via constant-time comparison (Step 3.5 / SEC-8).
const crypto = require('crypto')
const ApiError = require('../utils/ApiError')

function timingSafeEqualStrings(a, b) {
  const bufA = Buffer.from(String(a))
  const bufB = Buffer.from(String(b))
  if (bufA.length !== bufB.length) {
    // Still run a comparison of equal-length buffers so this branch doesn't
    // leak length information via an early return with no crypto work done.
    crypto.timingSafeEqual(bufA, bufA)
    return false
  }
  return crypto.timingSafeEqual(bufA, bufB)
}

function requireInternalKey(req, res, next) {
  const expected = process.env.INTERNAL_API_KEY
  if (!expected) {
    return next(new ApiError(500, 'INTERNAL_KEY_NOT_CONFIGURED', 'INTERNAL_API_KEY is not set on the server'))
  }
  const provided = req.headers['x-internal-key']
  if (!provided || !timingSafeEqualStrings(provided, expected)) {
    return next(new ApiError(401, 'UNAUTHORIZED', 'Invalid or missing internal key'))
  }
  next()
}

module.exports = requireInternalKey
