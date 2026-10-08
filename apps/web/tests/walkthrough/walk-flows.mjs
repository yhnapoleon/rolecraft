// Secondary flows: over-capacity settings, resource request and approval, world event -> task,
// agent return -> adopt -> log, new task. Usage: CHROME_BIN=… node walk-flows.mjs <zh|en>
import { launch, delay } from './cdp.mjs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { mkdirSync } from 'node:fs';
const OUT = process.env.OUT || join(tmpdir(), 'rolecraft-walk');
mkdirSync(OUT, { recursive: true });
const LANG = process.argv[2] || 'zh'; const en = LANG === 'en';
const BASE = process.env.BASE || 'http://127.0.0.1:8510/';
const b = await launch({ width: 1440, height: 900 });
const results = [];
const step = async (name, fn) => { try { await fn(); results.push(['OK', name]); } catch (e) { results.push(['FAIL', name, e.message.slice(0, 160)]); } };
const waitFor = async (expr, ms = 20000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { try { if (await b.ev(expr)) return true; } catch (_) {} await delay(300); } throw new Error('timeout ' + expr.slice(0, 80)); };
const shot = n => b.shot(`${OUT}/b-${LANG}-${n}.jpg`);
const closeSheet = async () => { await b.ev(`document.querySelector('#sheet')?.open && document.querySelector('#sheet').close()`); await delay(300); };
try {
  await b.goto(BASE + '#/'); await b.ev(`localStorage.clear(); localStorage.setItem('rolecraft.locale', '${LANG}')`);
  await b.goto(BASE + '#/pm'); await delay(900);
  await step('take case', () => b.click('.case-hero [data-action="take-case"]'));
  await step('board', () => waitFor(`!!document.querySelector('.board')`)); await delay(1200);
  await step('settings', () => b.click('.product-bar [data-action="config"]'));
  await b.ev(`(() => { const f = document.querySelector('[data-form="config"]'); f.participants.value = 45; f.participants.dispatchEvent(new Event('input', {bubbles:true})); f.participants.dispatchEvent(new Event('change', {bubbles:true})); })()`);
  await delay(300); await shot('01-settings-over');
  await step('save settings', () => b.submit('[data-form="config"]'));
  await step('saved', () => waitFor(`!document.querySelector('#sheet').open`, 10000)); await delay(600);
  await step('resources', () => b.click('.product-bar [data-action="resources"]'));
  await b.type('#res-form textarea[name="reason"]', en ? 'Extend to 45 staff in HR and admin, who ask most of the repeated questions.' : '扩到 45 名行政与 HR 同事，他们承担了大部分重复咨询。');
  await step('send request', () => b.submit('[data-form="resources"]'));
  await step('pending shown', () => waitFor(`!!document.querySelector('[data-action="live-approval"]')`, 10000));
  await delay(500); await shot('02-request-pending');
  await step('ask Priya', () => b.click('[data-action="live-approval"]'));
  await delay(1800); await shot('03-after-approval');
  results.push(['INFO', 'conditions in sheet', await b.ev(`document.querySelector('.res-now')?.innerText.replace(/\\s+/g, ' ') || ''`)]);
  await closeSheet(); await delay(800);
  results.push(['INFO', 'board conditions', await b.ev(`document.querySelector('.brief-band .conds')?.innerText.replace(/\\s+/g, ' ') || document.querySelector('.conds')?.innerText.replace(/\\s+/g, ' ') || ''`)]);
  await shot('04-board-after-approval');
  const world = await b.ev(`!!document.querySelector('.world-event')`);
  results.push(['INFO', 'world event', world]);
  if (world) { await step('add as task', () => b.click('.world-event [data-action="situation-task"]')); await delay(900); await shot('05-situation-task'); }
  if (!world) await step('open first task', () => b.click('.card-open', 0));
  await step('task route', () => waitFor(`location.hash.startsWith('#/task/')`)); await delay(700);
  await step('agent tab', () => b.click('.rail-tabs [data-tab="agent"]')); await delay(400);
  await b.type('#import-content', en ? '# Draft test set\n\n- What is the hotel limit?\n- Book a meeting room\n- Out of scope: annual leave' : '# 测试集草稿\n\n- 住宿报销上限是多少？\n- 怎么订会议室？\n- 范围外：年假怎么请？');
  await step('preview import', () => b.submit('[data-form="import"]')); await delay(600); await shot('06-import-preview');
  await step('confirm import', () => b.click('[data-action="confirm-import"]'));
  await step('agent work opened', () => waitFor(`!!document.querySelector('.agent-strip')`, 8000)); await delay(800); await shot('07-agent-work');
  await step('adopt', () => b.click('[data-action="adopt"]')); await delay(900);
  await step('agent tab again', () => b.click('.rail-tabs [data-tab="agent"]')); await delay(500); await shot('08-agent-log');
  results.push(['INFO', 'agent log items', await b.ev(`document.querySelectorAll('.agent-log .log:not(.ghost) .log-item').length`)]);
  await step('activity tab', () => b.click('.rail-tabs [data-tab="activity"]')); await delay(400); await shot('09-activity');
  await step('back to board', () => b.click('[data-action="to-board"]')); await delay(700);
  await step('new task', () => b.click('.board [data-action="new-task"]'));
  await b.type('#task-form input[name="title"]', en ? 'Check how often the policy changes' : '问清政策多久变一次');
  await step('add task', () => b.submit('#task-form')); await delay(900); await shot('10-board-new-task');
  results.push(['INFO', 'route + cards after new task', await b.ev(`location.hash + ' ' + document.querySelectorAll('.kanban .card').length`)]);
} catch (e) { results.push(['FAIL', 'script', e.message.slice(0, 200)]); }
finally { results.push(['LOGS', JSON.stringify(b.logs).slice(0, 1200)]); console.log(results.map(r => r.join(' | ')).join('\n')); await b.close(); }

process.exitCode = results.some(([status]) => status === 'FAIL') ? 1 : 0;
