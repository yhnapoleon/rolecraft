// Agent connection card on the normal entry: create access with returned work, read the endpoint
// and token from the card's own copy action, return work with a scripted Streamable HTTP client,
// then see it waiting for review in the Agent panel. No real agent or model is involved.
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

/** The card's own copy action, captured instead of the system clipboard. */
async function copied(browser, action) {
  await browser.ev(`(() => {
    window.regressionCopied = null;
    Object.defineProperty(navigator.clipboard, 'writeText', {
      configurable: true,
      value: async (text) => { window.regressionCopied = text; },
    });
    return true;
  })()`);
  await browser.click(`[data-connection-action="${action}"]`);
  await waitFor(browser, 'typeof window.regressionCopied === "string"');
  return browser.ev('window.regressionCopied');
}

async function ensureChecked(browser, label) {
  const selector = `[aria-label="${label}"]`;
  if (!(await browser.ev(`document.querySelector(${JSON.stringify(selector)}).checked`)))
    await browser.click(selector);
}

export async function connectAgentOverMcp(context) {
  const { browser, text, shot } = context;
  const agentName = text('MCP 连接卡', 'MCP connection card');
  const title = text('MCP 回传：试点检查清单', 'MCP return: pilot checklist');
  await browser.click('.rail-tabs [data-tab="agent"]');
  await waitFor(
    browser,
    `(() => {
      const input = document.querySelector('.agent-v4-grant [name="agentName"]');
      return !!input && !input.disabled;
    })()`,
  );
  // The scope chooser names what it lists.
  assert.ok(
    (await browser.text('.agent-v4-grant button')).includes(
      text('选择资料范围', 'Choose documents'),
    ),
  );
  await browser.type('[name="agentName"]', agentName);
  await ensureChecked(browser, text('允许操作与回传作品', 'Allow actions and returned work'));
  await ensureChecked(
    browser,
    text('授权整个工作区的可见内容', 'Allow visible content across the workspace'),
  );
  await browser.submit('.agent-v4-grant');
  await waitFor(
    browser,
    `document.querySelector('[data-connection-card]')?.innerText.includes(${JSON.stringify(agentName)})`,
  );
  const region = await browser.ev(`document.querySelector('[data-v4-region="agent"]').innerText`);
  assert.ok(
    region.includes(
      text(
        '授权已创建，按下方连接卡接入你的 Agent。',
        'Access created. Connect your agent with the card below.',
      ),
    ),
  );
  assert.ok(
    region.includes(
      text(
        '令牌会写进你的 Agent 配置和命令历史；最长 60 分钟后失效，可随时撤销。',
        'The token is written to your agent’s config and command history. It expires within 60 minutes, and you can revoke it any time.',
      ),
    ),
  );
  const command = await copied(browser, 'copy-claude');
  const endpoint = command.match(/rolecraft '([^']+\/mcp)'/)?.[1];
  const token = command.match(/Bearer ([^']+)'/)?.[1];
  assert.ok(endpoint?.startsWith(`${new URL(await browser.ev('location.href')).origin}/api/`));
  assert.ok(token && token.length >= 32);
  assert.equal(await copied(browser, 'copy-endpoint'), endpoint);
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
  const seen = (await agent.call('observation', {})).result.as_of;
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
      },
      expected_version: seen.business_seq,
      expected_workspace_revision: seen.workspace_revision,
    },
  });
  assert.equal(await agent.legacyHandshake(), LEGACY);
  await clickReady(browser, text('刷新授权与记录', 'Refresh access and records'));
  const awaiting = text('此版本待你检查', 'This version awaits your review');
  await waitFor(
    browser,
    `[...document.querySelectorAll('.agent-v4-work-row')].some((row) =>
      row.innerText.includes(${JSON.stringify(title)}) && row.innerText.includes(${JSON.stringify(awaiting)}))`,
  );
  await shot('mcp-returned');
  await browser.click('[data-connection-action="done"]');
  await waitFor(browser, `!document.querySelector('[data-connection-card]')`);
  await browser.ev(`(() => {
    const row = [...document.querySelectorAll('.agent-v4-access-row')]
      .find((line) => line.innerText.includes(${JSON.stringify(agentName)}));
    row.querySelector('button[data-agent-write="delegations.revoke"]').click();
    return true;
  })()`);
  const revoked = text('已撤销', 'Revoked');
  await waitFor(
    browser,
    `[...document.querySelectorAll('.agent-v4-access-row')].some((line) =>
      line.innerText.includes(${JSON.stringify(agentName)}) && line.innerText.includes(${JSON.stringify(revoked)}))`,
  );
  const denied = await agent.modern('tools/list');
  assert.equal(denied.status, 401);
  assert.equal(denied.body.error.data.code, 'credential_revoked_or_invalid');
}
