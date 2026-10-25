import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

/** Isolated reference reader in a real DOM; uses the gate's CHROME_BIN. */
export default defineConfig({
  root: fileURLToPath(new URL('../', import.meta.url)),
  test: {
    include: ['src/v4-references.browser.mjs'],
    testTimeout: 30000,
    hookTimeout: 30000,
  },
});
