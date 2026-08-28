import { defineVitestConfig } from '@nuxt/test-utils/config'

// Default node env; tests needing the Nuxt runtime opt in per-file via `// @vitest-environment nuxt`.
export default defineVitestConfig({
  test: {
    environment: 'node',
    include: ['app/**/*.{test,spec}.ts'],
    environmentOptions: {
      nuxt: {
        domEnvironment: 'happy-dom',
      },
    },
  },
})
