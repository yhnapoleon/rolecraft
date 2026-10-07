/** Controlled-host component checks on v4's Agent DOM/CSS; never production QA. */
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
const bundle = process.env.CODEX_NODE_MODULES;
const { chromium } = (bundle ? createRequire(bundle + '/package.json') : createRequire(import.meta.url))('playwright');
const origin = process.env.W06_VITE_ORIGIN || 'http://127.0.0.1:19460';
const output = process.env.W06_BROWSER_EVIDENCE;
if (!output) throw Error('W06_BROWSER_EVIDENCE is required');
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const checks = [], failures = [];
const context = await browser.newContext({ viewport: { width: 1080, height: 1000 }, reducedMotion: 'reduce' });
const page = await context.newPage();
page.on('pageerror', error => failures.push(String(error)));
async function fixture() {
  await page.goto(origin + '/src/app/styles.css');
  await page.setContent(`<!doctype html><html lang="zh"><head><link rel="stylesheet" href="${origin}/src/app/styles.css"><style>body{margin:0;overflow:auto}main{width:min(368px,100%);margin:16px auto}.test-note{font:12px system-ui;color:var(--ink-3);padding:8px}.agent-panel{width:100%;box-sizing:border-box}</style></head><body><main><p class="test-note">受控 host 部件验证 · 非正式服务</p><div class="rail-pad agent-panel"><section class="agent-conn"><div class="conn-row"><p class="agent-name">我的 Agent</p></div><div class="conn-ways"><button id="manual" class="btn small">复制任务包</button><div id="connection"></div></div></section><section class="agent-step"><h3>带回来</h3><textarea id="manual-return" class="textarea">原手动回传草稿</textarea><div id="returns"></div></section><section class="agent-log"><h3 class="mini-title">它做了什么</h3><div id="activity"></div></section></div></main></body></html>`);
  await page.evaluate(async () => {
    const { mountV4AgentSlot } = await import('/src/features/agent-native/v4-slot.ts');
    const ref = { session_id: 's1', kind: 'material', object_id: 'm1', version: 2 };
    const grant = (id, label) => ({ id, agent_label: label, session_id: 's1', executor: { kind: 'external_agent', delegation_id: id }, capabilities: ['read'], expires_at: '2030-10-08T01:00:00Z', revoked: false, effective_status: 'active' });
    const h = window.h = { snapshot: { session: { protocol: 2, sessionId: 's1', workLanguage: 'zh', scenarioHash: 'fixed' }, uiLanguage: 'zh', state: 'active', asOf: { business_seq: 3, workspace_revision: 2, storage_revision: 7 }, currentTask: { session_id: 's1', kind: 'task', object_id: 't1', version: 1 }, currentProduct: null, busy: false, storageError: false, available: Object.fromEntries(['delegations.list', 'delegations.create', 'delegations.revoke', 'timeline', 'work_products.list', 'work_products.adopt'].map(x => [x, true])) }, grants: [grant('d0', '已有 Agent')], products: [{ product_id: 'p1', session_id: 's1', version: 3, author: { kind: 'external_agent' }, executor: { kind: 'external_agent' }, title: '核对记录', purpose: 'investigation', adoption: { status: 'unadopted' }, removed_at: null }], events: [{ id: 'e1', session_id: 's1', type: 'permission_denied', executor: { kind: 'external_agent' }, refs: [], data: { summary: '<img src=x onerror="window.BAD=true">', verification: 'rule_verified' } }, { id: 'e2', session_id: 's1', type: 'model_check', executor: { kind: 'system' }, refs: [ref], data: { semantic_status: 'placeholder' } }], drafts: new Map(), calls: [], queries: [], recoveries: [], retries: [], listeners: new Set(), mode: 'confirmed', manual: 0, notices: [], reads: [], selected: [], rejectList: false, delayList: false };
    const respond = (operation, input) => {
      if (operation === 'delegations.create') h.grants.push({ ...grant('d' + h.calls.length, input.agent_label), capabilities: input.capabilities });
      if (operation === 'delegations.revoke') h.grants.find(x => x.id === input.delegation_id).revoked = true;
      if (operation === 'work_products.adopt') h.products.find(x => x.product_id === input.product_id).adoption.status = 'adopted';
      return { requestId: 'r' + h.calls.length, status: 'confirmed', result: { token: 'TOKEN_DO_NOT_COPY', secret: 'raw-host-only' } };
    };
    h.host = { snapshot: () => h.snapshot, subscribe: fn => { h.listeners.add(fn); return () => h.listeners.delete(fn); },
      query: async operation => { h.queries.push(operation); if (operation === 'delegations.list') { if (h.rejectList) throw Error('unavailable'); if (h.delayList) return await new Promise(resolve => h.resolveList = () => resolve({ items: h.grants })); return { items: structuredClone(h.grants) }; } return operation === 'timeline' ? { events: h.events } : { items: structuredClone(h.products), next_cursor: null }; },
      command: async (operation, input) => { h.calls.push({ operation, input: structuredClone(input) }); if (h.mode === 'throw') throw Error('unknown dispatch'); if (h.mode === 'hold') return await new Promise(resolve => h.resolve = () => resolve(respond(operation, input))); return h.mode === 'confirmed' ? respond(operation, input) : { requestId: 'original-r', status: h.mode, result: {} }; },
      recover: async id => { h.recoveries.push(id); return { requestId: id, status: 'confirmed', result: {} }; },
      retry: async id => { h.retries.push(id); return { requestId: id, status: 'confirmed', result: {} }; },
      draft: (slot, key) => h.drafts.get(slot + key), keepDraft: async (slot, key, value) => { if (h.failDraft) throw Error('storage unavailable'); h.drafts.set(slot + key, structuredClone(value)); }, flushDrafts: async () => {},
      chooseEvidence: async () => [ref], openReference: async ref => { h.reads.push(ref); }, selectTask: () => {}, selectProduct: ref => h.selected.push(ref), announce: text => h.notices.push(text) };
    h.mount = () => h.handle = mountV4AgentSlot({ host: h.host, nodes: { connection: document.querySelector('#connection'), activity: document.querySelector('#activity'), returns: document.querySelector('#returns') } });
    h.emit = () => [...h.listeners].forEach(fn => fn());
    document.querySelector('#manual').onclick = () => h.manual++;
    h.mount();
  });
  await page.waitForSelector('.agent-v4-work-row');
}
async function record(name, fn) { if (process.env.W06_VISUAL_ONLY === '1') return; await fixture(); try { await fn(); checks.push({ name, result: 'pass' }); } catch (e) { checks.push({ name, result: 'fail', error: String(e) }); throw e; } }
async function prepareGrant() { await page.locator('[name=agentName]').fill('我的 Codex'); await page.getByRole('button', { name: '选择材料与作品范围', exact: true }).click(); }
try {
  await record('default read scope, no automatic actions, host controls preserved', async () => {
    assert.equal(await page.evaluate(() => h.calls.length), 0);
    await page.getByRole('button', { name: '复制任务包', exact: true }).click();
    assert.equal(await page.evaluate(() => h.manual), 1); assert.equal(await page.locator('#manual-return').inputValue(), '原手动回传草稿');
    await prepareGrant(); await page.getByRole('button', { name: '创建授权', exact: true }).click();
    await page.waitForFunction(() => h.calls.length === 1 && document.querySelectorAll('.agent-v4-access-row').length === 2);
    const call = await page.evaluate(() => h.calls[0]); assert.equal(call.operation, 'delegations.create'); assert.deepEqual(call.input.capabilities, ['read']); assert.deepEqual(call.input.allowed_objects, ['m1']);
    assert.ok(!('request_id' in call.input) && !('expected_version' in call.input));
    assert.ok(!(await page.locator('body').innerText()).includes('TOKEN_DO_NOT_COPY'));
    assert.ok(!(await page.evaluate(() => JSON.stringify([...h.drafts]))).includes('TOKEN_DO_NOT_COPY'));
  });
  await record('exact version adoption remains distinct from submission', async () => {
    await page.getByRole('button', { name: '采用此版本', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('.agent-v4-work-row').textContent.includes('已采用'));
    assert.deepEqual(await page.evaluate(() => h.calls), [{ operation: 'work_products.adopt', input: { product_id: 'p1', product_version: 3, expected_head: 3, status: 'adopted' } }]);
  });
  await record('revoke is explicit, double click cannot duplicate, state read back', async () => {
    await page.evaluate(() => h.mode = 'hold');
    await page.getByRole('button', { name: '撤销授权', exact: true }).click();
    await page.evaluate(() => document.querySelector('button[data-agent-write="delegations.revoke"]').click());
    assert.equal(await page.evaluate(() => h.calls.length), 1);
    assert.ok(await page.getByRole('button', { name: '撤销授权', exact: true }).isDisabled());
    await page.evaluate(() => h.resolve());
    await page.waitForFunction(() => document.querySelector('.agent-v4-access-row').textContent.includes('已撤销'));
  });
  await record('unknown response survives remount, refresh is read only, recovery uses original key', async () => {
    await page.evaluate(() => h.mode = 'unconfirmed'); await prepareGrant(); await page.getByRole('button', { name: '创建授权', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('.agent-v4-pending').hidden === false);
    await page.getByRole('button', { name: '刷新授权与记录', exact: true }).click();
    await page.evaluate(() => { h.handle.destroy(); h.mount(); });
    await page.getByRole('button', { name: '核对原请求结果', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('.agent-v4-pending').hidden);
    assert.deepEqual(await page.evaluate(() => ({ writes: h.calls.length, recover: h.recoveries, retry: h.retries })), { writes: 1, recover: ['original-r'], retry: [] });
  });
  await record('failed operation retries only after separate user action', async () => {
    await page.evaluate(() => h.mode = 'failed'); await prepareGrant(); await page.getByRole('button', { name: '创建授权', exact: true }).click();
    await page.getByRole('button', { name: '明确重试这次操作', exact: true }).waitFor({ state: 'visible' });
    assert.deepEqual(await page.evaluate(() => h.retries), []);
    await page.getByRole('button', { name: '明确重试这次操作', exact: true }).click();
    assert.deepEqual(await page.evaluate(() => h.retries), ['original-r']);
  });
  await record('draft, input node, focus and caret survive host refresh and UI language change', async () => {
    await page.locator('[name=agentName]').fill('保留中文草稿');
    await page.evaluate(() => { const input = document.querySelector('[name=agentName]'); input.focus(); input.setSelectionRange(3, 3); h.inputBefore = input; h.snapshot.uiLanguage = 'en'; h.emit(); });
    assert.deepEqual(await page.evaluate(() => { const i = document.querySelector('[name=agentName]'); return { same: i === h.inputBefore, focus: i === document.activeElement, caret: i.selectionStart, value: i.value, work: h.snapshot.session.workLanguage }; }), { same: true, focus: true, caret: 3, value: '保留中文草稿', work: 'zh' });
    assert.equal(await page.getByRole('button', { name: 'Create access', exact: true }).count(), 1);
  });
  await record('session switch destroys slot and ignores late public response', async () => {
    await page.evaluate(() => { h.delayList = true; h.snapshot.asOf.business_seq++; h.emit(); });
    await page.waitForFunction(() => !!h.resolveList);
    await page.evaluate(() => { h.snapshot.session.sessionId = 's2'; h.emit(); h.resolveList(); });
    await page.waitForTimeout(50);
    assert.equal(await page.locator('.agent-v4-slot').count(), 0); assert.equal(await page.evaluate(() => h.listeners.size), 0); assert.equal(await page.evaluate(() => h.calls.length), 0);
  });
  await record('unverifiable connection never stays active, untrusted text never becomes HTML', async () => {
    assert.equal(await page.locator('#activity img').count(), 0); assert.equal(await page.evaluate(() => window.BAD), undefined);
    assert.ok((await page.locator('#activity').innerText()).includes('未获授权'));
    assert.ok((await page.locator('#activity').innerText()).includes('等待模型接入'));
    assert.ok((await page.locator('#activity').innerText()).includes('规则核实'));
    await page.evaluate(() => h.rejectList = true); await page.getByRole('button', { name: '刷新授权与记录', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#connection').textContent.includes('无法确认当前授权状态'));
    assert.equal(await page.locator('.agent-v4-access-row').count(), 0);
  });
  await record('throwing dispatch locks future writes and preserves marker across remount', async () => {
    await page.evaluate(() => h.mode = 'throw'); await prepareGrant(); await page.getByRole('button', { name: '创建授权', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#connection').textContent.includes('结果未知'));
    await page.evaluate(() => { h.handle.destroy(); h.mount(); });
    assert.ok(await page.getByRole('button', { name: '创建授权', exact: true }).isDisabled());
    assert.equal(await page.evaluate(() => h.calls.length), 1);
  });
  await record('storage failure preserves editable text and blocks actions until saved', async () => {
    await prepareGrant(); await page.evaluate(() => h.failDraft = true);
    await page.locator('[name=agentName]').fill('未保存的名字');
    await page.waitForFunction(() => document.querySelector('#connection').textContent.includes('草稿未保存'));
    assert.equal(await page.locator('[name=agentName]').inputValue(), '未保存的名字');
    assert.ok(await page.locator('[name=agentName]').isEnabled());
    assert.ok(await page.getByRole('button', { name: '创建授权', exact: true }).isDisabled());
    await page.evaluate(() => h.failDraft = false); await page.locator('[name=agentName]').fill('已保留的名字');
    await page.waitForFunction(() => document.querySelector('#connection').textContent.includes('草稿已保存'));
    assert.ok(await page.getByRole('button', { name: '创建授权', exact: true }).isEnabled());
  });
  await record('unavailable operations cannot dispatch and legacy manual flow remains available', async () => {
    await page.evaluate(() => { h.snapshot.available = {}; h.emit(); });
    assert.ok(await page.getByRole('button', { name: '创建授权', exact: true }).isDisabled());
    await page.getByRole('button', { name: '复制任务包', exact: true }).click(); assert.equal(await page.evaluate(() => h.manual), 1);
    assert.equal(await page.evaluate(() => h.calls.length), 0);
  });
  await fixture();
  await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'manual');
  for (let i = 0; i < 12 && !(await page.evaluate(() => document.activeElement.getAttribute('name') === 'agentName')); i++) await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement.getAttribute('name')), 'agentName');
  await page.keyboard.type('Keyboard Agent');
  await page.keyboard.press('Tab'); await page.keyboard.press('Space');
  await page.keyboard.press('Tab'); await page.keyboard.press('Space');
  for (let i = 0; i < 8 && !(await page.evaluate(() => document.activeElement.textContent === '创建授权')); i++) await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement.textContent), '创建授权');
  assert.notEqual(await page.evaluate(() => getComputedStyle(document.activeElement).outlineStyle), 'none');
  await page.keyboard.press('Enter');
  await page.waitForFunction(() => h.calls.length === 1);
  assert.deepEqual(await page.evaluate(() => h.calls[0].input.capabilities), ['read', 'act']);
  checks.push({ name: 'keyboard-only explicit grant with visible focus', result: 'pass' });
  await fixture();
  for (const [width, theme, language] of [[1080, 'light', 'zh'], [1080, 'dark', 'en'], [390, 'light', 'en'], [390, 'dark', 'zh']]) {
    await page.setViewportSize({ width, height: 1200 });
    await page.emulateMedia({ colorScheme: theme });
    await page.evaluate(({ theme, language }) => { document.documentElement.dataset.theme = theme; h.snapshot.uiLanguage = language; h.emit(); }, { theme, language });
    assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--canvas').trim()), theme === 'dark' ? '#0e0f12' : '#eceef2');
    await page.waitForFunction(expected => getComputedStyle(document.querySelector('.agent-v4-slot')).color === expected, theme === 'dark' ? 'rgb(242, 243, 245)' : 'rgb(21, 23, 28)');
    await page.screenshot({ path: `${output}/${width}-${theme}-${language}.png`, fullPage: true });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    checks.push({ name: `layout ${width}/${theme}/${language}`, result: 'pass', boundary: 'controlled host; real v4 CSS, no production integration claim' });
  }
  assert.deepEqual(failures, []);
} finally {
  await fs.writeFile(output + '/browser-results.json', JSON.stringify({ mode: 'controlled_host_component_only', checks, pageErrors: failures, actual_v4_root_qa: false, actual_backend: false }, null, 2));
  await browser.close();
}
console.log(JSON.stringify({ passed: checks.filter(x => x.result === 'pass').length, failed: checks.filter(x => x.result === 'fail').length, evidence: output }));
