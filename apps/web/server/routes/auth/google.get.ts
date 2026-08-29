/**
 * Google OAuth handler.
 *
 * Handles OAuth flow with Google (openid email profile scopes).
 * Stores user info in session cookie after successful auth.
 *
 * User mapping: id=sub, username=email.split('@')[0], email, name
 *
 * Authorization: Google authenticates any Google account, so before issuing a
 * session we enforce an operator-configured email/domain allowlist (see
 * isLoginAllowed). Fail-closed: with no allowlist configured, every login is
 * denied. Set ALLOWED_EMAIL_DOMAINS=* to deliberately allow any account.
 */
export default defineOAuthGoogleEventHandler({
  async onSuccess(event, { user }) {
    const config = useRuntimeConfig(event)

    // Authorization gate: reject anyone not on the allowlist before a session is
    // ever established. Fail-closed — with no allowlist configured, deny and point
    // the operator at the fix; with one configured, deny accounts not on it.
    const allowlistConfig = {
      allowedEmails: config.allowedEmails,
      allowedEmailDomains: config.allowedEmailDomains,
    }
    const allowed = isLoginAllowed(
      { email: user.email, emailVerified: user.email_verified },
      allowlistConfig,
    )
    if (!allowed) {
      const reason = isAllowlistConfigured(allowlistConfig) ? 'forbidden' : 'login_not_configured'
      console.warn('Google OAuth login rejected', {
        email: user.email,
        emailVerified: user.email_verified,
        reason,
      })
      return sendRedirect(event, `/login?error=${reason}`)
    }

    const now = Date.now()

    // Map Google user to session format
    // id: Google's "sub" claim (unique user ID)
    // username: derived from email (before @)
    await setUserSession(event, {
      user: {
        id: user.sub,
        email: user.email,
        name: user.name,
        picture: user.picture,
      },
      loggedInAt: now,
      lastActivityAt: now,
    })

    return sendRedirect(event, '/')
  },
  onError(_event, error) {
    console.error('Google OAuth error:', error)
    return sendRedirect(_event, '/login?error=oauth_failed')
  },
})
