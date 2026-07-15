const crypto = require('crypto')

// SEC-3 (Plan 2 Step 2.3): fail CLOSED, never fail open. A missing or malformed
// ENCRYPTION_KEY used to fall back to a hardcoded, publicly-known dev key —
// meaning every Binance API secret in the database was recoverable by anyone
// who read this file. Boot must fail loudly instead.
function loadRequiredKey(envVar) {
  const envKey = process.env[envVar]
  if (!envKey) {
    throw new Error(
      `${envVar} is not set. Refusing to start with an implicit/default ` +
      `encryption key — set a 32-byte ${envVar} in the environment.`
    )
  }
  const buf = Buffer.from(envKey, 'utf8')
  if (buf.length !== 32) {
    throw new Error(
      `${envVar} must be exactly 32 bytes (got ${buf.length}). ` +
      'Refusing to start with an invalid encryption key.'
    )
  }
  return buf
}

// Plan 4 Step 4.4: rotation support. ENCRYPTION_KEY is always "the current
// key" and always writes as the latest version. ENCRYPTION_KEY_PREV is
// optional — set it during a rotation window so records still tagged with
// the previous version keep decrypting while everything gets re-encrypted
// under the new key (e.g. by re-running server/scripts/migrate-encryption-key.js
// pointed at the new key). Drop ENCRYPTION_KEY_PREV once no v1 records remain.
// Steady state (no rotation in progress): only ENCRYPTION_KEY is set, every
// record is "v1" — byte-identical to pre-4.4 behavior.
const CURRENT_KEY = loadRequiredKey('ENCRYPTION_KEY')
const PREV_KEY = process.env.ENCRYPTION_KEY_PREV
  ? loadRequiredKey('ENCRYPTION_KEY_PREV')
  : null

const CURRENT_VERSION = PREV_KEY ? 'v2' : 'v1'
const KEYS_BY_VERSION = PREV_KEY
  ? { v1: PREV_KEY, v2: CURRENT_KEY }
  : { v1: CURRENT_KEY }

function encrypt(text) {
  if (!text) return ''
  const iv = crypto.randomBytes(12)
  const cipher = crypto.createCipheriv('aes-256-gcm', CURRENT_KEY, iv)
  const encrypted = Buffer.concat([cipher.update(text, 'utf8'), cipher.final()])
  const tag = cipher.getAuthTag()
  return `${CURRENT_VERSION}:${iv.toString('hex')}:${tag.toString('hex')}:${encrypted.toString('hex')}`
}

// Throws on any malformed/tampered/wrong-key input — callers must handle failure
// explicitly instead of silently receiving back the ciphertext or garbage bytes.
function decrypt(encryptedText) {
  if (!encryptedText) return ''
  const parts = encryptedText.split(':')
  const version = parts[0]
  const key = KEYS_BY_VERSION[version]
  if (parts.length !== 4 || !key) {
    throw new Error(
      `decrypt: unrecognized ciphertext envelope (expected one of ${Object.keys(KEYS_BY_VERSION).join('/')}:iv:tag:ciphertext)`
    )
  }
  const [, ivHex, tagHex, cipherHex] = parts
  const iv = Buffer.from(ivHex, 'hex')
  const tag = Buffer.from(tagHex, 'hex')
  const ciphertext = Buffer.from(cipherHex, 'hex')
  const decipher = crypto.createDecipheriv('aes-256-gcm', key, iv)
  decipher.setAuthTag(tag)
  return decipher.update(ciphertext, undefined, 'utf8') + decipher.final('utf8')
}

module.exports = { encrypt, decrypt }
