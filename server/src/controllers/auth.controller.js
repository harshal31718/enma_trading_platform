const jwt = require('jsonwebtoken')
const ApiResponse = require('../utils/ApiResponse')

const COOKIE_OPTIONS = {
  httpOnly: true,
  sameSite: 'lax',
  secure: process.env.NODE_ENV === 'production',
  maxAge: 7 * 24 * 60 * 60 * 1000,
}

function googleCallback(req, res) {
  const clientUrl = process.env.CLIENT_URL || 'http://localhost:5173'
  if (!req.user) {
    return res.redirect(`${clientUrl}/login?error=auth_failed`)
  }

  const token = jwt.sign(
    { userId: req.user._id, role: req.user.role },
    process.env.JWT_SECRET,
    { expiresIn: '7d' }
  )

  res.cookie('enma_jwt', token, COOKIE_OPTIONS)
  res.redirect(`${clientUrl}/`)
}

function logout(req, res) {
  res.clearCookie('enma_jwt', { httpOnly: true, sameSite: 'lax', secure: process.env.NODE_ENV === 'production' })
  res.json(ApiResponse.success(null))
}

function getMe(req, res) {
  const { _id, email, name, avatar, role } = req.user
  const algoAccess = req.user.algoAccess?.status || 'none'
  res.json(ApiResponse.success({ id: _id, email, name, avatar, role, algoAccess }))
}

module.exports = { googleCallback, logout, getMe }
