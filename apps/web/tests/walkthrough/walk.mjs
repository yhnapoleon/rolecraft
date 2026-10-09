// Full walkthrough of the workspace. Usage: CHROME_BIN=… node walk.mjs <width> <height> <lang: zh|en|auto-zh|auto-en> [dark]
import { launch, delay } from './cdp.mjs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { mkdirSync } from 'node:fs';
const OUT = process.env.OUT || join(tmpdir(), 'rolecraft-walk');
mkdirSync(OUT, { recursive: true });
const W = Number(process.argv[2] || 1440),
  H = Number(process.argv[3] || 900),
  LANG = process.argv[4] || 'zh',
  DARK = process.argv.includes('dark');
const tag = (W < 500 ? 'm' : W < 1100 ? 't' : 'd') + '-' + LANG + (DARK ? '-dark' : '');
const BASE = process.env.BASE || 'http://127.0.0.1:8510/';
const b = await launch({ width: W, height: H, dark: DARK, mobile: W < 500 });
const ua = (await b.send('Browser.getVersion')).userAgent;
await b.send('Emulation.setUserAgentOverride', {
  userAgent: ua,
  acceptLanguage: LANG.endsWith('zh') ? 'zh-CN,zh' : 'en-US,en',
});
const results = [];
const step = async (name, fn) => {
  try {
    await fn();
    results.push(['OK', name]);
  } catch (e) {
    results.push(['FAIL', name, e.message.slice(0, 160)]);
  }
};
const waitFor = async (expr, ms = 20000) => {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    try {
      if (await b.ev(expr)) return true;
    } catch (_) {}
    await delay(300);
  }
  throw new Error('timeout ' + expr.slice(0, 80));
};
const overflow = () =>
  b.ev('document.documentElement.scrollWidth - document.documentElement.clientWidth');
const SQUEEZE = `(() => { const out = []; for (const el of document.querySelectorAll('body *')) { if (el.children.length || !el.textContent.trim() || el.closest('[hidden],.sr-only,dialog:not([open])')) continue; const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue; const fs = parseFloat(getComputedStyle(el).fontSize); const len = el.textContent.trim().length; if (len > 5 && r.width < fs * 2.6 && r.height > fs * 3) out.push(el.className + ':' + el.textContent.trim().slice(0, 12)); } return out.slice(0, 6); })()`;
const shot = async (n, full) => {
  const sq = await b.ev(SQUEEZE);
  if (sq && sq.length) results.push(['WARN', 'squeezed at ' + n, JSON.stringify(sq)]);
  return b.shot(`${OUT}/${tag}-${n}.jpg`, full);
};
const en = LANG.includes('en');
const openRail = async () => {
  if (W < 1280) await b.click('[data-action="open-rail"]');
};
const closeRail = async () => {
  if (W < 1280) await b.ev(`document.querySelector('.rail-close')?.click()`);
  await delay(300);
};
try {
  await b.goto(BASE + '#/');
  await b.ev(
    `localStorage.clear(); ${LANG.startsWith('auto') ? '' : `localStorage.setItem('rolecraft.locale', '${LANG}');`}`,
  );
  await b.goto(BASE + '#/');
  await delay(900);
  await shot('01-jobs', true);
  await step('open career', () => b.click('[data-action="open-career"]'));
  await delay(500);
  await shot('02-entry', true);
  await step('triage needs first', () => b.select('select[data-change="triage"]', 'first', 0));
  await step('take case', () => b.click('.case-hero [data-action="take-case"]'));
  await step('board', () =>
    waitFor(`!!document.querySelector('.board') && location.hash === '#/work'`),
  );
  await delay(1500);
  results.push(['INFO', 'overflow board', await overflow()]);
  await shot('03-board');
  await step('about sheet', async () => {
    await b.click('[data-menu="more"]');
    await b.click('[data-action="about"]');
  });
  await delay(500);
  await shot('03b-about');
  await b.ev(`document.querySelector('#sheet')?.close()`);
  await delay(300);
  await step('open brief doc from board', () => b.click('.doc-card[data-id="brief"]'));
  await step('doc page', () => waitFor(`location.hash.startsWith('#/doc/')`));
  await delay(800);
  await shot('04-doc-page');
  await step('back to board', () => b.click('[data-action="to-board"]'));
  await step('open bench', () => b.click('.product-bar [data-action="open-bench"]'));
  await delay(500);
  await step('settings', () => b.click('.console-tools [data-action="config"]'));
  await step('save settings', () => b.submit('[data-form="config"]'));
  await step('settings saved', () => waitFor(`!document.querySelector('#sheet').open`, 10000));
  await step('back to board 2', () => b.click('[data-action="to-board"]'));
  await step('open first task', () => b.click('.card-open', 0));
  await step('task route', () => waitFor(`location.hash.startsWith('#/task/')`));
  await delay(900);
  await shot('05-task-start');
  await b.type(
    '#new-body',
    en
      ? '## What I think\nStart with 20 office staff, FAQ only, daily index.\n\n## Open questions\n- How often does travel policy change?\n- Who handles hand-offs?'
      : '## 我的判断\n先给 20 名行政同事开放，只上办公 FAQ，每日索引。\n\n## 还不确定\n- 差旅政策多久变一次？\n- 转人工由谁接？',
  );
  await step('work created', () => waitFor(`!!document.getElementById('editor-body')`, 5000));
  await delay(1200);
  await step('purpose decision', () => b.select('[data-edit="purpose"]', '试点决定'));
  await delay(900);
  await shot('06-task-work');
  await step('test it', () => b.click('.action-bar [data-type="bench"]'));
  await delay(500);
  await b.type('#lab-q', '差旅住宿报销上限是多少？');
  await step('run test', () => b.submit('[data-form="run-test"]'));
  await step('answer', () => waitFor(`document.querySelectorAll('.run').length > 0`, 15000));
  await delay(1500);
  await shot('07-task-bench');
  await step('ask Mei from rail', async () => {
    await openRail();
    await b.click('.rail-tabs [data-tab="team"]');
    await b.click('.person[data-role="business"]');
  });
  await b.type('#chat-input', en ? 'Who are the first users, really?' : '首批用户到底是谁？');
  await step('send', () => b.submit('[data-form="chat"]'));
  await step('reply', () =>
    waitFor(
      `[...document.querySelectorAll('.thread .msg.them')].filter(m => !m.classList.contains('is-typing')).length > 0`,
      30000,
    ),
  );
  await delay(700);
  await shot('08-task-chat');
  await closeRail();
  await step('open the work again', () => b.click('.ol-row[data-type="work"]'));
  await step('request review', () => b.click('.action-bar [data-action="request-review"]'));
  await delay(800);
  await shot('09-task-feedback');
  await step('activity tab', async () => {
    await openRail();
    await b.click('.rail-tabs [data-tab="activity"]');
  });
  await delay(400);
  await shot('10-task-activity');
  await step('agent tab', () => b.click('.rail-tabs [data-tab="agent"]'));
  await delay(400);
  await shot('11-task-agent');
  await closeRail();
  await step('back to board 3', () => b.click('[data-action="to-board"]'));
  await delay(900);
  await shot('12-board-after');
  const world = await b.ev(`!!document.querySelector('.world-event')`);
  results.push(['INFO', 'world event', world]);
  if (world) {
    await step('see change', () => b.click('.world-event [data-action="open-doc"]'));
    await delay(1600);
    await shot('13-policy-diff');
    await step('back to board 4', () => b.click('[data-action="to-board"]'));
  }
  await step('advice', async () => {
    await b.click('[data-menu="rank"]');
    await b.click('[data-action="show-advice"][data-role="technical"]');
  });
  await delay(500);
  await shot('14-advice');
  await step('apply advice', () => b.click('[data-action="apply-advice"]'));
  await delay(700);
  await shot('15-board-reordered');
  await step('deliver', () => b.click('.ws-toolbar [data-action="submit"]'));
  await delay(600);
  await b.ev(
    `(() => { const set = (n, v) => { const el = document.querySelector('#live-deliver [name="' + n + '"]'); el.value = v; el.dispatchEvent(new Event('input', {bubbles: true})); }; set('goal', '${en ? 'Serve 20 office staff with FAQ answers first.' : '先服务 20 名行政同事，回答办公 FAQ。'}'); set('owner', 'PM'); set('metrics', '${en ? 'Resolved rate and wrong policy answers, weekly.' : '有效解答率与错误政策回答数，每周统计。'}'); })()`,
  );
  await step('save deliverable', () => b.click('[data-action="live-save"]'));
  await step('saved', () =>
    waitFor(`!document.querySelector('[data-action="live-submit"]')?.disabled`, 10000),
  );
  await step('submit', () => b.click('[data-action="live-submit"]'));
  await step('review', () => waitFor(`document.querySelectorAll('.criterion').length > 0`, 40000));
  await delay(1200);
  await shot('16-review-rules', true);
  await step('coach tab', () => b.click('[data-action="review-tab"][data-tab="coach"]'));
  await delay(600);
  await shot('17-review-coach', true);
  results.push(['INFO', 'overflow end', await overflow()]);
} catch (e) {
  results.push(['FAIL', 'script', e.message.slice(0, 200)]);
} finally {
  results.push(['LOGS', JSON.stringify(b.logs).slice(0, 1500)]);
  console.log(results.map((r) => r.join(' | ')).join('\n'));
  await b.close();
}

process.exitCode = results.some(([status]) => status === 'FAIL') ? 1 : 0;
