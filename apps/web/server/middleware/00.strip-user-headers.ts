/**
 * Security middleware: Strip incoming X-User-* headers.
 *
 * Defense-in-depth: Prevents attackers from injecting user identity
 * headers if FastAPI is accidentally exposed directly.
 *
 * Runs BEFORE auth.ts (alphabetical order: 00 < auth).
 */
export default defineEventHandler((event) => {
  const headers = event.node.req.headers

  // Strip all X-User-* headers from incoming requests
  for (const key of Object.keys(headers)) {
    if (key.toLowerCase().startsWith('x-user')) {
      delete headers[key]
    }
  }
})
