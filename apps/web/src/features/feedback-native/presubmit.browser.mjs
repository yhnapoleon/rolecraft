/** Real-DOM checks of the pre-submission card in the submission panel, zh and en: it sits right
 * above the submit button and previews the exact choice; the feedback page, a submitted practice
 * and a read-only one show no card and request nothing; a failed preview says so and submitting
 * stays available; reopening the panel restores the last choice until it is submitted. A
 * controlled fixture page (presubmit-check.html); nothing is saved. The browser gate runs this
 * before its services; alone:
 * CHROME_BIN=… npx vitest run --config src/features/feedback-native/presubmit.vitest.config.ts */
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { afterAll, beforeAll, expect, it } from 'vitest';
import { waitFor } from '../../../tests/regression/browser-support.mjs';
import { delay, launch } from '../../../tests/walkthrough/cdp.mjs';

let server;
let origin;
beforeAll(async () => {
  // Any free port, so parallel worktrees and a running gate never collide.
  server = await createServer({
    root: fileURLToPath(new URL('../../../', import.meta.url)),
    server: { port: 0, strictPort: true },
    logLevel: 'error',
  });
  await server.listen();
  origin = `http://127.0.0.1:${server.httpServer.address().port}`;
});
afterAll(async () => {
  await server?.close();
});

const LANGUAGES = ['zh', 'en'];
const card = `document.querySelector('#fixture [data-presubmit]')`;
const settled = `(() => { const c = ${card}; return !!c && c.getAttribute('aria-busy') === 'false' && !!c.querySelector('.presubmit__count'); })()`;
const version = { session_id: 'fixture', kind: 'product', object_id: 'note', version: 2 };
const chosen = (decision) => ({ decision, products: [version] });

async function open(language, surface = 'submission') {
  const browser = await launch({ width: 1200, height: 900, reduced: true });
  await browser.goto(
    `${origin}/src/features/feedback-native/presubmit-check.html?lang=${language}&surface=${surface}`,
  );
  await waitFor(
    browser,
    `!!window.fixture && !!document.querySelector('#fixture .native-feedback')`,
  );
  return browser;
}
/** Tick the listed version and pick a decision, as a person would. */
async function choose(browser, decision) {
  await browser.click('#fixture input[type="checkbox"]');
  await browser.select('#fixture select', decision);
}
const requested = (browser, operation) =>
  browser.ev(
    `window.fixture.calls.filter((c) => c.operation === '${operation}').map((c) => ({ decision: c.input.decision, products: c.input.products }))`,
  );
const submitButton = (language) =>
  `[...document.querySelectorAll('#fixture button')].find((b) => b.textContent.trim() === '${
    language === 'en' ? 'Submit selected versions' : '提交选中的版本'
  }')`;

it.each(LANGUAGES)(
  'PRESUBMIT-UI-01 %s: the card sits between the decision and the submit button',
  async (language) => {
    const t = (zh, en) => (language === 'en' ? en : zh);
    const browser = await open(language);
    try {
      const around = await browser.ev(`(() => {
        const c = ${card};
        return {
          before: c.previousElementSibling?.getAttribute('aria-label'),
          after: c.nextElementSibling?.tagName + ' ' + c.nextElementSibling?.textContent.trim(),
          shown: !c.hidden && getComputedStyle(c).display !== 'none',
          text: c.innerText,
        };
      })()`);
      expect(around).toMatchObject({
        before: t('本次决定', 'Your decision'),
        after: `BUTTON ${t('提交选中的版本', 'Submit selected versions')}`,
        shown: true,
      });
      expect(around.text).toContain(t('选好作品版本和决定后', 'Choose versions and a decision'));
      expect(await requested(browser, 'preview')).toEqual([]);
      await choose(browser, 'launch');
      await waitFor(browser, settled);
      expect(await browser.ev(`${card}.querySelector('.presubmit__count').textContent`)).toBe(
        t('2/3 项已满足', '2/3 met'),
      );
      expect(await requested(browser, 'preview')).toEqual([chosen('launch')]);
    } finally {
      await browser.close();
    }
  },
);

it.each(LANGUAGES)('PRESUBMIT-UI-02 %s: the feedback page has no card', async (language) => {
  const browser = await open(language, 'feedback');
  try {
    expect(await browser.ev(`!!document.querySelector('[data-presubmit]')`)).toBe(false);
    await delay(400);
    expect(await browser.ev('window.fixture.calls')).toEqual([]);
  } finally {
    await browser.close();
  }
});

it.each(LANGUAGES)(
  'PRESUBMIT-UI-03 %s: no card once submitted, nor while the practice is read-only',
  async (language) => {
    const browser = await open(language);
    try {
      await choose(browser, 'launch');
      await waitFor(browser, settled);
      // Submitted: the panel keeps the saved snapshot and the card leaves.
      await browser.ev(`window.fixture.state.status = 'submitted'; window.fixture.update()`);
      expect(await browser.ev(`getComputedStyle(${card}).display`)).toBe('none');
      await browser.ev(`window.fixture.remount()`);
      expect(await browser.ev(`getComputedStyle(${card}).display`)).toBe('none');
      expect(await requested(browser, 'preview')).toEqual([chosen('launch')]);
    } finally {
      await browser.close();
    }
    const readOnly = await open(language);
    try {
      // Read-only (the host offers no rule check): no card, and choosing requests nothing.
      await readOnly.ev(
        `window.fixture.state.readOnly = true; window.fixture.canPreview = false; window.fixture.remount()`,
      );
      expect(await readOnly.ev(`getComputedStyle(${card}).display`)).toBe('none');
      await choose(readOnly, 'launch');
      await delay(600);
      expect(await requested(readOnly, 'preview')).toEqual([]);
    } finally {
      await readOnly.close();
    }
  },
);

it.each(LANGUAGES)(
  'PRESUBMIT-UI-04 %s: a failed preview says so and submitting stays available',
  async (language) => {
    const t = (zh, en) => (language === 'en' ? en : zh);
    const browser = await open(language);
    try {
      await browser.ev('window.fixture.failPreview = true');
      await choose(browser, 'launch');
      await waitFor(
        browser,
        `${card}.getAttribute('aria-busy') === 'false' && ${card}.innerText.includes(${JSON.stringify(
          t(
            '预演暂时算不出来，不影响交付。',
            'The preview is unavailable right now; you can still submit.',
          ),
        )})`,
      );
      expect(await browser.ev(`${submitButton(language)}.disabled`)).toBe(false);
      await browser.ev(`${submitButton(language)}.click()`);
      await waitFor(browser, `window.fixture.calls.some((c) => c.operation === 'submit')`);
      expect(await requested(browser, 'submit')).toEqual([chosen('launch')]);
    } finally {
      await browser.close();
    }
  },
);

it.each(LANGUAGES)(
  'PRESUBMIT-UI-05 %s: reopening the panel restores the last choice until it is submitted',
  async (language) => {
    const browser = await open(language);
    const picked = `({ checked: document.querySelector('#fixture input[type="checkbox"]').checked, decision: document.querySelector('#fixture select').value })`;
    try {
      await choose(browser, 'launch_narrow');
      await waitFor(browser, settled);
      await browser.ev('window.fixture.close()');
      expect(await browser.ev(`!!document.querySelector('[data-presubmit]')`)).toBe(false);
      await browser.ev('window.fixture.remount()');
      await waitFor(browser, settled);
      expect(await browser.ev(picked)).toEqual({ checked: true, decision: 'launch_narrow' });
      expect(await requested(browser, 'preview')).toEqual([
        chosen('launch_narrow'),
        chosen('launch_narrow'),
      ]);
      // Submitting forgets the choice: a later panel (a new cycle) starts empty.
      await browser.ev(`${submitButton(language)}.click()`);
      await waitFor(browser, `window.fixture.state.status === 'submitted'`);
      await delay(300);
      await browser.ev(
        `window.fixture.close(); window.fixture.state.status = 'active'; window.fixture.remount()`,
      );
      expect(await browser.ev(picked)).toEqual({ checked: false, decision: '' });
    } finally {
      await browser.close();
    }
  },
);
