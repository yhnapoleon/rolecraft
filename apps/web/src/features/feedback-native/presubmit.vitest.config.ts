import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

/** Real-DOM checks of the pre-submission card; CHROME_BIN uses the regression QA driver. */
export default defineConfig({
  root: fileURLToPath(new URL('../../../', import.meta.url)),
  test: {
    include: ['src/features/feedback-native/presubmit.browser.mjs'],
    testTimeout: 30000,
    hookTimeout: 30000,
  },
});
