/**
 * Client-side auth middleware.
 *
 * In Auth Mode: Redirects unauthenticated users to /login.
 * In Local Mode: No redirect — all routes accessible without login.
 */
export default defineNuxtRouteMiddleware(async (to) => {
  const config = useRuntimeConfig()

  // Local Mode: No auth required — skip all checks
  if (!config.public.authEnabled) {
    return
  }

  // Skip auth check for login page
  if (to.path === '/login') {
    return
  }

  const { loggedIn } = useUserSession()

  if (!loggedIn.value) {
    return navigateTo('/login')
  }
})
