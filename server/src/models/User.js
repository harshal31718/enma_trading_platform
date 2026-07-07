const mongoose = require('mongoose')

const userSchema = new mongoose.Schema(
  {
    googleId: { type: String, required: true, unique: true, index: true },
    email: { type: String, required: true, unique: true, lowercase: true, index: true },
    name: { type: String, required: true },
    avatar: { type: String, default: '' },
    role: { type: String, enum: ['user', 'admin'], default: 'user' },
    isActive: { type: Boolean, default: true },
    lastLoginAt: { type: Date },
    // Per-user Algo Trading access. Login is open to everyone; only the algo
    // start actions are gated (see requireAlgoAccess). Absence of this field is
    // treated as 'none'. Admins bypass this via role.
    algoAccess: {
      status: { type: String, enum: ['none', 'requested', 'granted'], default: 'none', index: true },
      requestedAt: { type: Date },
      decidedAt: { type: Date },
      decidedBy: { type: String }, // admin userId who granted/revoked
    },
  },
  { timestamps: true }
)

module.exports = mongoose.model('User', userSchema)
