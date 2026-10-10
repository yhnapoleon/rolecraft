/** Assistant answer modes and the generator setting in the normal v4 entry, zh and en.
 *
 * Two deployments run one after another on the same ports over real HTTP and workers:
 * an unconfigured one (local provider) and a configured one whose OpenAI-compatible
 * provider is a loopback test double in this process. The double only exists for this
 * check; no real provider, network or key is used. Build the web app first.
 *
 *   CHROME_BIN=... OUT=<new dir> node tests/regression/assistant-mode.browser.mjs
 */
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { delay, launch } from '../walkthrough/cdp.mjs';
import { waitFor } from './browser-support.mjs';

const WEB = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const ROOT = resolve(WEB, '../..');
assert.ok(process.env.OUT, 'OUT is required');
// Services run from the repository root, so every path they receive is absolute.
const OUT = resolve(process.env.OUT);
assert.ok(!existsSync(OUT), 'OUT must be a new directory');
mkdirSync(`${OUT}/screenshots`, { recursive: true });
const PYTHON = process.env.PYTHON || `${ROOT}/.venv/bin/python`;
const WEB_PORT = Number(process.env.WEB_PORT || 19930);
const API_PORT = Number(process.env.API_PORT || 19932);
const BASE = `http://127.0.0.1:${WEB_PORT}/`;
const results = [];

const COPY = {
  zh: {
    waiting: '等待模型接入（当前为原文检索结果）',
    extractive: '原文抽取',
    llm: '模型生成 · 回答待核验',
    unavailable: '模型生成：当前部署未接入模型，暂不能选择。',
    question: '住宿报销上限是多少？',
    generated: '（测试替身生成）住宿上限请以政策原文为准。',
    config: '本次有效配置',
    stale: '来源索引版本落后，以下内容须核验当前政策。',
    oldVersion: '这次回答引用的版本已经不是最新。',
  },
  en: {
    waiting: 'Awaiting model connection (showing extractive result)',
    extractive: 'Extractive',
    llm: 'Model-generated · Answer awaiting verification',
    unavailable:
      'Model-generated: no model is connected to this deployment, so it cannot be selected.',
    question: 'What is the hotel reimbursement limit?',
    generated: '(Test double) Check the hotel limit against the policy text.',
    config: 'Effective configuration for this run',
    stale:
      'The index is behind the source version. Verify the current policy before relying on the following passage.',
    oldVersion: 'This answer cites a version that is no longer current.',
  },
};

/** OpenAI-compatible loopback double: answers assistant prompts with one candidate citation. */
function startProvider() {
  const calls = { assistant: 0, other: 0 };
  const server = createServer((request, response) => {
    let body = '';
    request.on('data', (chunk) => {
      body += chunk;
    });
    request.on('end', () => {
      const payload = JSON.parse(body);
      const system = payload.messages?.[0]?.content ?? '';
      let content = 'Test double reply.';
      if (system.startsWith('assistant-generation-v1')) {
        calls.assistant += 1;
        const data = JSON.parse(payload.messages[1].content);
        content = JSON.stringify({
          answer: COPY[data.work_language].generated,
          citation_ids: [data.candidates[0].id],
        });
      } else calls.other += 1;
      const reply = JSON.stringify({
        choices: [{ message: { content } }],
        usage: { prompt_tokens: 12, completion_tokens: 6 },
      });
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(reply);
    });
  });
  return new Promise((ready) =>
    server.listen(0, '127.0.0.1', () => ready({ server, calls, port: server.address().port })),
  );
}

async function ready(url, child) {
  const deadline = Date.now() + 40000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`Service exited before ${url}`);
    try {
      if ((await fetch(url)).ok) return;
    } catch {
      /* not listening yet */
    }
    await delay(150);
  }
  throw new Error(`Service not ready: ${url}`);
}

async function startDeployment(name, provider, extraEnv) {
  const directory = `${OUT}/${name}`;
  mkdirSync(directory, { recursive: true });
  const env = Object.fromEntries(
    Object.entries(process.env).filter(([key]) => !key.startsWith('CAREER_LAB_')),
  );
  delete env.PYTHONPATH;
  const catalog = `${directory}/catalog.json`;
  const written = spawnSync(
    PYTHON,
    [
      '-c',
      'import sys; from pathlib import Path; from scripts.regression.published import write_catalog; write_catalog(Path(sys.argv[1]))',
      catalog,
    ],
    { cwd: ROOT, env, encoding: 'utf8' },
  );
  assert.equal(written.status, 0, written.stderr);
  Object.assign(env, extraEnv, {
    CAREER_LAB_CREDENTIAL_KEY_ID: 'assistant-mode-fixture-v1',
    CAREER_LAB_CREDENTIAL_KEY: 'isolated-assistant-mode-credential-key-not-for-deployment',
    CAREER_LAB_SCENARIO_CATALOG: catalog,
    CAREER_LAB_SCENARIO_ARCHIVE: `${directory}/archive`,
    ROLECRAFT_API_TARGET: `http://127.0.0.1:${API_PORT}`,
    PYTHONDONTWRITEBYTECODE: '1',
  });
  const common = ['--database-url', `sqlite:///${directory}/assistant.db`, '--provider', provider];
  const children = [];
  const run = (label, command, args, cwd) => {
    const child = spawn(command, args, { cwd, env, stdio: ['ignore', 'pipe', 'pipe'] });
    const log = [];
    child.stdout.on('data', (chunk) => log.push(chunk));
    child.stderr.on('data', (chunk) => log.push(chunk));
    child.on('exit', () => writeFileSync(`${directory}/${label}.log`, Buffer.concat(log)));
    children.push(child);
    return child;
  };
  const api = run(
    'api',
    PYTHON,
    ['-m', 'career_lab.cli', 'serve', '--host', '127.0.0.1', '--port', String(API_PORT), ...common],
    ROOT,
  );
  await ready(`http://127.0.0.1:${API_PORT}/health`, api);
  run('worker', PYTHON, ['-m', 'career_lab.cli', 'worker', ...common], ROOT);
  const web = run(
    'web',
    `${WEB}/node_modules/.bin/vite`,
    ['preview', '--port', String(WEB_PORT), '--strictPort'],
    WEB,
  );
  await ready(BASE, web);
  return async () => {
    for (const child of children.reverse()) {
      if (child.exitCode === null) {
        child.kill('SIGTERM');
        await Promise.race([new Promise((done) => child.once('exit', done)), delay(5000)]);
        if (child.exitCode === null) child.kill('SIGKILL');
      }
    }
  };
}

const viewports = {
  desktop: { width: 1440, height: 1000, reduced: true },
  mobile: { width: 390, height: 844, mobile: true, reduced: true },
};

async function stable(browser) {
  await browser.ev('document.fonts.ready.then(() => true)');
  await waitFor(browser, '!window.PracticeLive.store.getSnapshot().busy');
  await waitFor(browser, `!document.querySelector('#toast.visible')`, 8000).catch(() => {});
  await delay(300);
}

async function shot(browser, name, selector) {
  await stable(browser);
  if (selector)
    await browser.ev(
      `document.querySelector(${JSON.stringify(selector)})?.scrollIntoView({block: 'start'})`,
    );
  const path = `${OUT}/screenshots/${name}.jpg`;
  await browser.shot(path);
  return path;
}

async function noHorizontalScroll(browser, where) {
  const width = await browser.ev(
    '[document.documentElement.scrollWidth, window.innerWidth, document.body.scrollWidth]',
  );
  assert.ok(width[0] <= width[1] + 1 && width[2] <= width[1] + 1, `${where} overflows: ${width}`);
}

async function enter(viewport, language) {
  const browser = await launch(viewports[viewport]);
  await browser.goto(BASE);
  await browser.ev(
    `localStorage.clear(); localStorage.setItem('rolecraft.locale', ${JSON.stringify(language)});`,
  );
  await browser.goto(BASE);
  await waitFor(browser, `!!document.querySelector('[data-action="open-career"]')`);
  await browser.click('[data-action="open-career"]');
  await browser.click('.case-hero [data-action="take-case"]');
  await waitFor(browser, `location.hash === '#/work' && !!document.querySelector('.card-open')`);
  assert.equal(
    await browser.ev('window.PracticeLive.store.active().v2Binding.workLanguage'),
    language,
  );
  return browser;
}

const active = (browser, expression) =>
  browser.ev(`(() => { const s = window.PracticeLive.store.active(); return ${expression}; })()`);

async function openBench(browser) {
  await browser.goto(`${BASE}#/work`);
  await waitFor(browser, `!!document.querySelector('[data-action="open-bench"]')`);
  await browser.click('[data-action="open-bench"]');
  await waitFor(browser, `!!document.querySelector('#lab-q')`);
}

async function openSettings(browser) {
  await browser.click('.console-tools [data-action="config"]');
  await waitFor(browser, `!!document.querySelector('#config-form .generator-field')`);
}

async function saveSettings(browser) {
  const before = await active(browser, 's.world.config_version');
  await browser.submit('#config-form');
  await waitFor(
    browser,
    `window.PracticeLive.store.active().world.config_version === ${before + 1}`,
    20000,
  );
  return before + 1;
}

async function ask(browser) {
  const count = await browser.ev(`document.querySelectorAll('.run:not(.is-queued)').length`);
  const language = await active(browser, 's.v2Binding.workLanguage');
  await browser.type('#lab-q', COPY[language].question);
  await browser.submit('[data-form="run-test"]');
  return count;
}

/** The newest saved run's labels and the full text of the run card. */
const latestRun = (browser) =>
  browser.ev(`(() => {
    const run = document.querySelector('.runs .run:not(.is-queued)');
    const latest = run?.querySelector('.run-col');
    return {
      labels: [...(latest?.querySelectorAll('.answer-mode') ?? [])].map((n) => n.textContent),
      modes: [...(run?.querySelectorAll('.answer-mode') ?? [])].map((n) => n.dataset.answerMode),
      text: run?.innerText ?? '',
      body: latest?.querySelector('.answer-body')?.innerText ?? '',
      config: latest?.querySelector('.run-meta .stamp')?.textContent ?? '',
    };
  })()`);

const occurrences = (text, part) => text.split(part).length - 1;

async function importTestPlan(browser, language) {
  const plan = {
    schemaVersion: 1,
    returnId: `assistant-mode-${language}-${randomBytes(4).toString('hex')}`,
    artifact: {
      kind: 'test_set',
      title: language === 'zh' ? '住宿上限测试' : 'Hotel limit test',
      purpose: '测试计划',
      body: language === 'zh' ? '核对住宿报销上限。' : 'Check the hotel reimbursement limit.',
      cases: [
        {
          question: COPY[language].question,
          intent: language === 'zh' ? '核对政策' : 'Check the policy',
          expectation: '',
          refs: [],
        },
      ],
    },
  };
  await browser.goto(`${BASE}#/work`);
  await waitFor(browser, `!!document.querySelector('.card-open')`);
  await browser.click('.card-open');
  await waitFor(browser, `!!document.querySelector('.rail-tabs [data-tab="agent"]')`);
  await browser.click('.rail-tabs [data-tab="agent"]');
  await waitFor(browser, `!!document.querySelector('#import-content')`);
  await browser.type('#import-content', JSON.stringify(plan));
  await browser.submit('[data-form="import"]');
  await waitFor(browser, `!!document.querySelector('#sheet [data-action="confirm-import"]')`);
  await browser.click('#sheet [data-action="confirm-import"]');
  await waitFor(
    browser,
    `!!document.querySelector('[data-action="adopt"]') || !!document.querySelector('[data-action="test-run"]')`,
    20000,
  );
  if (await browser.ev(`!!document.querySelector('[data-action="adopt"]')`))
    await browser.click('[data-action="adopt"]');
  await waitFor(
    browser,
    `(() => { const b = document.querySelector('[data-action="test-run"]'); return !!b && !b.disabled; })()`,
    20000,
  );
}

async function runCase(browser, mode) {
  await browser.click('[data-action="test-run"]');
  await waitFor(
    browser,
    `document.querySelector('.test-generation')?.dataset.generationMode === ${JSON.stringify(mode)}`,
    30000,
  );
  return browser.ev(`(() => {
    const row = document.querySelector('.test-generation');
    return {
      labels: [...row.querySelectorAll('.test-generation-label')].map((n) => n.textContent),
      row: row.innerText,
      result: document.querySelector('.test-result')?.innerText ?? '',
      config: row.querySelector('.test-effective-config summary')?.textContent ?? '',
    };
  })()`);
}

/** What an authorized Agent may already do: apply settings the panel does not show. */
const applyAsAgent = (browser, settings) =>
  browser.ev(`(async () => {
    const s = window.PracticeLive.store.active();
    const headers = { Authorization: 'Bearer ' + s.token, 'Content-Type': 'application/json' };
    const path = '/api/sessions/' + encodeURIComponent(s.id);
    const state = (await (await fetch(path, { headers })).json()).state;
    const read = await (await fetch(path + '/workbench', { headers })).json();
    const config = read.result.result.timeline.workspace.config;
    const response = await fetch(path + '/configuration', {
      method: 'POST',
      headers,
      body: JSON.stringify({
        schema_version: 2,
        request_id: crypto.randomUUID(),
        operation: 'configuration.apply',
        payload: {
          base: { session_id: s.id, kind: 'config', object_id: config.id, version: config.version,
            config_version: config.config_version },
          settings: ${JSON.stringify(settings)},
        },
        expected_version: state.business_seq,
        expected_workspace_revision: state.workspace_revision,
      }),
    });
    return response.status;
  })()`);

async function step(deployment, language, name, action) {
  await action();
  results.push({ deployment, language, name, status: 'passed' });
  console.log(`PASS ${deployment} ${language}: ${name}`);
}

async function unconfigured(language) {
  const text = COPY[language];
  const browser = await enter('desktop', language);
  try {
    await step('unconfigured', language, 'settings show llm unavailable', async () => {
      await openBench(browser);
      assert.equal(await active(browser, 's.v2Assistant'), 'waiting_model');
      await openSettings(browser);
      const field = await browser.ev(`(() => {
        const f = document.querySelector('#config-form .generator-field');
        const input = (v) => f.querySelector('input[value="' + v + '"]');
        return { extractive: input('extractive').checked, llmDisabled: input('llm').disabled,
          note: f.querySelector('[data-state="unavailable"]')?.textContent };
      })()`);
      assert.deepEqual(field, { extractive: true, llmDisabled: true, note: text.unavailable });
      await shot(browser, `unconfigured-${language}-settings-desktop`, '.generator-field');
      const version = await saveSettings(browser);
      assert.equal(await active(browser, 's.world.configs.pilot.generator'), 'extractive');
      assert.equal(await active(browser, 's.world.config_version'), version);
    });
    await step('unconfigured', language, 'bench answer has exactly one label', async () => {
      await openBench(browser);
      await ask(browser);
      await waitFor(browser, `document.querySelectorAll('.runs .run').length > 0`, 20000);
      const run = await latestRun(browser);
      assert.deepEqual(run.labels, [text.waiting]);
      assert.equal(occurrences(run.text, text.waiting), 1);
      assert.equal(occurrences(run.body, text.waiting), 1);
      assert.ok(!run.text.includes(`${text.extractive}\n`), 'no second mode line');
      assert.equal(await active(browser, 's.tests.at(-1).mode'), 'extractive');
      await shot(browser, `unconfigured-${language}-bench-desktop`, '.runs');
    });
    await step('unconfigured', language, 'test-plan mode row shows real values once', async () => {
      await importTestPlan(browser, language);
      const row = await runCase(browser, 'extractive');
      assert.deepEqual(row.labels, [text.waiting]);
      assert.equal(occurrences(row.result, text.waiting), 1);
      assert.ok(row.config.startsWith(text.config) && /v\d+$/.test(row.config), row.config);
      await shot(browser, `unconfigured-${language}-testplan-desktop`, '.test-result');
    });
    assert.deepEqual(
      browser.logs.filter((entry) => entry.level === 'exception'),
      [],
    );
  } finally {
    await browser.close();
  }
  const mobile = await enter('mobile', language);
  try {
    await step('unconfigured', language, '390px bench and settings', async () => {
      await openBench(mobile);
      await ask(mobile);
      await waitFor(mobile, `document.querySelectorAll('.runs .run').length > 0`, 20000);
      assert.deepEqual((await latestRun(mobile)).labels, [text.waiting]);
      await noHorizontalScroll(mobile, 'bench');
      await shot(mobile, `unconfigured-${language}-bench-mobile`, '.runs');
      await openSettings(mobile);
      await noHorizontalScroll(mobile, 'settings');
      await shot(mobile, `unconfigured-${language}-settings-mobile`, '.generator-field');
    });
  } finally {
    await mobile.close();
  }
}

async function configured(language, calls) {
  const text = COPY[language];
  const before = calls.assistant;
  const browser = await enter('desktop', language);
  try {
    await step('configured', language, 'select model generation in settings', async () => {
      await openBench(browser);
      assert.equal(await active(browser, 's.v2Assistant'), 'model');
      await openSettings(browser);
      assert.equal(
        await browser.ev(`document.querySelector('#config-form input[value="llm"]').disabled`),
        false,
      );
      await browser.click('#config-form input[value="llm"]');
      await shot(browser, `configured-${language}-settings-llm-desktop`, '.generator-field');
      await saveSettings(browser);
      assert.equal(await active(browser, 's.world.configs.pilot.generator'), 'llm');
    });
    await step(
      'configured',
      language,
      'generated answer is labelled awaiting verification',
      async () => {
        await ask(browser);
        await waitFor(
          browser,
          `!!document.querySelector('.runs .run .answer-mode[data-answer-mode="llm"]')`,
          30000,
        );
        const run = await latestRun(browser);
        assert.deepEqual(run.labels, [text.llm]);
        assert.equal(occurrences(run.text, text.llm), 1);
        assert.ok(run.body.includes(text.generated), run.body);
        const version = await active(browser, 's.world.config_version');
        assert.ok(run.config.includes(`v${version}`), run.config);
        assert.equal(calls.assistant, before + 1);
        await shot(browser, `configured-${language}-bench-llm-desktop`, '.runs');
      },
    );
    await step(
      'configured',
      language,
      'test-plan mode row shows the generated record',
      async () => {
        await importTestPlan(browser, language);
        const row = await runCase(browser, 'llm');
        assert.deepEqual(row.labels, [text.llm]);
        assert.ok(row.row.includes('openai'), row.row);
        assert.ok(row.result.includes(text.generated), row.result);
        assert.ok(row.config.startsWith(text.config), row.config);
        assert.equal(calls.assistant, before + 2);
        await shot(browser, `configured-${language}-testplan-llm-desktop`, '.test-result');
      },
    );
    await step(
      'configured',
      language,
      'stale warning stays before a generated answer',
      async () => {
        await openBench(browser);
        const version = await active(browser, 's.world.config_version');
        assert.equal(await applyAsAgent(browser, { freshness_guard: 'warn' }), 200);
        await waitFor(
          browser,
          `window.PracticeLive.store.active().world.config_version === ${version + 1}`,
          20000,
        );
        await ask(browser);
        await waitFor(
          browser,
          `document.querySelector('.runs .run .run-col .answer-body')?.innerText.includes(${JSON.stringify(text.stale)})`,
          30000,
        );
        const run = await latestRun(browser);
        assert.deepEqual(run.labels, [text.llm]);
        assert.ok(run.body.indexOf(text.stale) < run.body.indexOf(text.generated), run.body);
        assert.ok(run.text.includes(text.oldVersion), run.text);
        assert.equal(calls.assistant, before + 3);
        await shot(browser, `configured-${language}-bench-stale-llm-desktop`, '.runs');
      },
    );
    await step('configured', language, 'reset to extractive keeps history labelled', async () => {
      await openBench(browser);
      await openSettings(browser);
      await browser.click('#config-form input[value="extractive"]');
      await saveSettings(browser);
      assert.equal(await active(browser, 's.world.configs.pilot.generator'), 'extractive');
      await openBench(browser);
      const runs = await ask(browser);
      await waitFor(
        browser,
        `document.querySelector('.runs .run .run-col .answer-mode')?.dataset.answerMode === 'extractive'`,
        20000,
      );
      const run = await latestRun(browser);
      assert.deepEqual(run.labels, [text.extractive]);
      assert.deepEqual(run.modes, ['extractive', 'llm']);
      assert.equal(occurrences(run.text, text.waiting), 0);
      assert.equal(calls.assistant, before + 3);
      assert.ok(runs >= 1);
      await shot(browser, `configured-${language}-bench-reset-desktop`, '.runs');
    });
    assert.deepEqual(
      browser.logs.filter((entry) => entry.level === 'exception'),
      [],
    );
  } finally {
    await browser.close();
  }
  const mobile = await enter('mobile', language);
  try {
    await step('configured', language, '390px generated answer and settings', async () => {
      await openBench(mobile);
      await openSettings(mobile);
      await mobile.click('#config-form input[value="llm"]');
      await saveSettings(mobile);
      await ask(mobile);
      await waitFor(
        mobile,
        `!!document.querySelector('.runs .run .answer-mode[data-answer-mode="llm"]')`,
        30000,
      );
      assert.deepEqual((await latestRun(mobile)).labels, [text.llm]);
      await noHorizontalScroll(mobile, 'bench');
      await shot(mobile, `configured-${language}-bench-llm-mobile`, '.runs');
      await openSettings(mobile);
      await noHorizontalScroll(mobile, 'settings');
      await shot(mobile, `configured-${language}-settings-mobile`, '.generator-field');
    });
  } finally {
    await mobile.close();
  }
}

const provider = await startProvider();
let failure;
try {
  let stop = await startDeployment('unconfigured', 'local', {});
  try {
    for (const language of ['zh', 'en']) await unconfigured(language);
  } finally {
    await stop();
  }
  // A synthetic test-only key in the output directory; it is never printed or reused.
  const keyFile = `${OUT}/configured-provider.key`;
  writeFileSync(keyFile, `sk-${randomBytes(24).toString('hex')}\n`, { mode: 0o600 });
  stop = await startDeployment('configured', 'openai', {
    CAREER_LAB_KEY_FILE: keyFile,
    CAREER_LAB_BASE_URL: `http://127.0.0.1:${provider.port}`,
    CAREER_LAB_MODEL: 'assistant-mode-test-double',
  });
  try {
    for (const language of ['zh', 'en']) await configured(language, provider.calls);
  } finally {
    await stop();
  }
} catch (error) {
  failure = error;
  results.push({ status: 'failed', error: String(error?.stack ?? error) });
} finally {
  provider.server.close();
  writeFileSync(
    `${OUT}/result.json`,
    `${JSON.stringify({ results, providerCalls: provider.calls }, null, 2)}\n`,
  );
}
if (failure) throw failure;
console.log(
  `assistant-mode: ${results.length} checks passed; provider calls ${JSON.stringify(provider.calls)}`,
);
