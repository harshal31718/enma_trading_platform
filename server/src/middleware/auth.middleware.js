const jwt = require('jsonwebtoken')
const User = require('../models/User')
const ApiError = require('../utils/ApiError')

async function verifyJWT(req, res, next) {
  try {
    const token = req.cookies?.enma_jwt
    if (!token) return next(new ApiError(401, 'UNAUTHORIZED', 'No token provided'))

    const decoded = jwt.verify(token, process.env.JWT_SECRET)
    const user = await User.findById(decoded.userId).lean()
    if (!user || !user.isActive) return next(new ApiError(401, 'UNAUTHORIZED', 'User not found or inactive'))

    req.user = user
    req.user.id = user._id.toString()
    next()
  } catch {
    next(new ApiError(401, 'UNAUTHORIZED', 'Invalid or expired token'))
  }
}

function requireAdmin(req, res, next) {
  if (req.user?.role !== 'admin') return next(new ApiError(403, 'FORBIDDEN', 'Admin access required'))
  next()
}

module.exports = { verifyJWT, requireAdmin }
