import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

/** Dedicated real-browser tests; CHROME_BIN uses the same driver as regression QA. */
export default defineConfig({
  root: fileURLToPath(new URL('../../../', import.meta.url)),
  test: {
    include: ['src/features/feedback-native/model-advice.browser.mjs'],
    testTimeout: 20000,
    hookTimeout: 20000,
  },
});
