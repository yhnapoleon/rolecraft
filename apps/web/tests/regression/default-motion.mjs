/** Default motion on the normal v4 entry, Chinese then English.
 *
 * Every other browser flow emulates prefers-reduced-motion, which skips the shared document
 * flight. Here the board opens the full brief, returns, opens one material, returns and opens
 * another while the flight layer runs. After every click the page must answer an evaluation
 * within a short budget, the flight layer must carry no v4 mount marker, the flight must land,
 * and the page must show the document that was opened or the board it returned to.
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

/** Click, then report what the flight layer looks like before any later task runs. */
async function clickIntoFlight(browser, selector) {
  const flight = await answer(
    browser,
    `(() => {
      const target = document.querySelector(${JSON.stringify(selector)});
      if (!target) return null;
      target.scrollIntoView({ block: 'center' });
      target.click();
      const layer = document.querySelector('.document-flight');
      return {
        started: !!layer,
        markers: layer
          ? [layer, ...layer.querySelectorAll('*')].flatMap((node) =>
              node.getAttributeNames().filter((name) => name.startsWith('data-v4-')),
            )
          : [],
      };
    })()`,
  );
  assert.ok(flight, `Not found: ${selector}`);
  assert.equal(flight.started, true, `Default motion did not start the document flight`);
  assert.deepEqual(flight.markers, [], 'The flight layer copies v4 mount markers');
}

async function land(browser) {
  const deadline = Date.now() + LANDING_MS;
  while (Date.now() < deadline) {
    const landed = await answer(
      browser,
      `!document.querySelector('.document-flight') &&
        !document.documentElement.classList.contains('document-in-flight')`,
    );
    if (landed) return;
    await delay(100);
  }
  throw new Error(`The document flight did not land within ${LANDING_MS} ms`);
}

async function boardTitle(browser, id) {
  const title = await answer(
    browser,
    `document.querySelector('.doc-card[data-id=${JSON.stringify(id)}] .dc-title')
      ?.textContent.trim()`,
  );
  assert.ok(title, `The board has no card for ${id}`);
  return title;
}

async function open(browser, selector, id) {
  const title = await boardTitle(browser, id);
  await clickIntoFlight(browser, selector);
  await land(browser);
  assert.equal(await answer(browser, 'location.hash'), `#/doc/${encodeURIComponent(id)}`);
  assert.equal(
    await answer(
      browser,
      `document.querySelector('.document[data-document-id=${JSON.stringify(id)}] .doc-title')
        ?.textContent.trim()`,
    ),
    title,
  );
}

async function backToBoard(browser, id) {
  await clickIntoFlight(browser, '[data-action="to-board"]');
  await land(browser);
  assert.equal(await answer(browser, 'location.hash'), '#/work');
  assert.ok(await boardTitle(browser, id));
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
        `location.hash === '#/work' && document.querySelectorAll('.doc-card').length > 2`,
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
      `[...document.querySelectorAll('.doc-card')].map((card) => card.dataset.id)
        .filter((id) => id !== 'brief').slice(0, 2)`,
    );
    assert.ok(first && second, 'The board lists at least two materials besides the brief');
    await step('open the full brief', () =>
      open(browser, '.band-actions [data-action="open-doc"][data-id="brief"]', 'brief'),
    );
    await step('return to the board from the brief', () => backToBoard(browser, 'brief'));
    await step('open a material', () =>
      open(browser, `.doc-card[data-id=${JSON.stringify(first)}]`, first),
    );
    await step('return to the board from the material', () => backToBoard(browser, first));
    await shot(browser, `${language}-motion-board`);
    await step('open another material', () =>
      open(browser, `.doc-card[data-id=${JSON.stringify(second)}]`, second),
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
