// Plan 7 Step 7.3 (SRV-4): setUserAlgoAccess must invalidate the target
// user's verifyJWT cache entry the instant a grant/revoke lands, preserving
// server/CLAUDE.md's documented "grants/revokes apply immediately — no JWT
// re-issue needed" guarantee now that verifyJWT caches User.findById.
jest.mock('../../models/User', () => ({ findById: jest.fn(), updateOne: jest.fn() }))
jest.mock('../../middleware/auth.middleware', () => ({ invalidateUserCache: jest.fn() }))

const User = require('../../models/User')
const { invalidateUserCache } = require('../../middleware/auth.middleware')
const { setUserAlgoAccess } = require('../admin.controller')

function mockRes() {
  return { json: jest.fn() }
}

describe('setUserAlgoAccess', () => {
  afterEach(() => jest.clearAllMocks())

  test('invalidates the target user cache entry after granting access', async () => {
    User.findById.mockReturnValue({ lean: () => Promise.resolve({ _id: 'target1', role: 'user' }) })
    User.updateOne.mockResolvedValue({})
    const req = { params: { id: 'target1' }, body: { status: 'granted' }, user: { id: 'admin1' } }
    await setUserAlgoAccess(req, mockRes())
    expect(invalidateUserCache).toHaveBeenCalledWith('target1')
  })

  test('invalidates the target user cache entry after revoking access', async () => {
    User.findById.mockReturnValue({ lean: () => Promise.resolve({ _id: 'target1', role: 'user' }) })
    User.updateOne.mockResolvedValue({})
    const req = { params: { id: 'target1' }, body: { status: 'none' }, user: { id: 'admin1' } }
    await setUserAlgoAccess(req, mockRes())
    expect(invalidateUserCache).toHaveBeenCalledWith('target1')
  })

  test('does not invalidate anything when the request is rejected before the update (invalid status)', async () => {
    const req = { params: { id: 'target1' }, body: { status: 'bogus' }, user: { id: 'admin1' } }
    await expect(setUserAlgoAccess(req, mockRes())).rejects.toMatchObject({ statusCode: 400 })
    expect(invalidateUserCache).not.toHaveBeenCalled()
  })

  test('does not invalidate anything when the target is an admin (blocked before the update)', async () => {
    User.findById.mockReturnValue({ lean: () => Promise.resolve({ _id: 'target1', role: 'admin' }) })
    const req = { params: { id: 'target1' }, body: { status: 'none' }, user: { id: 'admin1' } }
    await expect(setUserAlgoAccess(req, mockRes())).rejects.toMatchObject({ statusCode: 403 })
    expect(invalidateUserCache).not.toHaveBeenCalled()
  })
})
