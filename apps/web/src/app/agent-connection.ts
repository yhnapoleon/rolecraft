// Connection card for the Agent access issued on this page: the endpoint and one-step setup
// commands for Claude Code and Codex. The token stays in the host's memory; the card shows it
// masked and asks the host for it only when the person copies or downloads.
import { locale, T } from './i18n';

const SERVER = 'rolecraft';
const TOKEN_VARIABLE = 'ROLECRAFT_MCP_TOKEN';

export type ConnectionAction = 'copy-endpoint' | 'copy-claude' | 'copy-codex' | 'copy-token';

/** One shell word: single quotes, with any single quote closed, escaped and reopened. */
const shell = (value: string) => `'${value.replaceAll("'", `'\\''`)}'`;

/** The MCP endpoint through this page's API proxy, as the existing config file uses. */
export function mcpEndpoint(origin: string, sessionId: string) {
  return `${origin.replace(/\/+$/, '')}/api/sessions/${encodeURIComponent(sessionId)}/mcp`;
}

/** Claude Code: replace any earlier entry, then add the HTTP server in the local scope only. */
export function claudeCodeCommand(endpoint: string, token: string) {
  return `claude mcp remove ${SERVER} -s local >/dev/null 2>&1; claude mcp add -s local --transport http ${SERVER} ${shell(endpoint)} --header ${shell(`Authorization: Bearer ${token}`)}`;
}

/** Codex: start a session already connected; the token lives only in that process. */
export function codexCommand(endpoint: string, token: string) {
  const server = `mcp_servers.${SERVER}={ url = ${JSON.stringify(endpoint)}, bearer_token_env_var = "${TOKEN_VARIABLE}" }`;
  return `${TOKEN_VARIABLE}=${shell(token)} codex -c ${shell(server)}`;
}

export function connectionText(action: ConnectionAction, endpoint: string, token: string) {
  if (action === 'copy-endpoint') return endpoint;
  if (action === 'copy-token') return token;
  return action === 'copy-claude'
    ? claudeCodeCommand(endpoint, token)
    : codexCommand(endpoint, token);
}

const MASK = '••••••';
const CONFIG_FILE = 'rolecraft-agent-config.json';
type CardAction = ConnectionAction | 'download-config' | 'done';

/** What the card needs from the page's data host. Only the copy and download paths see the token. */
export type ConnectionHost = {
  snapshot(): { session?: { sessionId: string } | null };
  issuedDelegation(): { label: string; expiresAt: string } | null;
  connectionSecret(): { sessionId: string; token: string } | null;
  connectionConfig(apiUrl: string): unknown;
  dismissConnection(): void;
};
export type ConnectionDeps = {
  origin: string;
  notify(text: string): void;
  download(data: unknown, name: string): void;
  /** Re-render the card from the host: it disappears once nothing is offered. */
  refresh(): void;
  schedule?(task: () => void, milliseconds: number): void;
  clipboard?: { writeText(text: string): Promise<void> };
};

const goneText = () =>
  T(
    '这次授权的连接信息已收起；需要连接请重新授权。',
    'This access is no longer offered here. Create a new one to connect.',
  );

/** Renders the card into the host-owned node; text only, so nothing is parsed as markup. */
export function renderAgentConnection(
  target: HTMLElement,
  host: ConnectionHost | null,
  deps: ConnectionDeps,
) {
  target.replaceChildren();
  const issued = host?.issuedDelegation();
  const sessionId = host?.snapshot().session?.sessionId;
  if (!host || !issued || !sessionId) return;
  const endpoint = mcpEndpoint(deps.origin, sessionId);
  const doc = target.ownerDocument;
  const node = <K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text = '') => {
    const element = doc.createElement(tag);
    element.className = className;
    element.textContent = text;
    return element;
  };
  const button = (label: string, action: CardAction, className = 'btn small quiet') => {
    const element = node('button', className, label);
    element.type = 'button';
    element.dataset.connectionAction = action;
    element.addEventListener('click', () => run(action));
    return element;
  };
  const code = (text: string, label: string) => {
    const block = node('pre', 'agent-connection-code');
    block.setAttribute('aria-label', label);
    block.append(node('code', '', text));
    return block;
  };
  const field = (title: string, ...parts: HTMLElement[]) => {
    const section = node('div', 'agent-connection-field');
    section.append(node('p', 'agent-connection-key', title), ...parts);
    return section;
  };
  const fallback = node('div', 'agent-connection-fallback');
  fallback.hidden = true;

  async function run(action: CardAction) {
    if (action === 'done') {
      host?.dismissConnection();
      deps.notify(T('连接信息已收起。', 'Connection details hidden.'));
      deps.refresh();
      return;
    }
    if (action === 'download-config') {
      const config = host?.connectionConfig(`${deps.origin}/api`);
      if (!config) {
        deps.notify(goneText());
        deps.refresh();
        return;
      }
      deps.download(config, CONFIG_FILE);
      deps.notify(
        T('连接配置已交给浏览器下载。', 'The connection config was handed to the browser.'),
      );
      return;
    }
    const secret = action === 'copy-endpoint' ? null : host?.connectionSecret();
    if (action !== 'copy-endpoint' && !secret) {
      deps.notify(goneText());
      deps.refresh();
      return;
    }
    const text = connectionText(action, endpoint, secret?.token ?? '');
    try {
      await (deps.clipboard ?? navigator.clipboard).writeText(text);
      deps.notify(T('已复制', 'Copied'));
    } catch {
      // Shown only because the person asked to copy and the browser refused.
      const area = node('textarea', 'textarea agent-connection-manual');
      area.readOnly = true;
      area.rows = 3;
      area.value = text;
      area.setAttribute('aria-label', T('要复制的内容', 'Text to copy'));
      fallback.replaceChildren(
        node(
          'p',
          'meta',
          T(
            '浏览器没有允许复制，请手动选中下面的内容。',
            'The browser blocked copying. Select the text below.',
          ),
        ),
        area,
      );
      fallback.hidden = false;
      area.focus();
      area.select();
    }
  }

  const time = new Date(issued.expiresAt).toLocaleTimeString(
    locale() === 'en' ? 'en-US' : 'zh-CN',
    { hour: '2-digit', minute: '2-digit' },
  );
  const card = node('div', 'agent-config agent-connection');
  card.setAttribute('role', 'status');
  card.dataset.connectionCard = '';
  const title = node('p', 'agent-connection-title');
  title.append(node('b', '', T('授权已创建', 'Access created')));
  if (issued.label) title.append(` · ${issued.label}`);
  const endpointRow = node('div', 'agent-connection-row');
  endpointRow.append(
    code(endpoint, T('连接地址', 'Endpoint')),
    button(T('复制', 'Copy'), 'copy-endpoint'),
  );
  const more = node('details', 'agent-connection-more');
  more.append(
    node('summary', '', T('其他客户端', 'Other clients')),
    node(
      'p',
      'meta',
      T(
        '其他支持 Streamable HTTP 的 MCP 客户端：地址同上，请求头 Authorization: Bearer <令牌>。Codex 桌面版在 ~/.codex/config.toml 的 [mcp_servers.rolecraft] 里写 url 和 http_headers。',
        'Other MCP clients with Streamable HTTP: same endpoint, header Authorization: Bearer <token>. The Codex desktop app reads url and http_headers from [mcp_servers.rolecraft] in ~/.codex/config.toml.',
      ),
    ),
    button(T('复制令牌', 'Copy token'), 'copy-token'),
    node(
      'p',
      'meta',
      T(
        '配置文件给本机 Python 方式用：先 chmod 600 <文件>，再运行 python -m career_lab.mcp --config <文件>。',
        'The config file is for the local Python client: run chmod 600 <file>, then python -m career_lab.mcp --config <file>.',
      ),
    ),
  );
  const actions = node('div', 'row-actions');
  actions.append(
    button(T('下载配置文件', 'Download config file'), 'download-config'),
    button(T('完成', 'Done'), 'done', 'btn small primary'),
  );
  card.append(
    title,
    node('p', 'meta', T(`有效至 ${time}`, `Valid until ${time}`)),
    field(T('连接地址', 'Endpoint'), endpointRow),
    field(
      'Claude Code',
      code(
        claudeCodeCommand(endpoint, MASK),
        T('Claude Code 命令，令牌已隐藏', 'Claude Code command, token hidden'),
      ),
      node(
        'p',
        'meta',
        T('添加后启动或重启 Claude Code。', 'Start or restart Claude Code after adding.'),
      ),
      button(T('复制命令', 'Copy command'), 'copy-claude'),
    ),
    field(
      'Codex',
      code(
        codexCommand(endpoint, MASK),
        T('Codex 命令，令牌已隐藏', 'Codex command, token hidden'),
      ),
      node(
        'p',
        'meta',
        T(
          '在本终端直接启动已连好的 Codex，不写配置文件。',
          'Starts Codex here, already connected; nothing is saved to its config.',
        ),
      ),
      button(T('复制命令', 'Copy command'), 'copy-codex'),
    ),
    node(
      'p',
      'meta',
      T(
        '令牌会写进你的 Agent 配置和命令历史，最长 60 分钟失效，可随时撤销；点“完成”或离开练习后，这里不再提供。',
        'The token goes into your agent’s config and command history, expires within 60 minutes and can be revoked any time; after Done or leaving the practice, it is no longer offered here.',
      ),
    ),
    more,
    actions,
    fallback,
  );
  target.append(card);
  const remaining = Date.parse(issued.expiresAt) - Date.now();
  if (remaining > 0)
    (deps.schedule ?? ((task, ms) => setTimeout(task, ms)))(
      deps.refresh,
      Math.min(remaining + 100, 2_147_483_647),
    );
}

type OfferingHost = Pick<ConnectionHost, 'issuedDelegation' | 'dismissConnection'> & {
  subscribe(listener: () => void): () => void;
};

/** The card offers the token only while its practice is on screen. */
export function createConnectionKeeper(onWithdrawn: () => void) {
  let offering: OfferingHost | null = null;
  let watched: OfferingHost | null = null;
  let unwatch = () => {};
  return {
    /** After each render: the host of the practice on screen, or null outside any practice. */
    track(host: OfferingHost | null) {
      const previous = offering;
      offering = host?.issuedDelegation() ? host : null;
      if (host !== watched) {
        unwatch();
        watched = host;
        // The host can stop offering without any page render (revoked elsewhere and read from
        // the grant list, or expired), and idle polls no longer notify the page: re-render once.
        unwatch = host
          ? host.subscribe(() => {
              if (offering !== host || host.issuedDelegation()) return;
              offering = null;
              onWithdrawn();
            })
          : () => {};
      }
      // Leaving the practice or switching to another one withdraws the earlier offer for good.
      // Recorded first: the dismissal re-renders, which may call track() again.
      if (previous && previous !== host) previous.dismissConnection();
    },
  };
}
