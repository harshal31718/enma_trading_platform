const passport = require('passport')
const { Strategy: GoogleStrategy } = require('passport-google-oauth20')
const User = require('../models/User')
const PlatformConfig = require('../models/PlatformConfig')

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

        const config = await PlatformConfig.findById('platform')
        const isAllowed = config?.allowedEmails?.some(e => e.email === email)
        if (!isAllowed) return done(null, false, { message: 'not_invited' })

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
