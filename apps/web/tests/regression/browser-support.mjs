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
