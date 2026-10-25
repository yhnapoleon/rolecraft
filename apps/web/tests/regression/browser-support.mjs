import assert from 'node:assert/strict';
import { delay } from '../walkthrough/cdp.mjs';

export async function waitFor(browser, expression, milliseconds = 15000) {
  const deadline = Date.now() + milliseconds;
  while (Date.now() < deadline) {
    if (await browser.ev(expression)) return;
    await delay(100);
  }
  throw new Error(`Timed out: ${expression}`);
}

export async function clickReady(browser, label, scope = 'button') {
  const query = `(() => {
    const button = [...document.querySelectorAll(${JSON.stringify(scope)})]
      .find(node => node.textContent.trim() === ${JSON.stringify(label)} && node.offsetParent !== null);
    return !!button && !button.disabled;
  })()`;
  await waitFor(browser, query);
  await browser.clickText(label, scope);
}

/** The delivery panel's own button, by its mark: it says what it will submit ("提交第 2 版",
 * "Submit 2 versions"), so scripts do not match its words. Waits until it can be pressed. */
export async function submitDelivery(browser) {
  const button = `document.querySelector('[data-delivery-submit]')`;
  await waitFor(browser, `!!${button} && !${button}.disabled && ${button}.offsetParent !== null`);
  await browser.click('[data-delivery-submit]');
}

/** Follow the new-practice commission and skip the real tour, without changing entry storage.
 * Pointer input also catches an overlay that would prevent a learner from pressing either key. */
export async function acceptEntryStory(browser) {
  await waitFor(
    browser,
    `location.hash === '#/work' && !!document.querySelector('.rc-entry-story [data-action="walk-accept"]')`,
  );
  assert.equal(
    await browser.ev(`(() => {
    const entry = document.querySelector('.rc-entry-story');
    return entry.getBoundingClientRect().height > 0 && entry.textContent.includes('Grace')
      && !document.querySelector('.kanban .card-open') && !document.querySelector('.rc-tour');
  })()`),
    true,
    'A new practice shows Grace’s commission before the board or tour',
  );
  const press = async (selector) => {
    await waitFor(
      browser,
      `(() => {
      const button = document.querySelector(${JSON.stringify(selector)});
      return !!button && !button.disabled && button.getBoundingClientRect().height > 0;
    })()`,
    );
    await browser.ev(
      `document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block: 'center'})`,
    );
    // The tour is positioned on the next animation frame. A DOM-presence wait alone can
    // capture its old coordinates; wait for actionability, as a normal browser driver does.
    await waitFor(
      browser,
      `new Promise(resolve => {
      const button = document.querySelector(${JSON.stringify(selector)});
      const before = button.getBoundingClientRect();
      requestAnimationFrame(() => requestAnimationFrame(() => {
        const after = button.getBoundingClientRect();
        const x = after.x + after.width / 2, y = after.y + after.height / 2;
        const animations = [...button.getAnimations(), ...(button.closest('.rc-tour')?.getAnimations() || [])];
        resolve(button.isConnected && !button.disabled
          && Math.abs(before.x - after.x) < 0.5 && Math.abs(before.y - after.y) < 0.5
          && animations.every(a => a.playState !== 'running')
          && button.contains(document.elementFromPoint(x, y)));
      }));
    })`,
    );
    const point = await browser.ev(`(() => {
      const r = document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();
      return {x: r.x + r.width / 2, y: r.y + r.height / 2};
    })()`);
    await browser.send('Input.dispatchMouseEvent', { type: 'mouseMoved', ...point });
    await browser.send('Input.dispatchMouseEvent', {
      type: 'mousePressed',
      ...point,
      button: 'left',
      clickCount: 1,
    });
    await browser.send('Input.dispatchMouseEvent', {
      type: 'mouseReleased',
      ...point,
      button: 'left',
      clickCount: 1,
    });
  };
  await press('.rc-entry-story [data-action="walk-accept"]');
  await waitFor(browser, `!!document.querySelector('.rc-tour [data-tour="skip"]')`);
  assert.equal(
    await browser.ev(
      `!document.querySelector('.rc-entry-story') && !!document.querySelector('.rc-tour [data-tour="next"]')`,
    ),
    true,
    'Start opens the tour with both skip and next controls',
  );
  await press('.rc-tour [data-tour="skip"]');
  await waitFor(
    browser,
    `!document.querySelector('.rc-tour') && !document.querySelector('.rc-entry-story') && !!document.querySelector('.kanban .card-open')`,
  );
  assert.equal(
    await browser.ev(`(() => {
    const current = document.querySelector('.kanban [data-handed]')?.closest('[data-task-id]')?.querySelector('.card-open');
    return !!current && document.activeElement === current;
  })()`),
    true,
    'Skipping the tour focuses the current item handed over by Grace',
  );
}
