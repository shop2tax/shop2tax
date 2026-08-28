/**
 * Proxy all /api/v1/** requests to FastAPI backend.
 *
 * Uses proxyRequest which properly forwards headers including X-User-* headers
 * set by the auth middleware.
 */
export default defineEventHandler(async (event) => {
  const config = useRuntimeConfig()
  const path = event.path

  // Proxy to FastAPI
  const target = `${config.apiUrl}${path}`

  return proxyRequest(event, target)
})
