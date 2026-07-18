// reconciliation.js transitively requires ./symbolLock -> ../config/redis,
// which opens a real ioredis connection at module-load time if unmocked —
// the open socket keeps the Jest process alive after the test itself
// finishes (mirrors the same fix already applied in symbolLock.test.js).
jest.mock('../../config/redis', () => new (require('ioredis-mock'))())
jest.mock('../engineClient', () => ({ post: jest.fn(), get: jest.fn() }))
jest.mock('../../models/Settings', () => ({ findOne: jest.fn() }))
jest.mock('../../utils/encryption', () => ({ decrypt: jest.fn() }))

const engineClient = require('../engineClient')
const Settings = require('../../models/Settings')
const { decrypt } = require('../../utils/encryption')
const { _tryResumeSession, _rawCredsFor } = require('../reconciliation')

describe('Plan 5 Step 5.6 — resume-on-restart (opt-in, default off)', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    decrypt.mockImplementation((v) => `decrypted:${v}`)
  })

  describe('_rawCredsFor', () => {
    test('returns null when the user has no saved credentials', async () => {
      Settings.findOne.mockReturnValue({ lean: () => Promise.resolve(null) })
      const creds = await _rawCredsFor('user1', new Map())
      expect(creds).toBeNull()
    })

    test('returns decrypted creds + saved taker fee when present', async () => {
      Settings.findOne.mockReturnValue({
        lean: () => Promise.resolve({ encryptedApiKey: 'ek', encryptedApiSecret: 'es', takerFee: 0.0007 }),
      })
      const creds = await _rawCredsFor('user1', new Map())
      expect(creds).toEqual({ apiKey: 'decrypted:ek', apiSecret: 'decrypted:es', feeRate: 0.0007 })
    })

    test('falls back to the default fee rate when unset', async () => {
      Settings.findOne.mockReturnValue({
        lean: () => Promise.resolve({ encryptedApiKey: 'ek', encryptedApiSecret: 'es' }),
      })
      const creds = await _rawCredsFor('user1', new Map())
      expect(creds.feeRate).toBe(0.0005)
    })

    test('caches per userId — a second call does not hit Settings again', async () => {
      Settings.findOne.mockReturnValue({
        lean: () => Promise.resolve({ encryptedApiKey: 'ek', encryptedApiSecret: 'es' }),
      })
      const cache = new Map()
      await _rawCredsFor('user1', cache)
      await _rawCredsFor('user1', cache)
      expect(Settings.findOne).toHaveBeenCalledTimes(1)
    })
  })

  describe('_tryResumeSession', () => {
    const session = {
      _id: 'sess1',
      userId: 'user1',
      strategyName: 'MicroScalper',
      symbols: ['BTCUSDT'],
      timeframe: '1h',
      params: {},
      capital: '500',
      leverage: 5,
      riskParams: { default: {} },
    }

    test('returns false without calling the engine when credentials are missing', async () => {
      Settings.findOne.mockReturnValue({ lean: () => Promise.resolve(null) })
      const result = await _tryResumeSession(session, new Map())
      expect(result).toBe(false)
      expect(engineClient.post).not.toHaveBeenCalled()
    })

    test('calls POST /algo/sessions with resume:true and the reconstructed config', async () => {
      Settings.findOne.mockReturnValue({
        lean: () => Promise.resolve({ encryptedApiKey: 'ek', encryptedApiSecret: 'es', takerFee: 0.0004 }),
      })
      engineClient.post.mockResolvedValue({ data: { success: true } })

      const result = await _tryResumeSession(session, new Map())

      expect(result).toBe(true)
      expect(engineClient.post).toHaveBeenCalledWith('/algo/sessions', expect.objectContaining({
        session_id: 'sess1',
        strategy_name: 'MicroScalper',
        symbols: ['BTCUSDT'],
        timeframe: '1h',
        capital: '500',
        leverage: 5,
        fee_rate: 0.0004,
        api_key: 'decrypted:ek',
        api_secret: 'decrypted:es',
        resume: true,
      }))
    })

    test('returns false (falls through to stop+flatten) when the engine call throws', async () => {
      Settings.findOne.mockReturnValue({
        lean: () => Promise.resolve({ encryptedApiKey: 'ek', encryptedApiSecret: 'es' }),
      })
      engineClient.post.mockRejectedValue(new Error('engine unreachable'))

      const result = await _tryResumeSession(session, new Map())
      expect(result).toBe(false)
    })
  })
})
