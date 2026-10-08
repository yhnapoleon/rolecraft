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
