/**
 * Validate required environment variables at server startup.
 *
 * Fails fast with clear error messages instead of cryptic runtime errors.
 * Skips validation during prerendering (build time).
 * Skips ALL validation in Local Mode (no OAuth credentials configured).
 */
export default defineNitroPlugin(() => {
  // Skip validation during prerendering - env vars not needed for static generation
  if (import.meta.prerender) {
    return
  }

  const config = useRuntimeConfig()

  // Local Mode: No OAuth credentials → skip all secret validation
  // This enables zero-config local usage: `docker compose up` → app works immediately
  const isLocalMode = !config.oauth?.google?.clientId
  if (isLocalMode) {
    return
  }

  // === Auth Mode: Validate all required secrets ===

  // Session secret validation
  if (!config.session.password || config.session.password.length < 32) {
    throw new Error(
      'SESSION_SECRET (maps to NUXT_SESSION_PASSWORD) must be set and at least 32 characters. '
      + 'Generate one with: openssl rand -base64 32',
    )
  }

  // OAuth credentials validation (clientId already checked above for Local Mode detection)
  if (!config.oauth.google.clientSecret) {
    throw new Error(
      'GOOGLE_CLIENT_SECRET is required. '
      + 'Create OAuth app at: https://console.cloud.google.com/apis/credentials',
    )
  }

  // Login allowlist advisory. The actual enforcement is fail-closed in
  // isLoginAllowed() (server/utils/emailAllowlist.ts): in Auth Mode without an
  // allowlist, EVERY login is denied — secure by default. This check does not
  // throw on purpose: a thrown startup error would take the whole app down, so
  // instead the app stays up (login-blocked) and warns loudly so the operator
  // knows why nobody can sign in. To deliberately allow any Google account, set
  // ALLOWED_EMAIL_DOMAINS=*.
  const hasLoginAllowlist = Boolean(config.allowedEmails?.trim() || config.allowedEmailDomains?.trim())
  if (!hasLoginAllowlist) {
    console.warn(
      '[shop2tax] SECURITY: Auth Mode is active but no login allowlist is set — '
      + 'ALL logins are denied until you configure one. '
      + 'Set ALLOWED_EMAILS and/or ALLOWED_EMAIL_DOMAINS (or ALLOWED_EMAIL_DOMAINS=* to allow any Google account).',
    )
  }
})
