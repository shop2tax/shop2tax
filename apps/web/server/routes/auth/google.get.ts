/**
 * Google OAuth handler.
 *
 * Handles OAuth flow with Google (openid email profile scopes).
 * Stores user info in session cookie after successful auth.
 *
 * User mapping: id=sub, username=email.split('@')[0], email, name
 */
export default defineOAuthGoogleEventHandler({
  async onSuccess(event, { user }) {
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
