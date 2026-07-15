const crypto = require('crypto')

const TEST_KEY = 'a'.repeat(32) // exactly 32 bytes as utf8

describe('encryption.js (SEC-3 fail-closed)', () => {
  const ORIGINAL_ENV = process.env.ENCRYPTION_KEY

  afterEach(() => {
    if (ORIGINAL_ENV === undefined) delete process.env.ENCRYPTION_KEY
    else process.env.ENCRYPTION_KEY = ORIGINAL_ENV
    jest.resetModules()
  })

  function loadWithKey(key) {
    jest.resetModules()
    if (key === undefined) delete process.env.ENCRYPTION_KEY
    else process.env.ENCRYPTION_KEY = key
    return require('../encryption')
  }

  test('boot throws when ENCRYPTION_KEY is missing', () => {
    expect(() => loadWithKey(undefined)).toThrow(/ENCRYPTION_KEY is not set/)
  })

  test('boot throws when ENCRYPTION_KEY is not exactly 32 bytes', () => {
    expect(() => loadWithKey('too-short')).toThrow(/32 bytes/)
    expect(() => loadWithKey('x'.repeat(64))).toThrow(/32 bytes/)
  })

  test('valid round-trip: encrypt then decrypt returns the original text', () => {
    const { encrypt, decrypt } = loadWithKey(TEST_KEY)
    const plaintext = 'super-secret-binance-api-key'
    const ciphertext = encrypt(plaintext)
    expect(ciphertext).toMatch(/^v1:/)
    expect(decrypt(ciphertext)).toBe(plaintext)
  })

  test('empty input round-trips to empty string without throwing', () => {
    const { encrypt, decrypt } = loadWithKey(TEST_KEY)
    expect(encrypt('')).toBe('')
    expect(decrypt('')).toBe('')
  })

  test('decrypt throws on wrong key instead of returning garbage', () => {
    const { encrypt } = loadWithKey(TEST_KEY)
    const ciphertext = encrypt('secret')
    const { decrypt: decryptWithOtherKey } = loadWithKey('b'.repeat(32))
    expect(() => decryptWithOtherKey(ciphertext)).toThrow()
  })

  test('decrypt throws on truncated ciphertext instead of pass-through', () => {
    const { encrypt, decrypt } = loadWithKey(TEST_KEY)
    const ciphertext = encrypt('secret')
    const truncated = ciphertext.slice(0, -8)
    expect(() => decrypt(truncated)).toThrow()
  })

  test('decrypt throws on a tampered auth tag instead of pass-through', () => {
    const { encrypt, decrypt } = loadWithKey(TEST_KEY)
    const ciphertext = encrypt('secret')
    const [version, iv, tag, body] = ciphertext.split(':')
    const tamperedTag = Buffer.from(tag, 'hex')
    tamperedTag[0] ^= 0xff
    const tampered = [version, iv, tamperedTag.toString('hex'), body].join(':')
    expect(() => decrypt(tampered)).toThrow()
  })

  test('decrypt throws on an unrecognized/legacy unversioned envelope', () => {
    const { decrypt } = loadWithKey(TEST_KEY)
    // Old pre-SEC-3 format: "iv:tag:cipher" with no version prefix.
    const legacy = `${crypto.randomBytes(12).toString('hex')}:${crypto.randomBytes(16).toString('hex')}:deadbeef`
    expect(() => decrypt(legacy)).toThrow(/envelope/)
  })

  test('decrypt returns empty string for empty/falsy input without touching the crypto path', () => {
    const { decrypt } = loadWithKey(TEST_KEY)
    expect(decrypt('')).toBe('')
    expect(decrypt(undefined)).toBe('')
    expect(decrypt(null)).toBe('')
  })
})
