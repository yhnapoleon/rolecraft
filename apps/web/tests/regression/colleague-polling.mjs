/** Real HTTP/worker regression: a colleague's reply to shared work settles while the page is hidden.
 * Chrome reports a page hidden when the learner switches tabs or another window covers it; the
 * pending reply must still be read to its terminal status, without resending the turn, and be
 * shown on return. A hidden page skips rendering, so only the data is checked while hidden.
 * Standalone: CHROME_BIN=<browser> BASE=<web> OUT=<directory> node tests/regression/colleague-polling.mjs
 */
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { launch } from '../walkthrough/cdp.mjs';
import { acceptEntryStory, waitFor } from './browser-support.mjs';

export async function replyArrivesWhileHidden(base, output, language) {
  const target = `${output}/colleague-polling`;
  mkdirSync(target, { recursive: true });
  const browser = await launch({ width: 1440, height: 1100, reduced: true });
  const text = (zh, en) => (language === 'zh' ? zh : en);
  const shot = (name) => browser.shot(`${target}/${language}-${name}.jpg`);
  let cover;
  try {
    await browser.goto(base);
    await browser.ev(`localStorage.clear();
      localStorage.setItem('rolecraft.locale', ${JSON.stringify(language)});`);
    await browser.goto(base);
    await waitFor(browser, `!!document.querySelector('[data-action="open-career"]')`);
    await browser.click('[data-action="open-career"]');
    await browser.click('.case-hero [data-action="take-case"]');
    await acceptEntryStory(browser);
    await waitFor(browser, `location.hash === '#/work' && !!document.querySelector('.card-open')`);
    await browser.click('.card-open');
    await browser.type('#new-title', text('后台分享回归', 'Background sharing regression'));
    await browser.type(
      '#new-body',
      text('先核实范围，保留人工兜底。', 'Verify scope and keep human fallback.'),
    );
    await browser.clickText(text('保存为作品', 'Save as work'));
    await waitFor(browser, `!!document.querySelector('.ol-row[data-type="work"]')`);
    await browser.click('.ol-row[data-type="work"]');
    await waitFor(browser, `!!document.querySelector('#editor-body')`);
    // Resource timing sees every read, including the gateway's own fetch; never record bodies.
    await browser.ev(`(() => {
      performance.setResourceTimingBufferSize(10000);
      window.colleaguePollingSince = performance.now();
      document.addEventListener('visibilitychange', () => {
        if (document.hidden) window.colleaguePollingHiddenAt ??= performance.now();
      });
    })()`);
    const journal = `window.PracticeLive.v4Host(
      window.PracticeLive.engine.getAttempt(window.PracticeLive.state))
      .pendingRequests({readOnly:true}).length`;
    // A real second tab hides the workbench, as switching tabs does. chrome-headless-shell never
    // reports a page hidden, so there the page's visibility is overridden to the same effect.
    cover = await browser.send('Target.createTarget', { url: 'about:blank' });
    await browser.send('Target.activateTarget', { targetId: cover.targetId });
    let emulated = false;
    try {
      await waitFor(browser, `document.visibilityState === 'hidden'`, 3000);
    } catch {
      emulated = true;
      await browser.ev(`(() => {
        Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
        Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
        document.dispatchEvent(new Event('visibilitychange'));
      })()`);
    }
    await browser.clickText(text('分享已保存的这版', 'Share this saved version'));
    await waitFor(browser, `${journal} > 0`);
    // Leaving for the board redraws the workspace while the reply is still pending.
    await browser.click('[data-action="to-board"]');
    await waitFor(browser, `location.hash === '#/work'`);
    // Unchanged pre-fix, nothing reads the request while hidden and it never settles here.
    await waitFor(browser, `${journal} === 0`);
    const readTrace = `(() => {
      const since = window.colleaguePollingSince;
      const entries = performance.getEntriesByType('resource')
        .filter(e => e.startTime >= since)
        .map(e => ({ path: new URL(e.name).pathname, start: e.startTime, end: e.responseEnd }));
      return {
        hiddenAt: window.colleaguePollingHiddenAt,
        turns: entries.filter(e => e.path.endsWith('/turns')).length,
        reads: entries.filter(e => e.path.includes('/requests/')),
      };
    })()`;
    const trace = await browser.ev(readTrace);
    assert.equal(trace.turns, 1, 'Redrawing the workspace never resends the turn');
    assert.ok(trace.reads.length > 0, 'The pending reply was read');
    assert.ok(
      trace.reads.every((read) => read.start >= trace.hiddenAt),
      'Every progress read ran while hidden',
    );
    const sorted = [...trace.reads].sort((a, b) => a.start - b.start);
    for (let i = 1; i < sorted.length; i++)
      if (sorted[i].path === sorted[i - 1].path)
        assert.ok(sorted[i].start >= sorted[i - 1].end, 'One in-flight read per request');
    // Back on the page, the settled reply is shown without another turn.
    await browser.send('Target.closeTarget', { targetId: cover.targetId });
    cover = undefined;
    await browser.send('Page.bringToFront');
    if (emulated)
      await browser.ev(`(() => {
        delete document.hidden;
        delete document.visibilityState;
        document.dispatchEvent(new Event('visibilitychange'));
      })()`);
    await waitFor(browser, `document.visibilityState === 'visible'`);
    // The rail still holds Grace's conversation; rendering catches up once the page is shown.
    await waitFor(browser, `!!document.querySelector('.rc-roles__reply')`);
    assert.equal((await browser.ev(readTrace)).turns, 1, 'Returning never resends the turn');
    assert.deepEqual(
      browser.logs.filter((entry) => entry.level === 'exception'),
      [],
    );
    await shot('reply');
    return emulated ? 'emulated hidden' : 'hidden by a second tab';
  } catch (error) {
    await shot('failure');
    throw error;
  } finally {
    writeFileSync(
      `${target}/${language}-trace.json`,
      JSON.stringify(
        await browser.ev(`({
          visibility: document.visibilityState,
          hiddenAt: window.colleaguePollingHiddenAt,
          reads: performance.getEntriesByType('resource')
            .filter(e => e.name.includes('/requests/') || e.name.endsWith('/turns'))
            .map(e => ({ path: new URL(e.name).pathname, start: e.startTime, end: e.responseEnd })),
        })`),
        null,
        2,
      ),
    );
    if (cover) await browser.send('Target.closeTarget', { targetId: cover.targetId });
    await browser.close();
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  assert.ok(process.env.BASE && process.env.OUT, 'BASE and OUT are required');
  for (const language of (process.env.LANGS || 'zh,en').split(',')) {
    const how = await replyArrivesWhileHidden(process.env.BASE, process.env.OUT, language);
    console.log(`PASS ${language}: colleague reply settles while the page is hidden (${how})`);
  }
}
