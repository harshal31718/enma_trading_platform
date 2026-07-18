const passport = require('passport')
const { Strategy: GoogleStrategy } = require('passport-google-oauth20')
const User = require('../models/User')

// Extracted for direct unit testing without exercising the whole OAuth
// verify callback (env reads inline so tests can pass explicit values).
function isRejectedByAdminOnlyRestriction(email, { restrictToAdmin, adminEmail }) {
  return restrictToAdmin === 'true' && email !== adminEmail?.toLowerCase()
}

passport.use(
  new GoogleStrategy(
    {
      clientID: process.env.GOOGLE_CLIENT_ID,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET,
      callbackURL: process.env.GOOGLE_CALLBACK_URL || `${process.env.SERVER_URL || 'http://localhost:5000'}/api/v1/auth/google/callback`,
    },
    async (accessToken, refreshToken, profile, done) => {
      try {
        const email = profile.emails[0].value.toLowerCase()
        const name = profile.displayName
        const avatar = profile.photos?.[0]?.value || ''
        const googleId = profile.id

        // Login is open to anyone with a valid Google account (root CLAUDE.md
        // Rule 1) — this is the production/default contract, unchanged here.
        // AUTH_RESTRICT_TO_ADMIN is a local-dev-only opt-in (unset/false in
        // production and in this repo's committed .env.example): when set,
        // only ADMIN_EMAIL may sign in — every other Google account is
        // rejected at the OAuth callback, before any User doc is touched.
        if (isRejectedByAdminOnlyRestriction(email, {
          restrictToAdmin: process.env.AUTH_RESTRICT_TO_ADMIN,
          adminEmail: process.env.ADMIN_EMAIL,
        })) {
          return done(null, false, { message: 'This environment is restricted to the admin account' })
        }

        let user = await User.findOneAndUpdate(
          { googleId },
          { $set: { email, name, avatar, lastLoginAt: new Date() } },
          { upsert: true, new: true }
        )

        if (email === process.env.ADMIN_EMAIL?.toLowerCase() && user.role !== 'admin') {
          user.role = 'admin'
          await user.save()
        }

        return done(null, user)
      } catch (err) {
        return done(err)
      }
    }
  )
)

module.exports = passport
module.exports.isRejectedByAdminOnlyRestriction = isRejectedByAdminOnlyRestriction
