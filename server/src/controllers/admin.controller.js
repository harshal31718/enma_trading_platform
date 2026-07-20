const User = require('../models/User')
const ApiResponse = require('../utils/ApiResponse')
const ApiError = require('../utils/ApiError')
const { invalidateUserCache } = require('../middleware/auth.middleware')

// GET /api/v1/admin/users — all users with their Algo Trading access status.
// Global read (no userId scope): admin sees everyone. Normalises algoAccess to a
// flat status string so older docs without the field read as 'none'.
async function listUsers(req, res) {
  const users = await User.find({}, 'email name avatar role algoAccess createdAt lastLoginAt')
    .sort({ createdAt: -1 })
    .lean()

  const shaped = users.map((u) => ({
    id: u._id,
    email: u.email,
    name: u.name,
    avatar: u.avatar,
    role: u.role,
    algoAccess: u.algoAccess?.status || 'none',
    requestedAt: u.algoAccess?.requestedAt || null,
    createdAt: u.createdAt,
    lastLoginAt: u.lastLoginAt || null,
  }))

  res.json(ApiResponse.success(shaped))
}

// PATCH /api/v1/admin/users/:id/algo-access — grant or revoke a user's access.
// Body: { status: 'granted' | 'none' }. Admin rows are not editable (they bypass
// the gate via role anyway).
async function setUserAlgoAccess(req, res) {
  const { status } = req.body
  if (!['granted', 'none'].includes(status)) {
    throw new ApiError(400, 'VALIDATION_ERROR', "status must be 'granted' or 'none'")
  }

  const target = await User.findById(req.params.id).lean()
  if (!target) throw new ApiError(404, 'NOT_FOUND', 'User not found')
  if (target.role === 'admin') {
    throw new ApiError(403, 'FORBIDDEN', 'Admin access cannot be changed here')
  }

  await User.updateOne(
    { _id: target._id },
    { $set: { 'algoAccess.status': status, 'algoAccess.decidedAt': new Date(), 'algoAccess.decidedBy': req.user.id } }
  )
  // verifyJWT's short-TTL user cache (Plan 7 Step 7.3) must not delay this
  // grant/revoke — invalidate immediately so the very next request re-reads
  // from Mongo, preserving the existing "applies immediately" guarantee.
  invalidateUserCache(String(target._id))

  res.json(ApiResponse.success({ id: target._id, algoAccess: status }))
}

module.exports = { listUsers, setUserAlgoAccess }
