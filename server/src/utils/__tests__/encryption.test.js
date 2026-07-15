const crypto = require('crypto')

const TEST_KEY = 'a'.repeat(32) // exactly 32 bytes as utf8
const TEST_KEY_V2 = 'c'.repeat(32)

describe('encryption.js (SEC-3 fail-closed)', () => {
  const ORIGINAL_ENV = process.env.ENCRYPTION_KEY
  const ORIGINAL_PREV_ENV = process.env.ENCRYPTION_KEY_PREV

  afterEach(() => {
    if (ORIGINAL_ENV === undefined) delete process.env.ENCRYPTION_KEY
    else process.env.ENCRYPTION_KEY = ORIGINAL_ENV
    if (ORIGINAL_PREV_ENV === undefined) delete process.env.ENCRYPTION_KEY_PREV
    else process.env.ENCRYPTION_KEY_PREV = ORIGINAL_PREV_ENV
    jest.resetModules()
  })

  function loadWithKey(key, prevKey) {
    jest.resetModules()
    if (key === undefined) delete process.env.ENCRYPTION_KEY
    else process.env.ENCRYPTION_KEY = key
    if (prevKey === undefined) delete process.env.ENCRYPTION_KEY_PREV
    else process.env.ENCRYPTION_KEY_PREV = prevKey
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

  // Plan 4 Step 4.4: rotation exercised with mixed-version records.
  describe('key rotation (v1 -> v2)', () => {
    test('steady state (no ENCRYPTION_KEY_PREV): everything is v1', () => {
      const { encrypt } = loadWithKey(TEST_KEY)
      expect(encrypt('secret')).toMatch(/^v1:/)
    })

    test('a v1 record written before rotation still decrypts once ENCRYPTION_KEY_PREV is set', () => {
      // Phase 1: pre-rotation, only the old key is configured.
      const pre = loadWithKey(TEST_KEY)
      const legacyRecord = pre.encrypt('old-binance-secret')
      expect(legacyRecord).toMatch(/^v1:/)

      // Phase 2: rotation window — new ENCRYPTION_KEY, old key demoted to PREV.
      const rotating = loadWithKey(TEST_KEY_V2, TEST_KEY)
      expect(rotating.decrypt(legacyRecord)).toBe('old-binance-secret')
    })

    test('during rotation, new writes are tagged v2 and use the new key', () => {
      const rotating = loadWithKey(TEST_KEY_V2, TEST_KEY)
      const freshRecord = rotating.encrypt('new-binance-secret')
      expect(freshRecord).toMatch(/^v2:/)
      expect(rotating.decrypt(freshRecord)).toBe('new-binance-secret')
    })

    test('mixed-version records both decrypt correctly in the same rotation window', () => {
      const pre = loadWithKey(TEST_KEY)
      const v1Record = pre.encrypt('legacy-value')

      const rotating = loadWithKey(TEST_KEY_V2, TEST_KEY)
      const v2Record = rotating.encrypt('fresh-value')

      expect(rotating.decrypt(v1Record)).toBe('legacy-value')
      expect(rotating.decrypt(v2Record)).toBe('fresh-value')
    })

    test('after the rotation window closes (ENCRYPTION_KEY_PREV removed), old v1 records no longer decrypt', () => {
      const pre = loadWithKey(TEST_KEY)
      const v1Record = pre.encrypt('legacy-value')

      // PREV dropped — the retired key's bytes are gone; a new deploy would
      // reuse the "v1" version tag for CURRENT_KEY, so the old record now
      // fails GCM authentication under the wrong key rather than hitting the
      // "unrecognized envelope" branch — both are "no longer decryptable",
      // which is the property this test cares about.
      const postRotation = loadWithKey(TEST_KEY_V2)
      expect(() => postRotation.decrypt(v1Record)).toThrow()
    })
  })
})
