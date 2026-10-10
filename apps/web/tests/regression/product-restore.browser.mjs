/** Recover a removed manual return through the normal bilingual v4 dialog. */
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL, fileURLToPath } from 'node:url';

const root = process.env.WEB_ROOT ?? fileURLToPath(new URL('../../', import.meta.url));
assert.ok(root && process.env.BASE && process.env.OUT);
const { waitFor, clickReady } = await import(
  pathToFileURL(`${root}/tests/regression/browser-support.mjs`)
);
const { launch, delay } = await import(pathToFileURL(`${root}/tests/walkthrough/cdp.mjs`));
const results = [];
const query = (browser, operation, input = {}) =>
  browser.ev(`(() => {
  const live = window.PracticeLive;
  return live.v4Host(live.engine.getAttempt(live.state)).query(${JSON.stringify(operation)}, ${JSON.stringify(input)});
})()`);

async function run(language, adoptWork, fault = null) {
  const caseId = `D01-${language}-${fault ?? (adoptWork ? 'shared' : 'unadopted')}`;
  const browser = await launch({ width: 1440, height: 1100, reduced: true });
  const text = (zh, en) => (language === 'en' ? en : zh);
  let checkpoint = 'normal entry';
  try {
    if (fault)
      await browser.send('Page.addScriptToEvaluateOnNewDocument', {
        source: `(() => {
      const send = window.fetch.bind(window);
      window.restoreProbe = { fault: '', writes: 0, readFailures: 0 };
      window.fetch = async (input, options) => {
        const probe = window.restoreProbe;
        const url = typeof input === 'string' ? input : input.url;
        const body = typeof options?.body === 'string' ? JSON.parse(options.body) : null;
        const restoring = url.includes('/work-products/') && url.endsWith('/versions') && body?.payload?.removed === false;
        if (probe.fault === 'read' && url.includes('/work-products?') && !body) {
          probe.fault = '';
          probe.readFailures++;
          return new Response(JSON.stringify({ error: 'private diagnostic must not be shown', code: 'workspace_read_failed' }), { status: 503 });
        }
        if (!restoring) return send(input, options);
        probe.writes++;
        const injected = probe.fault;
        probe.fault = '';
        if (injected === 'rejected') {
          return new Response(JSON.stringify({ error: 'controlled version conflict', code: 'version_conflict' }), { status: 409 });
        }
        const response = await send(input, options);
        if (injected === 'lost') {
          await response.text();
          throw new TypeError('Controlled response loss after the real restoration');
        }
        return response;
      };
    })()`,
      });
    await browser.goto(process.env.BASE);
    await browser.ev(
      `localStorage.clear(); localStorage.setItem('rolecraft.locale', ${JSON.stringify(language)});`,
    );
    await browser.goto(process.env.BASE);
    await waitFor(browser, `!!document.querySelector('[data-action="open-career"]')`);
    await browser.click('[data-action="open-career"]');
    await browser.click('.case-hero [data-action="take-case"]');
    await waitFor(browser, `!!document.querySelector('.card-open')`);
    await browser.click('.card-open');
    await browser.click('.rail-tabs [data-tab="agent"]');
    await waitFor(browser, `!!document.querySelector('[data-action="download-package"]')`);
    const directory = `${process.env.OUT}/downloads/${caseId}`;
    mkdirSync(directory, { recursive: true });
    await browser.send('Browser.setDownloadBehavior', {
      behavior: 'allow',
      downloadPath: directory,
    });
    await browser.click('[data-action="download-package"]');
    const path = `${directory}/practice-task.json`;
    for (let attempt = 0; attempt < 100 && !existsSync(path); attempt++) await delay(100);
    assert.ok(existsSync(path));
    const pack = JSON.parse(readFileSync(path, 'utf8'));
    const title = text('外部助手的待检查建议', 'External assistant suggestion to check');
    const returned = JSON.stringify({
      schemaVersion: 1,
      returnId: `removed-return-${language}`,
      requestId: pack.requestId,
      artifact: {
        kind: 'text',
        title,
        purpose: '自由作品',
        body: text('建议先核实人工接管范围。', 'Check the scope of human handoff first.'),
      },
    });
    const preview = async (content = returned) => {
      await browser.type('#import-content', content);
      await browser.submit('#import-form');
      await waitFor(browser, `!!document.querySelector('#sheet [data-action="confirm-import"]')`);
    };
    const before = (await query(browser, 'work_products.list')).items;
    checkpoint = 'import and adopt';
    await preview();
    assert.deepEqual((await query(browser, 'work_products.list')).items, before);
    await browser.click('#sheet [data-action="confirm-import"]');
    await waitFor(
      browser,
      `!document.querySelector('#sheet[open]') && document.body.innerText.includes(${JSON.stringify(title)})`,
    );
    const imported = (await query(browser, 'work_products.list')).items.find(
      (row) => row.title === title,
    );
    assert.ok(imported);
    assert.equal(imported.adoption.status, 'unadopted');
    if (adoptWork) {
      await clickReady(browser, text('采用', 'Adopt'), '[data-action="adopt"]');
      await waitFor(browser, `!document.querySelector('[data-action="adopt"]')`);
      await clickReady(browser, text('分享已保存的这版', 'Share this saved version'));
      await waitFor(
        browser,
        `document.querySelector('[data-v4-insertion="sharing"]')?.innerText.includes(${JSON.stringify(text('可见', 'Visible'))})`,
      );
    }
    const adopted = (await query(browser, 'work_products.list')).items.find(
      (row) => row.product_id === imported.product_id,
    );
    assert.equal(adopted.adoption.status, adoptWork ? 'adopted' : 'unadopted');
    checkpoint = 'remove and repeat import';
    await clickReady(browser, text('移除作品', 'Remove product'));
    await clickReady(
      browser,
      text('确认移除并撤回全部分享', 'Confirm removal and revoke all shares'),
    );
    await waitFor(
      browser,
      `(async () => {
      const live = window.PracticeLive;
      const page = await live.v4Host(live.engine.getAttempt(live.state)).query('work_products.list', {});
      return !!page.items.find(row => row.product_id === ${JSON.stringify(imported.product_id)})?.removed_at;
    })()`,
    );
    // Keep a different work selected: the dialog must restore its own target.
    const otherTitle = text('另一份保持原状的作品', 'Another work kept unchanged');
    const otherReturn = JSON.parse(returned);
    otherReturn.returnId += '-other';
    otherReturn.artifact.title = otherTitle;
    await browser.click('.rail-tabs [data-tab="agent"]');
    await preview(JSON.stringify(otherReturn));
    await browser.click('#sheet [data-action="confirm-import"]');
    await waitFor(
      browser,
      `!document.querySelector('#sheet[open]') && document.body.innerText.includes(${JSON.stringify(otherTitle)})`,
    );
    const removed = (await query(browser, 'work_products.list')).items;
    const revokedShares = (
      await query(browser, 'work_products.shares.list', { product_id: imported.product_id })
    ).items;
    assert.equal(revokedShares.length, adoptWork ? 1 : 0);
    for (const share of revokedShares) assert.ok(share.revoked_at);
    const otherProduct = removed.find((row) => row.title === otherTitle);
    assert.ok(otherProduct);
    assert.equal(
      removed.find((row) => row.product_id === imported.product_id).removed_at !== null,
      true,
    );
    await browser.click('.rail-tabs [data-tab="agent"]');
    await preview();
    await browser.click('#sheet [data-action="confirm-import"]');
    await waitFor(browser, `!!document.querySelector('#sheet [data-action="restore-work"]')`);
    assert.deepEqual((await query(browser, 'work_products.list')).items, removed);
    checkpoint = 'explicit dialog restoration';
    if (fault) await browser.ev(`window.restoreProbe.fault = ${JSON.stringify(fault)}`);
    await browser.click('#sheet [data-action="restore-work"]');
    if (fault) {
      const expected =
        fault === 'rejected'
          ? text('恢复失败。', 'Restoration failed.')
          : fault === 'lost'
            ? text('恢复尚未确认', 'Restoration is unconfirmed.')
            : text(
                '操作未完成，输入已保留。',
                'The action did not complete. Your input is retained.',
              );
      await waitFor(
        browser,
        `document.querySelector('#sheet[open]')?.innerText.includes(${JSON.stringify(expected)})`,
      );
      const visible = await browser.ev(`document.querySelector('#sheet').innerText`);
      assert.ok(!visible.includes('private diagnostic'));
      assert.ok(!visible.includes('action_unavailable'));
      const afterFault = (await query(browser, 'work_products.list')).items.find(
        (row) => row.product_id === imported.product_id,
      );
      const probe = await browser.ev('window.restoreProbe');
      assert.equal(probe.writes, fault === 'read' ? 0 : 1);
      assert.equal(afterFault.version, adopted.version + (fault === 'lost' ? 2 : 1));
      if (fault === 'lost') {
        await browser.click('#sheet [data-action="close"]');
        await clickReady(browser, text('查看上一请求结果', 'Check previous request'));
        await waitFor(
          browser,
          `(() => {
          const live = window.PracticeLive;
          const host = live.v4Host(live.engine.getAttempt(live.state));
          return host.draft('workspace', host.snapshot().session.sessionId + ':request-pointer')?.status === 'confirmed';
        })()`,
        );
        assert.equal(await browser.ev('window.restoreProbe.writes'), 1);
      } else {
        await waitFor(
          browser,
          `!document.querySelector('#sheet [data-action="restore-work"]').disabled`,
        );
        await browser.click('#sheet [data-action="restore-work"]');
      }
    }
    await waitFor(browser, `!document.querySelector('#sheet[open]')`);
    const products = (await query(browser, 'work_products.list')).items;
    const restored = products.find((row) => row.product_id === imported.product_id);
    assert.equal(restored.removed_at, null);
    assert.equal(restored.version, adopted.version + 2);
    assert.equal(products.length, before.length + 2);
    assert.deepEqual(
      products.find((row) => row.product_id === otherProduct.product_id),
      otherProduct,
    );
    assert.equal(restored.content, imported.content);
    assert.deepEqual(restored.adoption, adopted.adoption);
    assert.deepEqual(
      (await query(browser, 'work_products.shares.list', { product_id: imported.product_id }))
        .items,
      revokedShares,
    );
    await browser.ev('window.restoreReloadMarker = true');
    await browser.send('Page.reload', { ignoreCache: true });
    await waitFor(
      browser,
      `!window.restoreReloadMarker && !!window.PracticeLive?.state && !!window.PracticeLive.store.active()?.v2NativeWorkspace && !!document.querySelector('[data-v4-region="workspace"]')`,
    );
    assert.equal(await browser.ev('typeof window.restoreReloadMarker'), 'undefined');
    const afterReload = (await query(browser, 'work_products.list')).items.find(
      (row) => row.product_id === imported.product_id,
    );
    assert.equal(afterReload.removed_at, null);
    assert.equal(afterReload.version, restored.version);
    assert.equal(afterReload.content, imported.content);
    assert.deepEqual(afterReload.adoption, adopted.adoption);
    assert.deepEqual(
      (await query(browser, 'work_products.shares.list', { product_id: imported.product_id }))
        .items,
      revokedShares,
    );
    results.push({ id: caseId, status: 'passed' });
    console.log(`PASS ${caseId}`);
  } catch (error) {
    const visible = await browser.ev('document.body.innerText');
    writeFileSync(
      `${process.env.OUT}/${caseId}-browser-errors.json`,
      JSON.stringify(browser.logs, null, 2),
    );
    if (await browser.ev('!!window.PracticeLive?.state && !!window.PracticeLive.store.active()')) {
      const products = await query(browser, 'work_products.list');
      writeFileSync(
        `${process.env.OUT}/${caseId}-product-state.json`,
        JSON.stringify(products, null, 2),
      );
    }
    writeFileSync(`${process.env.OUT}/${caseId}-failure.txt`, visible);
    await browser.shot(`${process.env.OUT}/${caseId}-failure.jpg`);
    results.push({ id: caseId, status: 'failed', checkpoint, error: String(error) });
    console.error(`FAIL ${caseId}: ${checkpoint}: ${error}`);
  } finally {
    await browser.close();
    writeFileSync(`${process.env.OUT}/result.json`, `${JSON.stringify(results, null, 2)}\n`);
  }
}
for (const language of ['zh', 'en']) {
  if (process.env.D01_FAILURES === '1') {
    for (const fault of ['read', 'rejected', 'lost']) await run(language, false, fault);
  } else {
    for (const adoptWork of [true, false]) await run(language, adoptWork);
  }
}
assert.equal(results.filter((row) => row.status === 'failed').length, 0);
