// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: '2024-12-01',

  app: {
    head: {
      title: 'shop2tax',
      titleTemplate: '%s | shop2tax',
      link: [
        {
          rel: 'preconnect',
          href: 'https://fonts.googleapis.com',
        },
        {
          rel: 'preconnect',
          href: 'https://fonts.gstatic.com',
          crossorigin: '',
        },
        {
          rel: 'stylesheet',
          href: 'https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;1,9..40,400&family=JetBrains+Mono:wght@400;500;600&display=swap',
        },
      ],
    },
    pageTransition: { name: 'page', mode: 'out-in' },
  },

  modules: [
    '@nuxt/ui',
    '@nuxt/eslint',
    '@vueuse/nuxt',
    'nuxt-auth-utils',
  ],

  css: ['~/assets/css/main.css'],

  devtools: { enabled: true },

  sourcemap: {
    server: false,
    client: false,
  },

  runtimeConfig: {
    // Public config (exposed to client)
    public: {
      // Auto-detect: OAuth credentials present → auth required, otherwise Local Mode
      authEnabled: !!process.env.GOOGLE_CLIENT_ID,
    },
    // Server-only config (from environment variables)
    proxySecret: process.env.NUXT_PROXY_SECRET || '',
    session: {
      name: 'shop2tax-session',
      password: process.env.SESSION_SECRET || '',
      maxAge: 60 * 60 * 24 * 7, // 7 days
      cookie: {
        sameSite: 'lax',
        secure: process.env.NODE_ENV === 'production',
      },
    },
    oauth: {
      google: {
        clientId: process.env.GOOGLE_CLIENT_ID || '',
        clientSecret: process.env.GOOGLE_CLIENT_SECRET || '',
        redirectURL: '',
        scope: ['openid', 'email', 'profile'],
      },
    },
    apiUrl: process.env.API_URL || 'http://localhost:8000',
  },

  eslint: {
    config: {
      standalone: false,
    },
  },

  typescript: {
    strict: true,
    typeCheck: process.env.NODE_ENV === 'production',
  },
})
