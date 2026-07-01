const PlatformConfig = require('../models/PlatformConfig')
const ApiResponse = require('../utils/ApiResponse')
const ApiError = require('../utils/ApiError')

async function getAllowedEmails(req, res) {
  const config = await PlatformConfig.findById('platform')
  res.json(ApiResponse.success(config?.allowedEmails || []))
}

async function addAllowedEmail(req, res) {
  const email = req.body.email?.toLowerCase()?.trim()
  if (!email) throw new ApiError(400, 'BAD_REQUEST', 'Email is required')

  const config = await PlatformConfig.findById('platform')
  const exists = config?.allowedEmails?.some(e => e.email === email)
  if (exists) throw new ApiError(409, 'CONFLICT', 'Email already in the whitelist')

  await PlatformConfig.findByIdAndUpdate('platform', {
    $push: { allowedEmails: { email, addedBy: req.user.email, addedAt: new Date() } },
  })

  res.json(ApiResponse.success({ email }))
}

async function removeAllowedEmail(req, res) {
  const email = req.params.email.toLowerCase()

  if (email === process.env.ADMIN_EMAIL?.toLowerCase()) {
    throw new ApiError(403, 'FORBIDDEN', 'Cannot remove the admin email from the whitelist')
  }

  await PlatformConfig.findByIdAndUpdate('platform', {
    $pull: { allowedEmails: { email } },
  })

  res.json(ApiResponse.success(null))
}

module.exports = { getAllowedEmails, addAllowedEmail, removeAllowedEmail }
