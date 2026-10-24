// My agent page on the normal entry: one press issues access, the page's own copy action gives the
// command (and the config for other clients), a scripted Streamable HTTP client connects and
// returns work, and the page shows the call stream, the returned paper and the connection state
// until the grant is revoked. No real agent or model is involved.
import assert from 'node:assert/strict';
import { clickReady, waitFor } from './browser-support.mjs';

const MODERN = '2026-07-28';
const LEGACY = '2025-11-25';

/** What an agent's own MCP client sends: the endpoint and the Authorization header, nothing else. */
class McpHttpClient {
  constructor(endpoint, token) {
    this.endpoint = endpoint;
    this.token = token;
    this.id = 0;
  }
  async post(body, headers = {}) {
    const response = await fetch(this.endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json, text/event-stream',
        Authorization: `Bearer ${this.token}`,
        ...headers,
      },
      body: JSON.stringify(body),
    });
    return {
      status: response.status,
      body: response.status === 202 ? null : await response.json(),
    };
  }
  async modern(method, params = {}) {
    this.id += 1;
    const meta = {
      'io.modelcontextprotocol/protocolVersion': MODERN,
      'io.modelcontextprotocol/clientCapabilities': {},
      'io.modelcontextprotocol/clientInfo': { name: 'rolecraft-browser-regression', version: '1' },
    };
    const headers = { 'MCP-Protocol-Version': MODERN, 'Mcp-Method': method };
    if (method === 'tools/call') headers['Mcp-Name'] = params.name;
    return this.post(
      { jsonrpc: '2.0', id: this.id, method, params: { ...params, _meta: meta } },
      headers,
    );
  }
  async call(name, args) {
    const { status, body } = await this.modern('tools/call', { name, arguments: args });
    assert.equal(status, 200, JSON.stringify(body));
    assert.equal(body.result.isError, false, JSON.stringify(body.result));
    return body.result.structuredContent;
  }
  async legacyHandshake() {
    this.id += 1;
    const started = await this.post({
      jsonrpc: '2.0',
      id: this.id,
      method: 'initialize',
      params: {
        protocolVersion: LEGACY,
        capabilities: {},
        clientInfo: { name: 'rolecraft-browser-regression', version: '1' },
      },
    });
    assert.equal(started.status, 200);
    const negotiated = { 'MCP-Protocol-Version': started.body.result.protocolVersion };
    const ready = await this.post(
      { jsonrpc: '2.0', method: 'notifications/initialized' },
      negotiated,
    );
    assert.equal(ready.status, 202);
    this.id += 1;
    const listed = await this.post(
      { jsonrpc: '2.0', id: this.id, method: 'tools/list' },
      negotiated,
    );
    assert.ok(listed.body.result.tools.length > 0);
    return negotiated['MCP-Protocol-Version'];
  }
}

/** The page's own copy action, captured instead of the system clipboard. */
async function copied(browser, selector) {
  await browser.ev(`(() => {
    window.regressionCopied = null;
    Object.defineProperty(navigator.clipboard, 'writeText', {
      configurable: true,
      value: async (text) => { window.regressionCopied = text; },
    });
    return true;
  })()`);
  await browser.click(selector);
  await waitFor(browser, 'typeof window.regressionCopied === "string"');
  return browser.ev('window.regressionCopied');
}

const host = `(() => {
  const live = window.PracticeLive;
  return live.v4Host(live.engine.getAttempt(live.state));
})()`;
/** What the page would still hand out for copying. */
const offeredSecret = (browser) => browser.ev(`${host}.connectionSecret()`);
const issuedId = (browser) => browser.ev(`${host}.issuedDelegation()?.delegationId ?? null`);

/** Another tab revoking a grant: the same API, not this page's host. */
const revokeOutsideThisPage = (browser, delegationId) =>
  browser.ev(`(async () => {
    const session = window.PracticeLive.store.active();
    const headers = { Authorization: 'Bearer ' + session.token };
    const state = (await (await fetch('/api/sessions/' + session.id, { headers })).json()).state;
    const response = await fetch('/api/sessions/' + session.id + '/delegations/' + ${JSON.stringify(delegationId)}, {
      method: 'DELETE',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        schema_version: 2,
        request_id: crypto.randomUUID(),
        operation: 'delegations.revoke',
        payload: { delegation_id: ${JSON.stringify(delegationId)} },
        expected_version: state.business_seq,
        expected_workspace_revision: state.workspace_revision,
      }),
    });
    return response.status;
  })()`);

/** The My agent page of the practice on screen, ready to connect or already connected. */
export async function openMyAgent(browser) {
  await browser.ev(`location.hash = '#/agent'`);
  await waitFor(
    browser,
    `!!document.querySelector('.ag-rig') && (
      !!document.querySelector('.ag-cta button:not([disabled])') ||
      ['waiting', 'connected', 'idle'].includes(document.querySelector('.ag-rig').dataset.phase))`,
  );
}

const phase = (browser, name, milliseconds) =>
  waitFor(
    browser,
    `document.querySelector('.ag-rig')?.dataset.phase === ${JSON.stringify(name)}`,
    milliseconds,
  );

export async function connectAgentOverMcp(context) {
  const { browser, text, shot } = context;
  const title = text('MCP 回传：试点检查清单', 'MCP return: pilot checklist');
  await openMyAgent(browser);
  // Decision R3: no name, duration or scope to choose; one press issues access.
  assert.equal(
    await browser.ev(`document.querySelectorAll('.ag-root input, .ag-root select').length`),
    0,
  );
  // Access may already be waiting from earlier in the practice; otherwise one press issues it.
  if (await browser.ev(`!!document.querySelector('.ag-cta button')`))
    await browser.click('.ag-cta button');
  await phase(browser, 'waiting');
  await waitFor(browser, `!!document.querySelector('.ag-connect .ag-cmd .ag-copy')`);
  assert.ok(
    (await browser.ev(`document.querySelector('.ag-connect').innerText`)).includes(
      text('到明天这个时候都有效', 'works until this time tomorrow'),
    ),
  );
  const firstGrant = await issuedId(browser);
  const command = await copied(browser, '.ag-connect .ag-cmd .ag-copy');
  const endpoint = command.match(/rolecraft '([^']+\/mcp)'/)?.[1];
  const token = command.match(/Bearer ([^']+)'/)?.[1];
  assert.ok(endpoint?.startsWith(`${new URL(await browser.ev('location.href')).origin}/api/`));
  assert.ok(token && token.length >= 32);
  // The command starts Claude Code with its first request.
  assert.ok(command.includes(text('读 RoleCraft 里的委托', 'Read the brief in RoleCraft')));
  // Other clients get the same endpoint and header as a config.
  await browser.click('.ag-connect .ag-seg button', 2);
  const config = JSON.parse(await copied(browser, '.ag-connect .ag-cmd .ag-copy'));
  assert.equal(config.mcpServers.rolecraft.url, endpoint);
  assert.equal(config.mcpServers.rolecraft.headers.Authorization, `Bearer ${token}`);
  await browser.click('.ag-connect .ag-seg button', 0);
  // Copying fetched the token; it is still nowhere in the page or its storage.
  assert.equal(
    await browser.ev(`document.documentElement.outerHTML.includes(${JSON.stringify(token)})`),
    false,
  );
  assert.equal(
    await browser.ev(`JSON.stringify({...localStorage}).includes(${JSON.stringify(token)})`),
    false,
  );
  await shot('mcp-card');
  const agent = new McpHttpClient(endpoint, token);
  const discovered = await agent.modern('server/discover');
  assert.ok(discovered.body.result.supportedVersions.includes(MODERN));
  const sessionId = await browser.ev('window.PracticeLive.store.active().id');
  let seen = (await agent.call('observation', {})).result.as_of;
  // M3: the agent cites a passage it read; the returned work shows that passage.
  const read = await agent.call('read_material', {
    command: {
      schema_version: 2,
      request_id: crypto.randomUUID(),
      operation: 'read_material',
      payload: {
        tool: 'read_material',
        material: {
          schema_version: 2,
          session_id: sessionId,
          kind: 'material',
          object_id: 'brief',
          version: 1,
        },
      },
      expected_version: seen.business_seq,
      expected_workspace_revision: seen.workspace_revision,
    },
  });
  const cited = (read.result?.fragments ?? read.fragments).find((part) => part.ref?.quote).ref;
  seen = (await agent.call('observation', {})).result.as_of;
  await agent.call('work_products.create', {
    command: {
      schema_version: 2,
      request_id: crypto.randomUUID(),
      operation: 'work_products.create',
      payload: {
        kind: 'text',
        purpose: 'exploration',
        title,
        content: text('先核对容量和索引更新。', 'Check capacity and index updates first.'),
        evidence_refs: [cited],
      },
      expected_version: seen.business_seq,
      expected_workspace_revision: seen.workspace_revision,
    },
  });
  assert.equal(await agent.legacyHandshake(), LEGACY);
  // The page saw it connect, read and hand back: the stream lists the calls by their real
  // tool names and the returned work arrives as a paper waiting for review.
  await phase(browser, 'connected');
  await waitFor(browser, `!!document.querySelector('.ag-line[data-tool="read_material"]')`);
  const awaiting = text('等你检查', 'Waiting for your check');
  await waitFor(
    browser,
    `[...document.querySelectorAll('.ag-paper')].some((paper) =>
      paper.innerText.includes(${JSON.stringify(title)}) && paper.innerText.includes(${JSON.stringify(awaiting)}))`,
  );
  await shot('mcp-returned');
  // Opening the returned work shows the cited passage in its own words.
  await browser.ev(`(() => {
    const paper = [...document.querySelectorAll('.ag-paper')]
      .find((sheet) => sheet.innerText.includes(${JSON.stringify(title)}));
    [...paper.querySelectorAll('button')]
      .find((button) => button.textContent === ${JSON.stringify(text('打开', 'Open'))})
      .click();
    return true;
  })()`);
  await waitFor(browser, `!!document.querySelector('#sheet[open] .evidence-quotes blockquote')`);
  assert.equal(
    await browser.ev(`document.querySelector('#sheet .evidence-quotes blockquote').textContent`),
    cited.quote,
  );
  await shot('mcp-returned-passage');
  await browser.ev(`document.querySelector('#sheet [data-action="close"]').click()`);
  await waitFor(browser, `!document.querySelector('#sheet').open`);
  // Leaving the practice withdraws the token from the page; the agent itself stays connected.
  await browser.click('button[data-action="menu"][data-menu="more"]');
  await browser.click('[data-action="to-entry"]');
  await waitFor(browser, `!!document.querySelector('.case-hero [data-action="resume-attempt"]')`);
  await browser.click('.case-hero [data-action="resume-attempt"]');
  await waitFor(browser, `location.hash === '#/work'`);
  await openMyAgent(browser);
  assert.equal(await offeredSecret(browser), null);
  await phase(browser, 'connected');
  // Copying again issues a fresh grant. Revoked in another tab, that grant is never handed out
  // again: the next copy reads the grant list first and issues another.
  await browser.clickText(text('再看一次连接命令', 'Show the command again'));
  await waitFor(browser, `!!document.querySelector('.ag-connect .ag-cmd .ag-copy')`);
  const second = (await copied(browser, '.ag-connect .ag-cmd .ag-copy')).match(
    /Bearer ([^']+)'/,
  )?.[1];
  const elsewhere = await issuedId(browser);
  assert.ok(second && elsewhere && elsewhere !== firstGrant);
  assert.equal(await revokeOutsideThisPage(browser, elsewhere), 200);
  const third = (await copied(browser, '.ag-connect .ag-cmd .ag-copy')).match(
    /Bearer ([^']+)'/,
  )?.[1];
  assert.ok(third && third !== second);
  assert.notEqual(await issuedId(browser), elsewhere);
  // Revoking the connected agent's grant: its token stops working and the page shows it gone.
  assert.equal(await revokeOutsideThisPage(browser, firstGrant), 200);
  const denied = await agent.modern('tools/list');
  assert.equal(denied.status, 401);
  assert.equal(denied.body.error.data.code, 'credential_revoked_or_invalid');
  await phase(browser, 'idle', 20000);
  assert.ok(
    (await browser.ev(`document.querySelector('.ag-rig').innerText`)).includes(
      text('最近一次', 'Last seen'),
    ),
  );
}
