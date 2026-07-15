const crypto = require('crypto')

// SEC-3 (Plan 2 Step 2.3): fail CLOSED, never fail open. A missing or malformed
// ENCRYPTION_KEY used to fall back to a hardcoded, publicly-known dev key —
// meaning every Binance API secret in the database was recoverable by anyone
// who read this file. Boot must fail loudly instead.
function loadKey() {
  const envKey = process.env.ENCRYPTION_KEY
  if (!envKey) {
    throw new Error(
      'ENCRYPTION_KEY is not set. Refusing to start with an implicit/default ' +
      'encryption key — set a 32-byte ENCRYPTION_KEY in the environment.'
    )
  }
  const buf = Buffer.from(envKey, 'utf8')
  if (buf.length !== 32) {
    throw new Error(
      `ENCRYPTION_KEY must be exactly 32 bytes (got ${buf.length}). ` +
      'Refusing to start with an invalid encryption key.'
    )
  }
  return buf
}

const key = loadKey()

// Versioned envelope (SEC-3): every ciphertext is tagged with the format version
// it was written under, so a future ENCRYPTION_KEY rotation can add a v2 codec
// without corrupting or misreading records still stored under v1.
const ENVELOPE_VERSION = 'v1'

function encrypt(text) {
  if (!text) return ''
  const iv = crypto.randomBytes(12)
  const cipher = crypto.createCipheriv('aes-256-gcm', key, iv)
  const encrypted = Buffer.concat([cipher.update(text, 'utf8'), cipher.final()])
  const tag = cipher.getAuthTag()
  return `${ENVELOPE_VERSION}:${iv.toString('hex')}:${tag.toString('hex')}:${encrypted.toString('hex')}`
}

// Throws on any malformed/tampered/wrong-key input — callers must handle failure
// explicitly instead of silently receiving back the ciphertext or garbage bytes.
function decrypt(encryptedText) {
  if (!encryptedText) return ''
  const parts = encryptedText.split(':')
  if (parts.length !== 4 || parts[0] !== ENVELOPE_VERSION) {
    throw new Error('decrypt: unrecognized ciphertext envelope (expected "v1:iv:tag:ciphertext")')
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
