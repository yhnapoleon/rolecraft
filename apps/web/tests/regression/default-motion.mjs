/** Default motion on the normal v4 entry, Chinese then English.
 *
 * The board opens the full brief, closes it, opens one material, closes it and opens another.
 * The reading sheet now slides over the board without changing routes. Each click must answer
 * within a short budget, start the real sheet animation and settle without duplicate mount
 * markers. Document identity, title, content and return focus are checked throughout.
 *
 * Started by `python -m scripts.regression.browser` after published-flows; BASE and OUT come
 * from the runner.
 */
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { delay, launch } from '../walkthrough/cdp.mjs';
import { waitFor } from './browser-support.mjs';

const base = process.env.BASE;
const output = process.env.OUT;
assert.ok(base && output, 'BASE and OUT are required');
mkdirSync(`${output}/screenshots`, { recursive: true });
const ANSWER_MS = 3000;
const LANDING_MS = 5000;
const results = [];

/** A page stuck in script never answers; fail within the budget instead of waiting on CDP. */
async function answer(browser, expression) {
  const value = browser.ev(expression);
  value.catch(() => {});
  let timer;
  const budget = new Promise((_, reject) => {
    timer = setTimeout(
      () => reject(new Error(`The page did not answer within ${ANSWER_MS} ms: ${expression}`)),
      ANSWER_MS,
    );
  });
  try {
    return await Promise.race([value, budget]);
  } finally {
    clearTimeout(timer);
  }
}

const responsiveWait = (browser, expression, milliseconds = ANSWER_MS) =>
  waitFor({ ev: (value) => answer(browser, value) }, expression, milliseconds);

/** The document now slides over the desk. Its real CSS animation must exist and settle;
 * no cloned workspace owner may appear while it is moving. */
async function land(browser) {
  const deadline = Date.now() + LANDING_MS;
  while (Date.now() < deadline) {
    if (
      await answer(
        browser,
        `!document.querySelector('.document-flight') &&
      !document.documentElement.classList.contains('document-in-flight') &&
      [...document.querySelectorAll('.mat-sheet, .mat-dim')].every(node =>
        node.getAnimations().every(animation => animation.playState !== 'running'))`,
      )
    )
      return;
    await delay(100);
  }
  throw new Error(`The reading sheet did not settle within ${LANDING_MS} ms`);
}

async function boardTitle(browser, id) {
  const title = await answer(
    browser,
    `document.querySelector('[data-doc-row=${JSON.stringify(id)}] .doc-row-title')?.textContent.trim()`,
  );
  assert.ok(title, `The board has no row for ${id}`);
  return title;
}

async function open(browser, selector, id) {
  const title = await boardTitle(browser, id);
  await answer(
    browser,
    `(() => {
    const target = document.querySelector(${JSON.stringify(selector)});
    if (!target) throw Error('The document opener is missing');
    target.scrollIntoView({ block: 'center' }); target.click();
  })()`,
  );
  await responsiveWait(
    browser,
    `!!document.querySelector('.mat-sheet[data-state="open"]')`,
    ANSWER_MS,
  );
  const motion = await answer(
    browser,
    `(() => {
    const sheet = document.querySelector('.mat-sheet');
    return { animations: sheet.getAnimations().map(a => a.animationName),
      markers: [sheet, ...sheet.querySelectorAll('*')].flatMap(node =>
        node.getAttributeNames().filter(name => name.startsWith('data-v4-'))) };
  })()`,
  );
  assert.ok(
    motion.animations.includes('rc-sheet-in-right'),
    'Default motion starts the reading sheet',
  );
  assert.deepEqual(motion.markers, [], 'The reading layer must not duplicate v4 mount owners');
  await land(browser);
  assert.equal(await answer(browser, 'location.hash'), '#/work');
  await responsiveWait(
    browser,
    `document.querySelector('.mat-body')?.innerText.length > 40`,
    15000,
  );
  assert.equal(
    await answer(browser, `document.querySelector('.mat-title')?.textContent.trim()`),
    title,
  );
  assert.equal(await answer(browser, `document.querySelector('.mat-sheet').dataset.matSheet`), id);
}

async function backToBoard(browser, id) {
  await answer(
    browser,
    `(() => {
    window.regressionSheetClosing = false;
    const sheet = document.querySelector('.mat-sheet');
    sheet.addEventListener('animationstart', event => {
      if (event.animationName === 'rc-sheet-out-right') window.regressionSheetClosing = true;
    });
    document.querySelector('.mat-x').click();
  })()`,
  );
  await land(browser);
  await responsiveWait(browser, `!document.querySelector('.mat-sheet')`, LANDING_MS);
  assert.equal(
    await answer(browser, 'window.regressionSheetClosing'),
    true,
    'Closing plays the return animation',
  );
  assert.equal(await answer(browser, 'location.hash'), '#/work');
  assert.ok(await boardTitle(browser, id));
  assert.equal(await answer(browser, `document.activeElement?.dataset.docRow`), id);
  assert.equal(
    await answer(browser, `document.querySelectorAll('[data-v4-region="workspace"]').length`),
    1,
    'The board keeps exactly one workspace owner',
  );
}

async function shot(browser, name) {
  await answer(browser, 'document.fonts.ready.then(() => true)');
  await browser.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 0, y: 0 });
  await browser.shot(`${output}/screenshots/${name}.jpg`);
}

async function runLanguage(language) {
  const browser = await launch({ width: 1440, height: 1100, reduced: false });
  const step = async (name, action) => {
    await action();
    results.push({ language, name, status: 'passed' });
    console.log(`PASS ${language} default motion: ${name}`);
  };
  try {
    await browser.goto(base);
    await browser.ev(
      `localStorage.clear();
      localStorage.setItem('rolecraft.locale', ${JSON.stringify(language)});`,
    );
    await browser.goto(base);
    await step('motion is not reduced and the workspace opens', async () => {
      assert.equal(
        await browser.ev(`matchMedia('(prefers-reduced-motion: reduce)').matches`),
        false,
      );
      await waitFor(browser, `!!document.querySelector('[data-action="open-career"]')`);
      await browser.click('[data-action="open-career"]');
      await browser.click('.case-hero [data-action="take-case"]');
      await waitFor(
        browser,
        `location.hash === '#/work' && document.querySelectorAll('[data-doc-row]').length > 2`,
      );
      // Let the one-time entrance choreography finish; looping indicators keep running.
      await waitFor(
        browser,
        `document.getAnimations().every((item) =>
          item.playState !== 'running' || item.effect?.getTiming().iterations === Infinity)`,
      );
    });
    const [first, second] = await answer(
      browser,
      `[...document.querySelectorAll('[data-doc-row]')].map((card) => card.dataset.id)
        .filter((id) => id !== 'brief').slice(0, 2)`,
    );
    assert.ok(first && second, 'The board lists at least two materials besides the brief');
    await step('open the full brief', () =>
      open(browser, '[data-action="open-doc"][data-id="brief"]', 'brief'),
    );
    await step('return to the board from the brief', () => backToBoard(browser, 'brief'));
    await step('open a material', () =>
      open(browser, `[data-doc-row=${JSON.stringify(first)}]`, first),
    );
    await step('return to the board from the material', () => backToBoard(browser, first));
    await shot(browser, `${language}-motion-board`);
    await step('open another material', () =>
      open(browser, `[data-doc-row=${JSON.stringify(second)}]`, second),
    );
    await shot(browser, `${language}-motion-document`);
    assert.deepEqual(
      browser.logs.filter((item) => item.level === 'exception'),
      [],
    );
  } catch (error) {
    results.push({ language, status: 'failed', error: String(error) });
    await browser.shot(`${output}/screenshots/${language}-motion-failure.jpg`).catch(() => {});
    throw error;
  } finally {
    await browser.close();
    writeFileSync(`${output}/default-motion.json`, `${JSON.stringify(results, null, 2)}\n`);
  }
}

for (const language of ['zh', 'en']) await runLanguage(language);
