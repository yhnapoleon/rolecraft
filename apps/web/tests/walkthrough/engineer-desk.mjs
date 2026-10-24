// Engineer walkthrough over the normal entry (201 redesign): home engineer card "Start" → the
// intro ("same practice, second hat") → Daniel's ticket and the three steps → reproduce (amber,
// "still broken") → your agent connects over MCP and reproduces, runs a trial (warn + min score
// 0.2) and drafts with one change stated → the person takes the agent's settings, runs a trial,
// holds to sign → review 1 (one new hidden failure, amber) → fix again (warn only), drafts by hand,
// signs → review 2 (all clear, compared with review 1) → back to the product manager.
// Screenshots (PNG) for design review, named after-<screen>-<state>-<theme>-<width>-<lang>.png.
//
// DELIVER=1: before the product manager opens the review, the practice is delivered (one note and a
// no-go, set up through the API), so "update the pilot" first opens a revision and the board shows
// Grace's note quoting the person's reason (G13): after-pm-board-revise-note-*.
//
// BASE=http://127.0.0.1:18760 OUT=<dir> LANG_UI=zh|en [THEME=dark] [WIDTH=390] [REDUCED=1]
//   [DELIVER=1] [VIDEO=1] [FFMPEG=<ffmpeg>] CHROME_BIN=… node apps/web/tests/walkthrough/engineer-desk.mjs
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { delay, launch } from './cdp.mjs';

const base = process.env.BASE;
const out = process.env.OUT;
const language = process.env.LANG_UI === 'zh' ? 'zh' : 'en';
const dark = process.env.THEME === 'dark';
const width = Number(process.env.WIDTH || 1440);
const reduced = process.env.REDUCED === '1';
const video = process.env.VIDEO === '1';
assert.ok(base && out, 'BASE and OUT are required');
mkdirSync(out, { recursive: true });
const zh = language === 'zh';
const say = (cn, en) => (zh ? cn : en);
const tag = `${dark ? 'dark' : 'light'}-${width}-${language}${reduced ? '-reduced' : ''}`;
const results = [];

const browser = await launch({
  width,
  height: width < 600 ? 844 : 900,
  dark,
  mobile: width < 600,
  reduced,
});

async function waitFor(expression, ms = 45000) {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    if (await browser.ev(expression)) return;
    await delay(100);
  }
  throw new Error(`Timed out: ${expression}`);
}
const shots = [];
async function shot(screen, state, { settle = 500 } = {}) {
  const path = `${out}/after-${screen}-${state}-${tag}.png`;
  await delay(reduced ? 200 : settle);
  const r = await browser.send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(path, Buffer.from(r.data, 'base64'));
  shots.push(path);
}
async function step(name, fn) {
  const started = Date.now();
  try {
    await fn();
    results.push({ name, ok: true, ms: Date.now() - started });
    console.log(`ok   ${name}`);
  } catch (error) {
    results.push({ name, ok: false, error: String(error?.stack || error) });
    console.log(`FAIL ${name}\n${error?.stack || error}`);
    await shot('fail', name.replace(/\W+/g, '-')).catch(() => {});
    throw error;
  }
}
const setValue = (sel, value) =>
  browser.ev(`(() => { const el = document.querySelector(${JSON.stringify(sel)}); if (!el) return false;
    el.focus(); el.value = ${JSON.stringify(value)}; el.dispatchEvent(new Event('input', { bubbles: true })); return true; })()`);
const enabled = (sel) =>
  `!!document.querySelector(${JSON.stringify(sel)}) && !document.querySelector(${JSON.stringify(sel)}).disabled`;
// The engineer's screens are the workspace's main screen: #main scrolls, not the window.
const top = (sel) =>
  browser.ev(`(() => { const el = document.querySelector(${JSON.stringify(sel)}); if (!el) return false;
    el.scrollIntoView({ block: 'start' }); document.getElementById('main')?.scrollBy(0, -16); return true; })()`);
const toTop = () =>
  browser.ev(
    `(() => { window.scrollTo(0, 0); document.getElementById('main')?.scrollTo(0, 0); return true; })()`,
  );
const noRawCodes = async (where) => {
  const body = await browser.ev(`document.querySelector('main')?.innerText ?? ''`);
  for (const bad of [
    'engineer_',
    'answered_with_warning',
    '"schema_version"',
    'ticket-',
    'review-',
    'trial-',
    'draft-',
    '模拟',
    'simulat',
  ])
    assert.ok(!body.includes(bad), `${where}: shows ${bad}`);
};
const noSideScroll = async (where) => {
  const wide = await browser.ev('document.documentElement.scrollWidth - window.innerWidth');
  assert.ok(wide <= 1, `${where}: scrolls sideways by ${wide}px`);
};

/** Hold the pointer on an element for ms (a real press: pointerdown … pointerup). */
async function hold(sel, ms) {
  const box = await browser.ev(
    `(() => { const e = document.querySelector(${JSON.stringify(sel)}); e.scrollIntoView({ block: 'center', behavior: 'instant' }); const r = e.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; })()`,
  );
  if (width < 600) {
    // A phone: a finger held on the key.
    if (process.env.DEBUG)
      console.log(
        'hold at',
        box,
        await browser.ev(
          `(() => { const e = document.elementFromPoint(${box.x}, ${box.y}); return e ? e.outerHTML.slice(0, 160) : null; })()`,
        ),
      );
    const point = [{ x: box.x, y: box.y }];
    await browser.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: point });
    await delay(ms);
    await browser.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    return;
  }
  await browser.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: box.x, y: box.y });
  await browser.send('Input.dispatchMouseEvent', {
    type: 'mousePressed',
    x: box.x,
    y: box.y,
    button: 'left',
    clickCount: 1,
  });
  await delay(ms);
  await browser.send('Input.dispatchMouseEvent', {
    type: 'mouseReleased',
    x: box.x,
    y: box.y,
    button: 'left',
    clickCount: 1,
  });
}
/** A real mouse click (pointer events, focus as a person's click gives it). */
async function mouseClick(sel) {
  const box = await browser.ev(
    `(() => { const e = document.querySelector(${JSON.stringify(sel)}); e.scrollIntoView({ block: 'center', behavior: 'instant' }); const r = e.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; })()`,
  );
  for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased'])
    await browser.send('Input.dispatchMouseEvent', {
      type,
      x: box.x,
      y: box.y,
      button: 'left',
      clickCount: type === 'mouseMoved' ? 0 : 1,
    });
  await delay(400);
}
async function pressEnter(sel) {
  await browser.ev(`document.querySelector(${JSON.stringify(sel)}).focus(); true`);
  const key = { key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 };
  await browser.send('Input.dispatchKeyEvent', { type: 'keyDown', ...key, text: '\r' });
  await browser.send('Input.dispatchKeyEvent', { type: 'keyUp', ...key });
}

/** Record the screen while fn runs (screencast frames → ffmpeg). */
async function record(name, fn) {
  if (!video) return fn();
  const dir = join(out, `.frames-${name}`);
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  const frames = [];
  const off = browser.on('Page.screencastFrame', (p) => {
    frames.push({ data: p.data, t: p.metadata.timestamp });
    browser.send('Page.screencastFrameAck', { sessionId: p.sessionId }).catch(() => {});
  });
  await browser.send('Page.startScreencast', { format: 'jpeg', quality: 85, everyNthFrame: 1 });
  try {
    await fn();
    await delay(700);
  } finally {
    await browser.send('Page.stopScreencast');
    off();
  }
  if (frames.length < 2) return;
  const lines = [];
  frames.forEach((f, i) => {
    const file = join(dir, `${String(i).padStart(5, '0')}.jpg`);
    writeFileSync(file, Buffer.from(f.data, 'base64'));
    const next = frames[i + 1];
    lines.push(
      `file '${file}'`,
      `duration ${next ? Math.max(0.001, next.t - f.t).toFixed(4) : 0.5}`,
    );
  });
  lines.push(`file '${join(dir, `${String(frames.length - 1).padStart(5, '0')}.jpg`)}'`);
  writeFileSync(join(dir, 'list.txt'), lines.join('\n'));
  const target = `${out}/after-${name}-${tag}-motion.webm`;
  execFileSync(process.env.FFMPEG, [
    '-y',
    '-loglevel',
    'error',
    '-f',
    'concat',
    '-safe',
    '0',
    '-i',
    join(dir, 'list.txt'),
    '-vf',
    'scale=trunc(iw/4)*2:trunc(ih/4)*2,fps=30',
    '-c:v',
    'libvpx-vp9',
    '-b:v',
    '2M',
    target,
  ]);
  rmSync(dir, { recursive: true, force: true });
  shots.push(target);
}

/** A button found by its visible words (React islands carry no ids). */
const byText = (scope, re) =>
  `[...document.querySelectorAll(${JSON.stringify(scope)})].find((b) => ${re}.test(b.textContent) || ${re}.test(b.getAttribute('aria-label') || ''))`;
/** My agent's "Other MCP client" config, copied (captured instead of the system clipboard):
 * the endpoint and the token the person's Agent would use. */
async function copiedConfig() {
  await browser.ev(`(() => { window.edCopied = null; Object.defineProperty(navigator.clipboard, 'writeText',
    { configurable: true, value: async (t) => { window.edCopied = t; } }); return true; })()`);
  await browser.ev(
    `(${byText('.ag-connect button', '/其他 MCP 客户端|Other MCP client/')}).click(); true`,
  );
  await waitFor(`!!(${byText('.ag-connect button', '/复制配置|Copy config/')})`);
  await browser.ev(`(${byText('.ag-connect button', '/复制配置|Copy config/')}).click(); true`);
  await waitFor('typeof window.edCopied === "string"');
  const server = JSON.parse(await browser.ev('window.edCopied')).mcpServers.rolecraft;
  return { endpoint: server.url, token: server.headers.Authorization.replace(/^Bearer /, '') };
}
/** What the person's own Agent sends over MCP (Streamable HTTP, 2026-07-28). */
async function agentCall(endpoint, token, name, args) {
  const response = await fetch(endpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json, text/event-stream',
      Authorization: `Bearer ${token}`,
      'MCP-Protocol-Version': '2026-07-28',
      'Mcp-Method': 'tools/call',
      'Mcp-Name': name,
    },
    body: JSON.stringify({
      jsonrpc: '2.0',
      id: Date.now(),
      method: 'tools/call',
      params: {
        name,
        arguments: args,
        _meta: {
          'io.modelcontextprotocol/protocolVersion': '2026-07-28',
          'io.modelcontextprotocol/clientCapabilities': {},
          'io.modelcontextprotocol/clientInfo': { name: 'claude-code', version: '2' },
        },
      },
    }),
  });
  const body = await response.json();
  assert.equal(response.status, 200, JSON.stringify(body));
  assert.equal(body.result.isError, false, JSON.stringify(body.result));
  return body.result.structuredContent;
}
const agentCommand = (operation, payload) => ({
  command: {
    schema_version: 2,
    request_id: `walk-${operation}-${Date.now()}`,
    operation,
    payload,
    expected_version: 0,
    expected_workspace_revision: 0,
  },
});

/** Set-up only (DELIVER=1): deliver the practice through the API, as its own submit would, so the
 * product side meets a delivered practice. The page's own credentials are borrowed from its next
 * request. */
async function deliverPractice(sessionId) {
  // The page's bearer token, read off its own next API request (its Agent feed polls every few
  // seconds). No reload: the engineer side keeps the practice it last saw.
  await browser.send('Network.enable');
  let token = null;
  const off = browser.on('Network.requestWillBeSent', (p) => {
    const auth = p.request.headers.Authorization || p.request.headers.authorization;
    if (!token && auth && p.request.url.includes('/api/sessions/')) token = auth;
  });
  const deadline = Date.now() + 20000;
  while (!token && Date.now() < deadline) await delay(100);
  off();
  if (!token) return 'no token';
  return browser.ev(`(async () => {
    const token = ${JSON.stringify(token)};
    const base = ${JSON.stringify(`/api/sessions/${encodeURIComponent(sessionId)}`)};
    const headers = { Authorization: token, 'Content-Type': 'application/json' };
    const state = async () => (await (await fetch(base, { headers: { Authorization: token } })).json()).state;
    const command = async (path, operation, payload) => {
      const s = await state();
      const response = await fetch(base + path, { method: 'POST', headers, body: JSON.stringify({
        schema_version: 2, request_id: crypto.randomUUID(), operation, payload,
        expected_version: s.business_seq, expected_workspace_revision: s.workspace_revision }) });
      const body = await response.json();
      if (!response.ok) return { error: operation + ' ' + response.status + ' ' + JSON.stringify(body).slice(0, 300) };
      return body.result;
    };
    const work = await command('/work-products', 'work_products.create', {
      kind: 'text', title: ${JSON.stringify(say('试点判断', 'Pilot decision'))},
      content: ${JSON.stringify(say('先不上线：住宿上限的回答还在引用旧政策。', 'Not yet: the hotel-limit answer still cites the old policy.'))} });
    if (work.error) return work.error;
    const sent = await command('/submissions', 'submissions.create', { decision: 'no_go', products: [work.ref] });
    if (sent?.error) return sent.error;
    return (await state()).status;
  })()`);
}

async function signHeld() {
  if (reduced) {
    // Keyboard: Enter draws the line in 400ms and signs, no holding.
    await pressEnter('#ed-sign');
  } else await hold('#ed-sign', 1150);
}

let ticketId = '';
try {
  await browser.goto(base);
  await browser.ev(
    `localStorage.clear(); sessionStorage.clear(); localStorage.setItem('rolecraft.locale', ${JSON.stringify(language)}); true`,
  );
  await browser.goto(base);

  await step('home → engineer Start → the intro', async () => {
    await waitFor(`!!document.querySelector('[data-action="engineer-start"]')`);
    await record('intro-enter', async () => {
      await browser.click('[data-action="engineer-start"]');
      await waitFor(`!!document.querySelector('.ed-intro__q')`, 30000);
      await delay(900);
    });
    assert.match(await browser.ev('location.hash'), /#\/engineer\/.+(\?|%3F)intro/);
    const text = await browser.ev(`document.querySelector('.ed-intro__paper').innerText`);
    assert.ok(text.includes(say('你现在是工程师', 'You’re the engineer now')));
    assert.ok(
      !(await browser.ev(`!!document.querySelector('#ed-intro-back')`)),
      'a new practice offers no way back to product',
    );
    assert.equal(
      await browser.ev(
        `JSON.parse(localStorage.getItem('rolecraft.hat.v1') || '{}')[Object.keys(JSON.parse(localStorage.getItem('rolecraft.hat.v1') || '{}'))[0]]`,
      ),
      'engineer',
    );
    await noSideScroll('intro');
    await shot('intro', 'new');
  });

  await step('take the ticket → Daniel’s ticket and three steps', async () => {
    // P1-3: the problem flies from the intro's slip into Daniel's ticket (shared element).
    await record('take', async () => {
      if (width < 600) await browser.click('#ed-intro-take');
      else await mouseClick('#ed-intro-take');
      await waitFor(
        `!!document.querySelector('.ed-ticket') && !!document.querySelector('.rc-primary__key')`,
      );
    });
    ticketId = (await browser.ev('location.hash')).split('/')[2];
    const ticket = await browser.ev(`document.querySelector('.ed-ticket').innerText`);
    assert.ok(ticket.includes('Daniel'));
    assert.ok(ticket.includes(say('做完是', 'Done means')));
    // The desk is the engineer hat's own first screen (as the board is the product manager's):
    // the shell draws its back key (none once S's fix-agent-hat lands; the base still says Board).
    console.log(
      `     desk back key: ${await browser.ev(`document.querySelector('.shell-bar .back:not(.narrow-only)')?.textContent.trim() ?? '(none)'`)}`,
    );
    await waitFor(
      `/${say('复现问题', 'Reproduce the problem')}/.test(document.querySelector('.rc-primary__label')?.textContent ?? '')`,
    );
    // Inside the workspace: the shell's bar (hat on Engineer, the engineer's scale) and the rail.
    assert.equal(await browser.ev(`document.querySelector('.shell-bar').dataset.hat`), 'engineer');
    assert.ok(
      await browser.ev(`!!document.querySelector('#ws-stage [data-engineer-screen] .ed-ticket')`),
    );
    assert.ok(await browser.ev(`!!document.querySelector('#ws-rail')`), 'the right rail is there');
    assert.equal(
      await browser.ev(
        `[...document.querySelectorAll('.rc-scale__step')].map((b) => b.textContent.trim()).join('|')`,
      ),
      say('复现|修复与试跑|签字', 'Reproduce|Fix & trial|Sign off'),
    );
    if (width < 600)
      assert.ok(
        await browser.ev(`document.getElementById('ws-rail').inert`),
        'the rail is a drawer at phone width',
      );
    assert.equal(await browser.ev(`document.querySelectorAll('.ed-step.is-open').length`), 1);
    assert.equal(
      await browser.ev(`document.querySelector('.ed-step.is-open').dataset.step`),
      'reproduce',
    );
    await noRawCodes('desk');
    await noSideScroll('desk');
    await toTop();
    await shot('desk', 'first');
  });

  await step('① reproduce: still broken, amber, right under the key', async () => {
    await browser.ev(
      `document.querySelector('#ed-reproduce').focus(); document.querySelector('#ed-reproduce').click(); true`,
    );
    await waitFor(`!!document.querySelector('.ed-result__row[data-tone="warn"]')`);
    const row = await browser.ev(`document.querySelector('.ed-result__row').innerText`);
    assert.ok(row.includes(say('问题还在', 'Still broken')));
    assert.ok(
      !(await browser.ev(`!!document.querySelector('.ed-result__row [data-tone="good"]')`)),
      'no green for "still broken"',
    );
    await delay(500);
    assert.equal(
      await browser.ev(`document.querySelector('.ed-step.is-open').dataset.step`),
      'reproduce',
      'focus in ① keeps it open',
    );
    await waitFor(
      `/${say('试跑', 'Run a trial')}/.test(document.querySelector('.rc-primary__label')?.textContent ?? '')`,
    );
    await browser.ev('document.activeElement?.blur(); true');
    await top('.ed-steps');
    await shot('reproduce', 'still-broken');
  });

  let endpoint = '';
  let token = '';
  await step(
    'your agent: connect here, then it reproduces, trials and drafts over MCP',
    async () => {
      // G7: Connect goes to My agent (#/agent); the desk shows no grant card, expiry or command.
      assert.equal(
        await browser.ev(`!!document.querySelector('.ed-agent [data-connection-action]')`),
        false,
      );
      await mouseClick('#ed-grant');
      await waitFor(`location.hash === '#/agent' && !!document.querySelector('.ag-connect-key')`);
      await browser.ev(`document.querySelector('.ag-connect-key').click(); true`);
      await waitFor(`!!document.querySelector('.ag-connect')`);
      await toTop();
      await shot('agent', 'my-agent');
      ({ endpoint, token } = await copiedConfig());
      // Back to the desk the way a person comes back: the browser's back.
      await browser.ev('history.back(); true');
      await waitFor(
        `location.hash.startsWith('#/engineer/') && !!document.querySelector('.ed-agent')`,
      );
      await waitFor(`document.querySelector('.ed-agent').dataset.connection === 'waiting'`);
      await toTop();
      await shot('agent', 'connect');
      // The agent lamp pulses on every real call (shell agent-bus → topbar ring).
      await browser.ev(`(() => { window.edPulses = 0; const animate = Element.prototype.animate;
        Element.prototype.animate = function (...args) { if (this.classList?.contains('lamp-ring')) window.edPulses++;
          return animate.apply(this, args); }; return true; })()`);
      await agentCall(endpoint, token, 'engineer.tickets.read', { query: { ticket_id: ticketId } });
      await agentCall(
        endpoint,
        token,
        'engineer.reproduce',
        agentCommand('engineer.reproduce', { ticket_id: ticketId }),
      );
      await agentCall(
        endpoint,
        token,
        'engineer.trial',
        agentCommand('engineer.trial', {
          ticket_id: ticketId,
          changes: { freshness_guard: 'warn', min_score: 0.2 },
        }),
      );
      await agentCall(
        endpoint,
        token,
        'engineer.submissions.draft',
        agentCommand('engineer.submissions.draft', {
          ticket_id: ticketId,
          changes: { freshness_guard: 'warn', min_score: 0.2 },
          explanation: say(
            '索引落后于新政策时，回答带上提醒。',
            'Warn when the indexed policy is older than the source.',
          ),
          change_statements: [
            {
              field: 'freshness_guard',
              before: 'none',
              after: 'warn',
              reason: say('每日索引落后于新通知。', 'The daily index lags the newer notice.'),
            },
          ],
          claimed_results: { F01: 'pass', F04: 'pass', F05: 'pass', F12: 'pass' },
          unresolved: [],
        }),
      );
      await waitFor(`document.querySelectorAll('.ed-card').length >= 3`, 15000);
      await waitFor('window.edPulses > 0', 15000);
      // The live stream: one line per call (verb · object · tool name), the newest three.
      const streamText = `document.querySelector('.ed-agent__stream')?.textContent ?? ''`;
      await waitFor(
        `document.querySelectorAll('.ed-agent__stream .ag-line').length === 3 && ['engineer.submissions.draft', 'engineer.trial', 'engineer.reproduce'].every((t) => (${streamText}).includes(t))`,
        15000,
      );
      assert.match(
        await browser.ev(`document.querySelector('.ed-agent').dataset.connection`),
        /on|idle/,
      );
      const cards = await browser.ev(`document.querySelector('.ed-cards').innerText`);
      assert.ok(cards.includes(say('起草提交', 'Drafted a sign-off')));
      assert.ok(
        (await browser.ev(`!!document.querySelector('.ed-code-diff')`)) ||
          (await browser.ev(
            `[...document.querySelectorAll('.ed-card__head')].find(h => h.getAttribute('aria-expanded') === 'true')?.closest('.ed-card').dataset.kind`,
          )) === 'draft',
      );
      // Open the trial card: its diff of settings.
      // Opened with the mouse (o7: no focus ring from a pointer).
      // (A phone shows only the newest card: the trial's opens from code there.)
      // Let the stream's arriving lines settle first (they move the cards below by a row); the
      // trial card may already be open (it was the newest when it arrived).
      await delay(900);
      if (!(await browser.ev(`!!document.querySelector('.ed-code-diff')`))) {
        if (width < 600)
          await browser.ev(
            `document.querySelector('.ed-card[data-kind="trial"] .ed-card__head').click(); true`,
          );
        else await mouseClick('.ed-card[data-kind="trial"] .ed-card__head');
      }
      await waitFor(`!!document.querySelector('.ed-code-diff')`);
      await toTop();
      await shot('agent', 'handed-in');
      // A stream line opens its card: the reproduction's row opens the reproduction card.
      await browser.ev(
        `document.querySelectorAll('.ed-card__head[aria-expanded="true"]').forEach((h) => h.click()); true`,
      );
      const repro = `[...document.querySelectorAll('.ed-agent__stream .ag-line')].find((l) => /engineer\\.reproduce/.test(l.textContent))`;
      await waitFor(`!!(${repro})`);
      if (width < 600) await browser.ev(`(${repro}).click(); true`);
      else {
        await browser.ev(`(${repro}).setAttribute('data-walk', 'repro'); true`);
        await mouseClick('[data-walk="repro"]');
      }
      await waitFor(
        `document.querySelector('.ed-card[data-kind="reproduce"] .ed-card__head')?.getAttribute('aria-expanded') === 'true'`,
      );
      // (A phone has the Agent panel below the ticket: bring it to the top.)
      if (width < 600) await top('.ed-agent');
      else await toTop();
      await shot('agent', 'stream-open');
    },
  );

  await step(
    '② take the agent’s settings: changes marked old → new with its mark, then a trial',
    async () => {
      await browser.click('#ed-step-fix');
      await waitFor(`document.querySelector('.ed-step.is-open')?.dataset.step === 'fix'`);
      await waitFor(`!document.querySelector('#ed-use-agent').hidden`);
      await browser.click('#ed-use-agent');
      await waitFor(`document.querySelectorAll('.ed-field.is-changed').length === 2`);
      assert.ok(
        await browser.ev(`!!document.querySelector('.ed-field.is-changed .ed-by-agent')`),
        'agent mark on changed settings',
      );
      // G11: the struck value is this practice's own baseline (0.35 in Chinese, 0.3 in English).
      const was = await browser.ev(
        `document.querySelector('.ed-field[data-field="min_score"] .ed-diff__was').textContent`,
      );
      // The published scenario packs set retrieval thresholds per language.
      const baseline = zh ? '0.35' : '0.3';
      assert.equal(was, baseline, `min_score was ${was}, baseline ${baseline}`);
      await top('#ed-step-fix');
      await shot('fix', 'agent-settings');
      await record('trial', async () => {
        await browser.click('#ed-trial');
        await waitFor(
          `!document.querySelector('.ed-line.is-pending') && document.querySelectorAll('.ed-line[data-kind="trial"]').length >= 2`,
        );
        await delay(700);
      });
      await browser.ev(
        `document.querySelector('.ed-log').scrollIntoView({ block: 'center' }); true`,
      );
      await shot('fix', 'trial-log');
    },
  );

  await step(
    '③ the sheet: actual change beside the stated one, unmarked; hold to sign',
    async () => {
      await browser.click('#ed-step-signoff');
      await waitFor(`!!document.querySelector('.ed-sheet .ed-compare')`);
      const actual = await browser.ev(
        `document.querySelectorAll('.ed-compare__col:first-child .ed-diff__row').length`,
      );
      const stated = await browser.ev(
        `document.querySelectorAll('.ed-compare__col:last-child .ed-diff__row').length`,
      );
      assert.equal(actual, 2);
      assert.equal(stated, 1);
      await top('.ed-sheet');
      await shot('signoff', 'sheet');
      // Signing without the impact note is stopped before the line draws.
      await hold('#ed-sign', 200);
      await waitFor(`!document.querySelector('#ed-impact-error').hidden`);
      await setValue(
        '#ed-impact',
        say('可能影响原来该拒答的问题。', 'Could change answers to questions it used to refuse.'),
      );
      if (!reduced) {
        await hold('#ed-sign', 350);
        await waitFor(`!document.querySelector('.ed-signature__hint').hidden`);
        await shot('signoff', 'hold-early');
      }
      await record('signoff-hold', async () => {
        await signHeld();
        await waitFor(`!document.querySelector('.ed-signature__stamp').hidden`, 5000);
        await delay(reduced ? 200 : 560);
        await shot('signoff', 'stamped', { settle: 0 });
        // G2: the reviews left drop at once; the running line has its counts.
        const left = await browser.ev(
          `document.querySelector('.ed-signature__meta number-flow').value`,
        );
        assert.equal(left, 2, 'reviews left drop to 2 when the stamp lands');
        // (A slow recording may already show "Review done".)
        const running = await browser.ev(
          `document.querySelector('.ed-shimmer')?.textContent ?? null`,
        );
        if (running !== null) assert.ok(running.includes(say('公开 4 条', '4 public')), running);
        await waitFor(
          `location.hash.startsWith('#/engineer-review/') && !!document.querySelector('.er-verdict')`,
          30000,
        );
        await delay(1200);
      });
    },
  );

  await step('review 1: target fixed, one new failure (amber); fix it again leads', async () => {
    const head = await browser.ev(`document.querySelector('.er-verdict').innerText`);
    assert.ok(
      await browser.ev(`document.querySelector('.er-verdict__mark').dataset.tone === 'warn'`),
      head,
    );
    // One ink key on screen: the top bar's says "fix it again"; the report's own key leads its row.
    await waitFor(
      `/${say('再修一轮', 'Fix it again')}/.test(document.querySelector('.rc-primary__label')?.textContent ?? '')`,
    );
    assert.equal(
      await browser.ev(`document.querySelectorAll('#ws-stage .ed-k.is-primary').length`),
      0,
    );
    assert.equal(
      await browser.ev(`document.querySelector('.ed-review__actions .ed-k').id`),
      'ed-again',
    );
    console.log(
      `     report back key: ${await browser.ev(`document.querySelector('.shell-bar .back:not(.narrow-only)')?.textContent.trim() ?? '(none)'`)}`,
    );
    assert.ok(
      await browser.ev(`!!document.querySelector('.ed-note')`),
      'the note: 2 settings changed, 1 described',
    );
    await noRawCodes('report 1');
    await noSideScroll('report 1');
    await toTop();
    await shot('report', 'new-failure');
  });

  await step(
    'fix again: back to ②, candidate kept; put min score back, trial, draft by hand',
    async () => {
      // P0-1: the shell's "fix it again" pressed while the report is on screen (the desk is kept
      // off screen) takes the person to this practice's desk at ②, not into the hidden desk.
      await browser.ev(`(() => { const b = document.createElement('button'); b.dataset.action = 'engineer.fix-again';
        b.hidden = true; document.body.append(b); b.click(); b.remove(); return true; })()`);
      await waitFor(
        `location.hash.startsWith('#/engineer/') && document.querySelector('.ed-step.is-open')?.dataset.step === 'fix'`,
      );
      assert.equal(
        await browser.ev(`document.querySelectorAll('.ed-field.is-changed').length`),
        2,
        'candidate survives the round trip',
      );
      await browser.click('#ed-f-min_score-restore');
      await waitFor(`document.querySelectorAll('.ed-field.is-changed').length === 1`);
      await top('#ed-step-fix');
      await shot('fix', 'one-change');
      await browser.click('#ed-trial');
      await waitFor(
        `document.querySelectorAll('.ed-line[data-kind="trial"]').length >= 3 && !document.querySelector('.ed-line.is-pending')`,
      );
      await browser.click('#ed-step-signoff');
      await waitFor(`!!document.querySelector('#ed-compose')`);
      await browser.click('#ed-compose');
      await waitFor(`!!document.querySelector('#ed-draft-explanation')`);
      await setValue(
        '#ed-draft-explanation',
        say(
          '只在索引落后时加提醒，最低相关度保持不变。',
          'Warn only when the index lags; minimum relevance stays as it was.',
        ),
      );
      await setValue(
        '#ed-st-0-reason',
        say('每日索引落后于新通知。', 'The daily index lags the newer notice.'),
      );
      await browser.click('#ed-claims-on');
      await waitFor(enabled('#ed-claims-fill'));
      await browser.click('#ed-claims-fill');
      await top('.ed-sheet');
      await shot('signoff', 'compose');
      await browser.click('#ed-draft-save');
      await waitFor(
        `!!document.querySelector('.ed-compare') && !document.querySelector('#ed-draft-explanation')`,
      );
      await setValue(
        '#ed-impact',
        say('只影响引用过期资料的回答。', 'Only answers citing an out-of-date source.'),
      );
      await signHeld();
      await waitFor(
        `location.hash.startsWith('#/engineer-review/') && !!document.querySelector('.er-verdict')`,
        30000,
      );
    },
  );

  await step(
    'review 2: all clear, compared with review 1; back to the product manager',
    async () => {
      await record('report-clean', async () => {
        await waitFor(`!!document.querySelector('.ed-compare-row')`, 15000);
        await delay(1600);
      });
      assert.ok(
        await browser.ev(`document.querySelector('.er-verdict__mark').dataset.tone === 'good'`),
      );
      await waitFor(
        `/${say('交回产品经理', 'Back to the product manager')}/.test(document.querySelector('.rc-primary__label')?.textContent ?? '')`,
      );
      assert.equal(
        await browser.ev(`document.querySelector('.ed-review__actions .ed-k').id`),
        'ed-hand-back',
      );
      await noSideScroll('report 2');
      await toTop();
      await shot('report', 'clean', { settle: 1400 });
      await browser.click('#ed-hand-back');
      await waitFor(`location.hash === '#/work'`);
      const hat = await browser.ev(
        `Object.values(JSON.parse(localStorage.getItem('rolecraft.hat.v1') || '{}'))`,
      );
      assert.ok(hat.includes('pm'), 'the hat is the product manager’s again');
      await shot('handback', 'board');
      // The hat switch in the top bar: the bar stays where it is, only the main screen changes;
      // the engineer side comes back to this practice's desk (its last ticket).
      const hatKey = (re) =>
        `[...document.querySelectorAll('.rc-hat [role="radio"], .rc-hat button')].find((b) => ${re}.test(b.textContent) && !b.closest('[aria-hidden="true"]'))`;
      if (width >= 600) {
        const barBefore = await browser.ev(
          `JSON.stringify(document.querySelector('.shell-bar').getBoundingClientRect())`,
        );
        await browser.ev(
          `(${hatKey('/工程师|Engineer/')}).setAttribute('data-walk', 'hat-eng'); true`,
        );
        await record('hat-switch', async () => {
          await mouseClick('[data-walk="hat-eng"]');
          await waitFor(
            `location.hash.startsWith('#/engineer/') && !!document.querySelector('#ws-stage .ed-ticket')`,
          );
          await delay(600);
        });
        assert.equal(
          await browser.ev(
            `JSON.stringify(document.querySelector('.shell-bar').getBoundingClientRect())`,
          ),
          barBefore,
          'the bar does not move when the hat changes',
        );
        await toTop();
        await shot('hat-switch', 'desk');
        await browser.ev(
          `(${hatKey('/产品经理|Product manager/')}).setAttribute('data-walk', 'hat-pm'); true`,
        );
        await mouseClick('[data-walk="hat-pm"]');
        await waitFor(`location.hash === '#/work'`);
        await delay(600);
      }
    },
  );

  if (process.env.DELIVER === '1')
    await step('set-up: the practice is delivered before the review is taken in', async () => {
      const sessionId = decodeURIComponent(endpoint.split('/sessions/')[1].split('/')[0]);
      const status = await deliverPractice(sessionId);
      assert.equal(status, 'submitted', status);
    });

  await step('product side: the review as a sheet; update the pilot from it', async () => {
    // The board line draws the signal; until then the same action is pressed from a stand-in key.
    const reviewId = await browser.ev(
      `Object.keys(Object.values(JSON.parse(localStorage.getItem('rolecraft.engineer.local.v1') || '{}'))[0]?.handedBack || {}).at(-1) || ''`,
    );
    assert.ok(reviewId, 'the hand-back was recorded');
    await browser.ev(`(() => { const b = document.createElement('button'); b.dataset.action = 'engineer.review.open';
      b.dataset.id = ${JSON.stringify(reviewId)}; b.hidden = true; document.body.append(b); b.click(); return true; })()`);
    const update = `[...document.querySelectorAll('.rc-sheet button')].find((b) => /试点设置|pilot settings/.test(b.textContent))`;
    await waitFor(`!!(${update}) && !(${update}).disabled`, 20000);
    await shot('pm-sheet', 'review', { settle: 700 });
    await browser.ev(`(${update}).click(); true`);
    await waitFor(`!!document.querySelector('.ed-confirm')`);
    await shot('pm-confirm', 'update', { settle: 500 });
    await browser.ev(`[...document.querySelectorAll('.ed-confirm button')].at(-1).click(); true`);
    await waitFor(
      `!document.querySelector('.ed-confirm') && /v\\d/.test(document.querySelector('.rc-sheet footer')?.innerText || '')`,
      20000,
    );
    await shot('pm-sheet', 'updated', { settle: 600 });
    // P1-6: the board reads the new configuration without a reload.
    await browser.ev(
      `document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); true`,
    );
    await waitFor(
      `[...document.querySelectorAll('.pb-gauge')].some((g) => /v2/.test(g.textContent))`,
      15000,
    );
    await shot('pm-board', 'config-v2', { settle: 900 });
    if (process.env.DELIVER === '1') {
      // G13: the revision opened for the update; Grace quotes the person's own reason.
      await waitFor(`!!document.querySelector('[data-revise-note]')`, 15000);
      const note = await browser.ev(`document.querySelector('[data-revise-note]').innerText`);
      assert.ok(
        note.includes(
          say('把工程复核修好的设置更新到试点', 'put the engineering fix into the pilot'),
        ),
        note,
      );
      await browser.ev(
        `document.querySelector('[data-revise-note]').scrollIntoView({ block: 'center' }); true`,
      );
      await shot('pm-board', 'revise-note', { settle: 700 });
    }
  });
} finally {
  const errors = browser.logs.filter((l) => l.level !== 'warning');
  writeFileSync(
    `${out}/results-${tag}.json`,
    JSON.stringify({ results, shots, logs: browser.logs }, null, 2),
  );
  console.log(`shots ${shots.length}; console errors ${errors.length}`);
  for (const e of errors.slice(0, 5)) console.log('  ', e.text.slice(0, 200));
  await browser.close();
}
