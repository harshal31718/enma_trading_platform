/**
 * One-off migration (Plan 2 Step 2.3 / SEC-3): re-encrypt every Settings
 * document's Binance credential fields from the old hardcoded fallback key
 * (`dev-secret-key-salt-placeholder`, unversioned `iv:tag:cipher` envelope)
 * to the new required ENCRYPTION_KEY (versioned `v1:iv:tag:cipher` envelope).
 *
 * Must run BEFORE encryption.js's fail-closed version is deployed — it
 * decrypts existing data with the OLD key/format and re-encrypts with the
 * NEW key/format via the ENCRYPTION_KEY env var passed to this process.
 *
 * Idempotent: a field already in the "v1:" envelope is left untouched.
 *
 * Usage (inside the server container, with the target ENCRYPTION_KEY set):
 *   docker exec -e ENCRYPTION_KEY=<new key> <container> node scripts/migrate-encryption-key.js
 */
const crypto = require('crypto')
const mongoose = require('mongoose')

const MONGO_URI = process.env.MONGO_URI || 'mongodb://mongodb:27017/enma_trading'
const MONGO_DB = process.env.MONGO_DB || 'enma_trading'

const OLD_KEY = crypto.scryptSync('dev-secret-key-salt-placeholder', 'dev-salt', 32)

function oldDecrypt(encryptedText) {
  if (!encryptedText) return ''
  const parts = encryptedText.split(':')
  if (parts.length !== 3) return null // already versioned, or not decryptable under the old format
  try {
    const [ivHex, tagHex, cipherHex] = parts
    const iv = Buffer.from(ivHex, 'hex')
    const tag = Buffer.from(tagHex, 'hex')
    const ciphertext = Buffer.from(cipherHex, 'hex')
    const decipher = crypto.createDecipheriv('aes-256-gcm', OLD_KEY, iv)
    decipher.setAuthTag(tag)
    return decipher.update(ciphertext, undefined, 'utf8') + decipher.final('utf8')
  } catch {
    return null
  }
}

function newEncrypt(text, newKey) {
  if (!text) return ''
  const iv = crypto.randomBytes(12)
  const cipher = crypto.createCipheriv('aes-256-gcm', newKey, iv)
  const encrypted = Buffer.concat([cipher.update(text, 'utf8'), cipher.final()])
  const tag = cipher.getAuthTag()
  return `v1:${iv.toString('hex')}:${tag.toString('hex')}:${encrypted.toString('hex')}`
}

const FIELDS = ['encryptedApiKey', 'encryptedApiSecret', 'encryptedMainnetApiKey', 'encryptedMainnetApiSecret']

async function main() {
  const envKey = process.env.ENCRYPTION_KEY
  if (!envKey || Buffer.from(envKey, 'utf8').length !== 32) {
    throw new Error('Set ENCRYPTION_KEY (32 bytes) to the NEW target key before running this migration.')
  }
  const newKey = Buffer.from(envKey, 'utf8')

  await mongoose.connect(MONGO_URI, { dbName: MONGO_DB })
  const db = mongoose.connection.db
  const settingsColl = db.collection('settings')

  const docs = await settingsColl.find({}).toArray()
  let migrated = 0
  let alreadyVersioned = 0
  let empty = 0
  let undecryptable = 0

  for (const doc of docs) {
    const update = {}
    for (const field of FIELDS) {
      const val = doc[field]
      if (!val) { empty++; continue }
      if (val.startsWith('v1:')) { alreadyVersioned++; continue }
      const plain = oldDecrypt(val)
      if (plain === null) {
        undecryptable++
        console.warn(`[migrate] ${doc._id} ${field}: could not decrypt under the old key/format — left as-is`)
        continue
      }
      update[field] = newEncrypt(plain, newKey)
    }
    if (Object.keys(update).length > 0) {
      await settingsColl.updateOne({ _id: doc._id }, { $set: update })
      migrated++
    }
  }

  console.log(`[migrate] documents scanned: ${docs.length}`)
  console.log(`[migrate] documents updated: ${migrated}`)
  console.log(`[migrate] fields already on v1: ${alreadyVersioned}`)
  console.log(`[migrate] empty fields skipped: ${empty}`)
  console.log(`[migrate] undecryptable fields (left untouched): ${undecryptable}`)

  await mongoose.connection.close()
}

main().catch((err) => {
  console.error('[migrate] FAILED:', err)
  process.exit(1)
})
