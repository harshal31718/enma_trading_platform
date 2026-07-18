const { isRejectedByAdminOnlyRestriction } = require('../passport')

describe('isRejectedByAdminOnlyRestriction (local-dev admin-only login gate)', () => {
  test('production/default (restriction unset) never rejects anyone', () => {
    expect(isRejectedByAdminOnlyRestriction('anyone@example.com', {
      restrictToAdmin: undefined,
      adminEmail: 'admin@example.com',
    })).toBe(false)
  })

  test('restriction "false" (explicit) never rejects anyone', () => {
    expect(isRejectedByAdminOnlyRestriction('anyone@example.com', {
      restrictToAdmin: 'false',
      adminEmail: 'admin@example.com',
    })).toBe(false)
  })

  test('restriction enabled: rejects a non-admin email', () => {
    expect(isRejectedByAdminOnlyRestriction('someone-else@example.com', {
      restrictToAdmin: 'true',
      adminEmail: 'admin@example.com',
    })).toBe(true)
  })

  test('restriction enabled: allows the admin email', () => {
    expect(isRejectedByAdminOnlyRestriction('admin@example.com', {
      restrictToAdmin: 'true',
      adminEmail: 'admin@example.com',
    })).toBe(false)
  })

  test('restriction enabled: admin email match is case-insensitive on the configured side', () => {
    expect(isRejectedByAdminOnlyRestriction('admin@example.com', {
      restrictToAdmin: 'true',
      adminEmail: 'ADMIN@EXAMPLE.COM',
    })).toBe(false)
  })

  test('restriction enabled but ADMIN_EMAIL unset: rejects everyone (fail closed, not open)', () => {
    expect(isRejectedByAdminOnlyRestriction('admin@example.com', {
      restrictToAdmin: 'true',
      adminEmail: undefined,
    })).toBe(true)
  })
})
