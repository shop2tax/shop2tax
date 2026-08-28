/**
 * Extend nuxt-auth-utils User type with our session fields.
 */
declare module '#auth-utils' {
  interface User {
    id: string
    email: string
    name?: string
    picture?: string
  }

  interface UserSession {
    user?: User
    loggedInAt?: number
    lastActivityAt?: number
  }
}

export {}
