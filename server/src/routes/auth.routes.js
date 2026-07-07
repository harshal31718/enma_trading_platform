const express = require('express')
const passport = require('passport')
const { googleCallback, logout, getMe } = require('../controllers/auth.controller')
const { verifyJWT } = require('../middleware/auth.middleware')

const router = express.Router()

router.get('/google', passport.authenticate('google', { scope: ['profile', 'email'], session: false }))

const clientUrl = process.env.CLIENT_URL || 'http://localhost:5173'

router.get(
  '/google/callback',
  passport.authenticate('google', { session: false, failureRedirect: `${clientUrl}/login?error=auth_failed` }),
  googleCallback
)

router.post('/logout', logout)
router.get('/me', verifyJWT, getMe)

module.exports = router
