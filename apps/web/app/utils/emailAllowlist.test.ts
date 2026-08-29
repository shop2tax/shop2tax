// Unit tests for the login authorization allowlist (server/utils/emailAllowlist.ts).
// The logic is a pure function, so it is tested directly. The file lives under
// app/ because the vitest include glob is `app/**` only; the import reaches into
// the server util it covers.
import { describe, expect, it } from 'vitest'
import { isAllowlistConfigured, isLoginAllowed } from '../../server/utils/emailAllowlist'

const verified = (email: string) => ({ email, emailVerified: true })
const unverified = (email: string) => ({ email, emailVerified: false })

describe('isLoginAllowed', () => {
  it('denies when no allowlist is configured (fail-closed)', () => {
    expect(isLoginAllowed(verified('owner@example.com'), { allowedEmails: '', allowedEmailDomains: '' })).toBe(false)
  })

  it('denies when the allowlist is only whitespace/empty entries (fail-closed)', () => {
    expect(isLoginAllowed(verified('owner@example.com'), { allowedEmails: '  ', allowedEmailDomains: ' , ' })).toBe(false)
  })

  it('allows any account when the wildcard opt-in is set', () => {
    expect(isLoginAllowed(verified('anyone@gmail.com'), { allowedEmails: '', allowedEmailDomains: '*' })).toBe(true)
  })

  it('allows even an unverified email under the wildcard opt-in (deliberately open)', () => {
    expect(isLoginAllowed(unverified('anyone@gmail.com'), { allowedEmails: '', allowedEmailDomains: '*' })).toBe(true)
  })

  it('allows an exact email match (verified)', () => {
    expect(isLoginAllowed(verified('owner@example.com'), { allowedEmails: 'owner@example.com', allowedEmailDomains: '' })).toBe(true)
  })

  it('matches emails case-insensitively', () => {
    expect(isLoginAllowed(verified('Owner@Example.com'), { allowedEmails: 'owner@example.com', allowedEmailDomains: '' })).toBe(true)
    expect(isLoginAllowed(verified('owner@example.com'), { allowedEmails: 'OWNER@EXAMPLE.COM', allowedEmailDomains: '' })).toBe(true)
  })

  it('allows a domain match (verified)', () => {
    expect(isLoginAllowed(verified('someone@example.com'), { allowedEmails: '', allowedEmailDomains: 'example.com' })).toBe(true)
  })

  it('matches domains case-insensitively', () => {
    expect(isLoginAllowed(verified('someone@Example.COM'), { allowedEmails: '', allowedEmailDomains: 'EXAMPLE.com' })).toBe(true)
  })

  it('honors either list (email OR domain)', () => {
    const config = { allowedEmails: 'boss@other.de', allowedEmailDomains: 'example.com' }
    expect(isLoginAllowed(verified('boss@other.de'), config)).toBe(true)
    expect(isLoginAllowed(verified('staff@example.com'), config)).toBe(true)
  })

  it('ignores empty entries from trailing/duplicate commas', () => {
    expect(isLoginAllowed(verified('owner@example.com'), { allowedEmails: 'owner@example.com,,', allowedEmailDomains: '' })).toBe(true)
  })

  it('denies an unverified email when an allowlist is active (fail-closed on unverified)', () => {
    expect(isLoginAllowed(unverified('owner@example.com'), { allowedEmails: 'owner@example.com', allowedEmailDomains: '' })).toBe(false)
  })

  it('denies an account that is on neither list', () => {
    expect(isLoginAllowed(verified('stranger@evil.com'), { allowedEmails: 'owner@example.com', allowedEmailDomains: 'example.com' })).toBe(false)
  })

  it('matches the domain after the LAST @, defeating crafted local parts', () => {
    // lastIndexOf('@') → domain is evil.com, which is not allowed
    expect(isLoginAllowed(verified('someone@example.com@evil.com'), { allowedEmails: '', allowedEmailDomains: 'example.com' })).toBe(false)
  })

  it('rejects an email without an @', () => {
    expect(isLoginAllowed(verified('notanemail'), { allowedEmails: '', allowedEmailDomains: 'example.com' })).toBe(false)
  })

  it('rejects an empty domain (email ending in @)', () => {
    expect(isLoginAllowed(verified('user@'), { allowedEmails: '', allowedEmailDomains: 'example.com' })).toBe(false)
  })

  it('does not treat a subdomain or suffix as a domain match', () => {
    expect(isLoginAllowed(verified('user@sub.example.com'), { allowedEmails: '', allowedEmailDomains: 'example.com' })).toBe(false)
    expect(isLoginAllowed(verified('user@example.com.evil.com'), { allowedEmails: '', allowedEmailDomains: 'example.com' })).toBe(false)
  })
})

describe('isAllowlistConfigured', () => {
  it('is false when both lists are empty', () => {
    expect(isAllowlistConfigured({ allowedEmails: '', allowedEmailDomains: '' })).toBe(false)
  })

  it('is false when both lists are only whitespace/commas', () => {
    expect(isAllowlistConfigured({ allowedEmails: '  ', allowedEmailDomains: ' , ' })).toBe(false)
  })

  it('is true when emails are set', () => {
    expect(isAllowlistConfigured({ allowedEmails: 'owner@example.com', allowedEmailDomains: '' })).toBe(true)
  })

  it('is true when domains are set', () => {
    expect(isAllowlistConfigured({ allowedEmails: '', allowedEmailDomains: 'example.com' })).toBe(true)
  })

  it('is true for the wildcard opt-in', () => {
    expect(isAllowlistConfigured({ allowedEmails: '', allowedEmailDomains: '*' })).toBe(true)
  })
})
