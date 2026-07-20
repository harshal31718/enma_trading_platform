const jwt = require('jsonwebtoken')
const User = require('../models/User')
const ApiError = require('../utils/ApiError')

// Plan 7 Step 7.3 (SRV-4): short-TTL cache for the per-request `User.findById`
// lookup — every protected route runs this on every request (e.g. Trade's
// 4s position poll), so an unconditional DB hit per request adds up. Kept
// deliberately short so it's a performance smoothing, not a staleness risk:
// `invalidateUserCache()` is called the moment `admin.controller.js` changes
// a user's algoAccess, so the "grants/revoke apply on next request"
// guarantee documented in server/CLAUDE.md holds exactly, not just
// approximately — the TTL only covers the common case where nothing changed
// between two requests moments apart.
const USER_CACHE_TTL_MS = 5_000
const _userCache = new Map() // userId -> { user, cachedAt }

function _getCachedUser(userId) {
  const entry = _userCache.get(userId)
  if (!entry) return null
  if (Date.now() - entry.cachedAt > USER_CACHE_TTL_MS) {
    _userCache.delete(userId)
    return null
  }
  // Shallow copy — verifyJWT mutates `.id` onto whatever it assigns to
  // req.user, and req.user must never be a shared reference across
  // concurrent requests hitting the same cache entry.
  return { ...entry.user }
}

function _setCachedUser(userId, user) {
  _userCache.set(userId, { user, cachedAt: Date.now() })
}

function invalidateUserCache(userId) {
  _userCache.delete(String(userId))
}

// Test-only: the cache is module-scoped state, so tests that reuse the same
// userId across cases (mocking a different User.findById result each time)
// need a way to reset it between cases rather than sharing a stale entry.
function _clearUserCacheForTests() {
  _userCache.clear()
}

async function verifyJWT(req, res, next) {
  const token = req.cookies?.enma_jwt
  if (!token) return next(new ApiError(401, 'UNAUTHORIZED', 'No token provided'))

  let decoded
  try {
    decoded = jwt.verify(token, process.env.JWT_SECRET)
  } catch {
    return next(new ApiError(401, 'UNAUTHORIZED', 'Invalid or expired token'))
  }

  let user = _getCachedUser(decoded.userId)
  if (!user) {
    try {
      user = await User.findById(decoded.userId).lean()
    } catch (dbErr) {
      // Infra failure (Mongo down/unreachable) is not the same failure mode
      // as a bad token — a 401 here would tell the client to re-auth when
      // the actual problem is the DB, sending users through a useless
      // login retry loop. 503 signals "retry shortly", not "your session
      // is invalid."
      console.error('[Auth] User lookup failed (infra):', dbErr.message)
      return next(new ApiError(503, 'SERVICE_UNAVAILABLE', 'Unable to verify session — please retry shortly'))
    }
    if (user) _setCachedUser(decoded.userId, user)
  }

  if (!user || !user.isActive) return next(new ApiError(401, 'UNAUTHORIZED', 'User not found or inactive'))

  req.user = user
  req.user.id = user._id.toString()
  next()
}

function requireAdmin(req, res, next) {
  if (req.user?.role !== 'admin') return next(new ApiError(403, 'FORBIDDEN', 'Admin access required'))
  next()
}

// Gates the Algo Trading start actions. Admins always pass; other users need an
// explicit granted status. Absence of algoAccess is treated as no access.
function requireAlgoAccess(req, res, next) {
  if (req.user?.role === 'admin' || req.user?.algoAccess?.status === 'granted') return next()
  return next(new ApiError(403, 'ALGO_ACCESS_REQUIRED', 'Algo trading access required'))
}

module.exports = { verifyJWT, requireAdmin, requireAlgoAccess, invalidateUserCache, _clearUserCacheForTests }
