import antfu from '@antfu/eslint-config'
import withNuxt from './.nuxt/eslint.config.mjs'

export default withNuxt(
  antfu({
    ignores: [
      '**/*.md',
    ],
    rules: {
      'dot-notation': 'off',
      '@typescript-eslint/dot-notation': 'off',
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          varsIgnorePattern: '^_',
          argsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],
      'node/prefer-global/process': 'off',
      // Enforces pnpm trustPolicy=no-downgrade, unsatisfiable with our dependency
      // tree (undici-types/semver/chokidar lack npm provenance).
      'pnpm/yaml-enforce-settings': 'off',
    },
  }),
)
