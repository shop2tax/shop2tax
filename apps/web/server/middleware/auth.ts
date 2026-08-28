/**
 * Auth middleware that:
 * 1. Handles Local Mode (no OAuth) — injects System-User headers
 * 2. Checks idle session timeout (120 min)
 * 3. Updates lastActivityAt on each request
 * 4. Injects X-User headers for FastAPI
 *
 * Flow: Nuxt SSR → FastAPI (internal network only)
 * FastAPI trusts these headers because it's only accessible via Nuxt proxy.
 */

// System user for Local Mode (no OAuth configured)
const SYSTEM_USER_ID = '00000000-0000-0000-0000-000000000000'

// Idle timeout: 120 minutes in milliseconds
const IDLE_TIMEOUT_MS = 120 * 60 * 1000

// Throttle activity updates to avoid cookie rewrite on every request
const ACTIVITY_UPDATE_THRESHOLD_MS = 60 * 1000 // 1 minute

export default defineEventHandler(async (event) => {
  // Only protect FastAPI routes at /api/v1/**
  if (!event.path.startsWith('/api/v1')) {
    return
  }

  // Public endpoints that don't require authentication
  if (event.path === '/api/v1/settings/public') {
    return
  }

  const config = useRuntimeConfig()

  // Local Mode: No OAuth credentials → inject System-User, skip session check
  // This enables zero-config local usage without login
  const isLocalMode = !config.oauth?.google?.clientId
  if (isLocalMode) {
    event.node.req.headers['x-user-id'] = SYSTEM_USER_ID
    event.node.req.headers['x-user-name'] = 'Local User'
    event.node.req.headers['x-user-email'] = 'local@localhost'
    // No proxy secret needed in Local Mode — backend also detects Local Mode
    return
  }

  const session = await getUserSession(event)

  if (!session?.user) {
    throw createError({ statusCode: 401, message: 'Unauthorized' })
  }

  // Check idle timeout
  const lastActivity = session.lastActivityAt || session.loggedInAt || 0
  const now = Date.now()
  const idleTime = now - lastActivity

  if (idleTime > IDLE_TIMEOUT_MS) {
    // Clear expired session
    await clearUserSession(event)
    throw createError({
      statusCode: 401,
      message: 'Session expired due to inactivity',
    })
  }

  // Update last activity timestamp (throttled - only if >60s since last update)
  if (now - lastActivity > ACTIVITY_UPDATE_THRESHOLD_MS) {
    await setUserSession(event, {
      ...session,
      lastActivityAt: now,
    })
  }

  // Inject user info for FastAPI
  event.node.req.headers['x-user-id'] = String(session.user.id)
  event.node.req.headers['x-user-email'] = session.user.email
  event.node.req.headers['x-user-name'] = session.user.name || ''

  // Proxy secret for defense in depth
  event.node.req.headers['x-proxy-secret'] = config.proxySecret || ''
})
