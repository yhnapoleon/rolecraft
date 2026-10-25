import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  root: fileURLToPath(new URL('../../', import.meta.url)),
  test: {
    include: ['src/app/view-transition.browser.mjs'],
    testTimeout: 30000,
    hookTimeout: 30000,
  },
});
