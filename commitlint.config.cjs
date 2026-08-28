// Commitlint configuration
// Follows Conventional Commits: https://www.conventionalcommits.org/

module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'header-max-length': [2, 'always', 100],
    'scope-enum': [
      2,
      'always',
      [
        'api',
        'web',
        'docker',
        'deps',
        'plan',
      ],
    ],
    'scope-empty': [0],
  },
}
