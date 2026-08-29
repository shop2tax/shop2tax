/**
 * Login authorization allowlist for Google OAuth (Auth Mode).
 *
 * Authentication (proving control of a Google account) is not authorization
 * (being permitted to use this instance). The Google consent screen accepts ANY
 * Google account, and every user of a shop2tax instance shares the same tenant,
 * so the login route must decide who is allowed a session.
 *
 * Two operator-configured, case-insensitive allowlists (either or both):
 *  - allowedEmails: comma-separated exact addresses (e.g. "a@x.de,b@y.de")
 *  - allowedEmailDomains: comma-separated domains matched against the part after
 *    the last '@' (e.g. "example.com" allows anyone@example.com)
 *
 * Secure by default (fail-closed): when NO allowlist is configured, login is
 * denied. In Auth Mode the app also refuses to start without an allowlist (see
 * server/plugins/validate-env.ts), so this denial is a defence-in-depth backstop
 * — a misconfigured or bypassed setup never silently admits every Google account.
 *
 * Explicit opt-in to open access: setting allowedEmailDomains to "*" deliberately
 * allows any Google account (e.g. a public instance). This is a conscious choice,
 * never the default.
 */

/** Wildcard in the domain list that opts into allowing any Google account. */
const ALLOW_ANY_ACCOUNT = '*'

export interface EmailAllowlistConfig {
  /** Comma-separated exact email addresses (case-insensitive). */
  allowedEmails: string
  /** Comma-separated domains, matched against the part after '@' (case-insensitive). */
  allowedEmailDomains: string
}

export interface GoogleIdentity {
  email: string
  /** Whether Google marked the email as verified (email_verified claim). */
  emailVerified: boolean
}

function parseList(raw: string): string[] {
  return raw
    .split(',')
    .map(entry => entry.trim().toLowerCase())
    .filter(entry => entry.length > 0)
}

/**
 * Decide whether a Google-authenticated identity is permitted to sign in.
 *
 * @returns true if the login is allowed, false if it must be rejected.
 */
export function isLoginAllowed(identity: GoogleIdentity, config: EmailAllowlistConfig): boolean {
  const allowedEmails = parseList(config.allowedEmails)
  const allowedDomains = parseList(config.allowedEmailDomains)

  // Explicit opt-in to open access (ALLOWED_EMAIL_DOMAINS=*): any Google account
  // is deliberately allowed. A conscious choice, never the default.
  if (allowedDomains.includes(ALLOW_ANY_ACCOUNT)) {
    return true
  }

  // Fail-closed: no allowlist configured → deny. Auth Mode refuses to start
  // without one (validate-env.ts), so this is a defence-in-depth backstop that
  // never silently admits every Google account.
  if (allowedEmails.length === 0 && allowedDomains.length === 0) {
    return false
  }

  // Never authorize based on an unverified email, otherwise a caller could claim
  // an allowed address they do not control.
  if (!identity.emailVerified) {
    return false
  }

  const email = identity.email.trim().toLowerCase()
  if (allowedEmails.includes(email)) {
    return true
  }

  const atIndex = email.lastIndexOf('@')
  if (atIndex === -1) {
    return false
  }

  const domain = email.slice(atIndex + 1)
  return domain.length > 0 && allowedDomains.includes(domain)
}

/**
 * Whether an operator has configured any allowlist at all (including the "*"
 * opt-in). Lets the login route tell "no allowlist configured" apart from
 * "this account is not on the list", so it can show a helpful message instead
 * of a misleading "forbidden".
 */
export function isAllowlistConfigured(config: EmailAllowlistConfig): boolean {
  return parseList(config.allowedEmails).length > 0 || parseList(config.allowedEmailDomains).length > 0
}
