/** Actual browser DOM, first controlled client then real c7 HTTP/worker boundary. */
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { launch, delay } from '../../../tests/walkthrough/cdp.mjs';
const [base, out] = process.argv.slice(2);
if (!base || !out) throw Error('base URL and evidence directory required');
mkdirSync(out, { recursive: true });
const browser = await launch({ width: 1120, height: 900 });
const checks = [];
const record = (name) => {
  checks.push(name);
  console.log('PASS ' + name);
};
const state = (expr) => browser.ev(expr);
const viewPath = '/src/features/roles-native/test-page.html';
try {
  await browser.goto(base + viewPath);
  assert.equal(await state('document.querySelectorAll(".rc-roles__person").length'), 3);
  record('three colleagues mounted');
  await browser.type('textarea', '35-45人，scope_filter与human_fallback在2026-10-31前怎么做？');
  await browser.send('Input.dispatchKeyEvent', {
    type: 'keyDown',
    key: 'Enter',
    code: 'Enter',
    modifiers: 2,
  });
  await delay(350);
  assert.equal(await state('rolesTest.calls.filter(x=>x[0]==="send").length'), 1);
  assert.equal(await state('document.querySelector("textarea").value'), '');
  assert.match((await browser.text('.rc-roles__conversation'))[0], /scope_filter/);
  record('keyboard submit and real pending projection');
  await state(
    'rolesTest.setView({...rolesTest.view,turns:rolesTest.view.turns.map(t=>({...t,status:"completed",reply:"本地资料参考；需要同事判断的部分等待模型接入。",materials:[{id:"policy",title:"试点准入说明",version:2}]}))})',
  );
  await delay(80);
  assert.equal((await browser.text('.rc-roles__material'))[0], '试点准入说明 · v2');
  await browser.click('.rc-roles__material');
  assert.equal(await state('rolesTest.calls.at(-1)[1].version'), 2);
  record('material title and exact version callback');
  await browser.shot(join(out, 'desktop-light.jpg'));
  await browser.click('[data-role="tech_lead"]');
  await browser.type('textarea', '技术草稿');
  await browser.click('[data-role="business_lead"]');
  await browser.type('textarea', '业务草稿');
  await browser.click('[data-role="tech_lead"]');
  assert.equal(await state('document.querySelector("textarea").value'), '技术草稿');
  record('per-colleague draft retention');
  await state('rolesTest.loseResponse()');
  await browser.submit('form');
  assert.equal(await state('document.querySelector("textarea").value'), '技术草稿');
  assert.equal(await state('document.querySelector("[data-action=send]").disabled'), true);
  await state('rolesTest.remount()');
  await delay(100);
  await browser.click('[data-role="tech_lead"]');
  assert.equal(await state('document.querySelector("textarea").value'), '技术草稿');
  const sends = await state('rolesTest.calls.filter(x=>x[0]==="send").length');
  await browser.click('[data-action="recover"]');
  assert.equal(await state('rolesTest.calls.filter(x=>x[0]==="send").length'), sends);
  assert.equal(await state('document.querySelector("textarea").value'), '');
  record('response-loss recovery uses original client request without resending');
  await browser.type('textarea', '保留输入');
  await state('rolesTest.failRead(true);rolesTest.refresh()');
  assert.equal(await state('document.querySelector("textarea").value'), '保留输入');
  assert.equal(await state('document.querySelector("[data-action=send]").disabled'), true);
  assert.equal(await state('document.body.textContent.includes("PRIVATE_DIAGNOSTIC")'), false);
  await state('rolesTest.failRead(false);rolesTest.refresh()');
  record('read failure retains input and hides raw diagnostics');
  await state('rolesTest.holdSend()');
  await browser.submit('form');
  await browser.type('textarea', '发送后继续编辑');
  await state('rolesTest.release()');
  await delay(80);
  assert.equal(await state('document.querySelector("textarea").value'), '发送后继续编辑');
  record('in-flight edits survive acknowledgement');
  await state(
    'rolesTest.setView({...rolesTest.view,turns:[{id:"failed",roleId:"tech_lead",question:"原失败问题",status:"failed",canRetry:true},{id:"stale",roleId:"tech_lead",question:"资料已变化",status:"needs_context",canRefresh:true}]})',
  );
  await delay(80);
  await browser.click('[data-action="retry"]');
  await browser.click('[data-action="refresh-context"]');
  assert.deepEqual(await state('rolesTest.calls.filter(x=>["retry","refresh"].includes(x[0]))'), [
    ['retry', 'failed'],
    ['refresh', 'stale'],
  ]);
  record('failed and needs-context explicit actions');
  await state(
    'rolesTest.setView({...rolesTest.view,turns:[{id:"escaped",roleId:"tech_lead",question:"<img src=x onerror=window.bad=1>",status:"completed",reply:"<script>window.bad=1</script>",materials:[{id:"never-render-this-id",title:"<b>公开材料</b>",version:3}]}]})',
  );
  await delay(80);
  assert.equal(
    await state('document.querySelectorAll(".rc-roles img,.rc-roles script,.rc-roles b").length'),
    0,
  );
  assert.equal(
    await state('document.querySelector(".rc-roles").textContent.includes("never-render-this-id")'),
    false,
  );
  record('text and material titles are escaped without exposing IDs');
  await state('rolesTest.locale("en")');
  assert.match((await browser.text('.rc-roles__language'))[0], /中文/);
  assert.match((await browser.text('.rc-roles__conversation'))[0], /公开材料/);
  record('interface language does not translate work or history');
  await browser.send('Emulation.setDeviceMetricsOverride', {
    width: 390,
    height: 844,
    deviceScaleFactor: 2,
    mobile: true,
  });
  await browser.shot(join(out, 'mobile-light.jpg'));
  assert.equal(await state('document.documentElement.scrollWidth<=innerWidth'), true);
  record('390px no horizontal overflow');
  await browser.send('Emulation.setEmulatedMedia', {
    features: [
      { name: 'prefers-color-scheme', value: 'dark' },
      { name: 'prefers-reduced-motion', value: 'reduce' },
    ],
  });
  await browser.shot(join(out, 'mobile-dark-reduced.jpg'));
  record('dark and reduced-motion render');
  await state('rolesTest.destroy()');
  assert.equal(await state('document.querySelectorAll(".rc-roles").length'), 0);
  await state('rolesTest.locale("zh");rolesTest.setView({...rolesTest.view})');
  assert.equal(await state('document.querySelectorAll(".rc-roles").length'), 0);
  record('destroy removes DOM and subscriptions');
  await browser.goto(base + viewPath + '?mode=http');
  for (let i = 0; i < 50; i++) {
    if (await state('!!window.rolesHttp?.ready')) break;
    await delay(100);
  }
  assert.equal(await state('!!window.rolesHttp?.ready'), true);
  await browser.click('[data-role="tech_lead"]');
  const original = '35-45人，scope_filter和human_fallback于2026-10-31前怎么做？';
  await browser.type('textarea', original);
  await state('rolesTest.loseResponse()');
  await browser.submit('form');
  assert.equal(await state('document.querySelector("textarea").value'), original);
  await browser.click('[data-action="recover"]');
  await browser.click('[data-action="reload"]');
  assert.equal(await state('rolesHttp.requestCount()'), 1);
  assert.equal(await state('rolesTest.calls.filter(x=>x[0]==="send").length'), 1);
  assert.match((await browser.text('.rc-roles__conversation'))[0], /本地生成端口尚未接入/);
  assert.equal(await state('document.querySelectorAll(".rc-roles__reply").length'), 0);
  assert.equal((await state('rolesHttp.publicEvidence()'))[0].question, original);
  await browser.shot(join(out, 'real-http-unavailable.jpg'));
  record('actual HTTP/worker failure preserves original question and request recovery');
  const errors = browser.logs.filter((x) => !x.text.includes('favicon.ico'));
  assert.deepEqual(errors, []);
  writeFileSync(
    join(out, 'browser-results.json'),
    JSON.stringify(
      {
        checks,
        scope:
          'Controlled native component plus actual c7 HTTP/independent worker unavailable-port path; no real model or production successful role chain',
        httpEvidence: await state('rolesHttp.publicEvidence()'),
        consoleErrors: errors,
      },
      null,
      2,
    ),
  );
} finally {
  await browser.close();
}
