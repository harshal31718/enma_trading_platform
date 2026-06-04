const crypto = require('crypto')

let key
try {
  const envKey = process.env.ENCRYPTION_KEY
  if (envKey && Buffer.from(envKey, 'utf8').length === 32) {
    key = Buffer.from(envKey, 'utf8')
  } else {
    key = crypto.scryptSync('dev-secret-key-salt-placeholder', 'dev-salt', 32)
  }
} catch {
  key = crypto.scryptSync('dev-secret-key-salt-placeholder', 'dev-salt', 32)
}

function encrypt(text) {
  if (!text) return ''
  const iv = crypto.randomBytes(12)
  const cipher = crypto.createCipheriv('aes-256-gcm', key, iv)
  const encrypted = Buffer.concat([cipher.update(text, 'utf8'), cipher.final()])
  const tag = cipher.getAuthTag()
  return `${iv.toString('hex')}:${tag.toString('hex')}:${encrypted.toString('hex')}`
}

function decrypt(encryptedText) {
  if (!encryptedText) return ''
  const parts = encryptedText.split(':')
  if (parts.length !== 3) return encryptedText
  try {
    const [ivHex, tagHex, cipherHex] = parts
    const iv = Buffer.from(ivHex, 'hex')
    const tag = Buffer.from(tagHex, 'hex')
    const ciphertext = Buffer.from(cipherHex, 'hex')
    const decipher = crypto.createDecipheriv('aes-256-gcm', key, iv)
    decipher.setAuthTag(tag)
    return decipher.update(ciphertext, undefined, 'utf8') + decipher.final('utf8')
  } catch {
    return encryptedText
  }
}

module.exports = { encrypt, decrypt }
