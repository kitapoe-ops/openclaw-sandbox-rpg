/**
 * Minimal ESLint config for sandbox-rpg-tmp/frontend.
 *
 * History: CI step `npm run lint` (which runs `eslint . --ext .vue,.ts,.tsx --fix`)
 * has been failing silently for many commits because no .eslintrc* file existed
 * in the frontend/ directory. ESLint 8 falls back to erroring out when no
 * config can be found.
 *
 * This config is intentionally minimal: it tells ESLint to scan the same
 * files the npm script targets, using the modern flat-config-friendly ruleset
 * bundled with ESLint 8. No custom rules are added — the goal is to make
 * the lint step pass in CI so the gate can be enforced. Real lint rules
 * can be tightened in a follow-up.
 *
 * If you need to opt out of lint entirely (e.g. for a hotfix), pass
 * `--no-eslintrc` or remove the `lint` step from .github/workflows/ci.yml.
 */
module.exports = {
  root: true,
  env: {
    browser: true,
    es2022: true,
    node: true,
  },
  extends: ['eslint:recommended'],
  parser: 'vue-eslint-parser',
  parserOptions: {
    parser: '@typescript-eslint/parser',
    ecmaVersion: 'latest',
    sourceType: 'module',
    extraFileExtensions: ['.vue'],
  },
  plugins: ['@typescript-eslint', 'vue'],
  ignorePatterns: ['dist/', 'node_modules/'],
  rules: {
    // Vue 3 SFCs use <template> + <script setup> which trips up some
    // recommended rules. Disable the ones that are noise on Vue 3 code.
    'no-unused-vars': 'off', // TypeScript handles this better
    '@typescript-eslint/no-unused-vars': 'warn',
    'vue/multi-word-component-names': 'off', // GameView, HomeView, etc.
  },
}
