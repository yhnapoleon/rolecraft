import { describe, expect, it } from 'vitest';
import {
  accessDuration,
  claudeCodeCommand,
  codexCommand,
  connectionText,
  createConnectionKeeper,
  mcpEndpoint,
  renderAgentConnection,
} from './agent-connection';

const TOKEN = 'a'.repeat(64);
const HINT =
  '令牌会写进你的 Agent 配置和命令历史，授权时长为 23 小时 55 分钟，可随时撤销；点“完成”或离开练习后，这里不再提供。';
const ENDPOINT = 'http://127.0.0.1:20020/api/sessions/s1/mcp';

describe('agent connection commands', () => {
  it('derives the displayed lifetime from the issued access duration', () => {
    expect(accessDuration('zh')).toBe('23 小时 55 分钟');
    expect(accessDuration('en')).toBe('23 h 55 min');
  });
  it('builds the endpoint on the page origin through the API proxy', () => {
    expect(mcpEndpoint('http://127.0.0.1:20020', 's1')).toBe(ENDPOINT);
    expect(mcpEndpoint('http://localhost:18560/', 'a/b')).toBe(
      'http://localhost:18560/api/sessions/a%2Fb/mcp',
    );
  });
  it('gives Claude Code a local-scope HTTP server with the token in its header', () => {
    expect(claudeCodeCommand(ENDPOINT, TOKEN)).toBe(
      `claude mcp remove rolecraft -s user >/dev/null 2>&1; claude mcp add -s user --transport http rolecraft '${ENDPOINT}' --header 'Authorization: Bearer ${TOKEN}' >/dev/null && { claude mcp get rolecraft 2>&1 | grep -m1 'Status:' || true; }`,
    );
  });
  it('makes one handshake after setup without printing the token', () => {
    const claude = claudeCodeCommand(ENDPOINT, TOKEN);
    // The handshake's output is narrowed to its Status line (the full output repeats headers).
    expect(claude).toContain("claude mcp get rolecraft 2>&1 | grep -m1 'Status:'");
    const codex = codexCommand(ENDPOINT, TOKEN);
    expect(codex).toContain('"method": "initialize"');
    expect(codex).toContain('urllib.request.urlopen(request, timeout=10)');
    expect(codex).not.toMatch(/print\([^)]*argv\[2\]/);
  });
  it('starts Codex connected, with the token only in its environment', () => {
    const command = codexCommand(ENDPOINT, TOKEN);
    expect(command).toContain('config.toml.rolecraft-backup-');
    expect(command).toContain('http_headers');
    expect(command).toContain(`'${ENDPOINT}' '${TOKEN}'`);
    expect(command).not.toContain('bearer_token_env_var');
    expect(command).not.toContain('codex -c');
  });
  it('quotes values for the shell so a quote cannot end the argument', () => {
    expect(claudeCodeCommand("http://h/it's", "to'ken")).toContain(
      `'http://h/it'\\''s' --header 'Authorization: Bearer to'\\''ken'`,
    );
  });
  it('copies exactly what each action names', () => {
    expect(connectionText('copy-endpoint', ENDPOINT, TOKEN)).toBe(ENDPOINT);
    expect(connectionText('copy-token', ENDPOINT, TOKEN)).toBe(TOKEN);
    expect(connectionText('copy-claude', ENDPOINT, TOKEN)).toBe(claudeCodeCommand(ENDPOINT, TOKEN));
    expect(connectionText('copy-codex', ENDPOINT, TOKEN)).toBe(codexCommand(ENDPOINT, TOKEN));
  });
});

/** The few DOM calls the card makes, recorded for inspection. */
class Node {
  className = '';
  textContent = '';
  hidden = false;
  type = '';
  value = '';
  readOnly = false;
  rows = 0;
  selected = false;
  children: Node[] = [];
  attributes: Record<string, string> = {};
  dataset: Record<string, string> = {};
  listeners: Record<string, (() => unknown)[]> = {};
  constructor(
    readonly tagName: string,
    readonly ownerDocument: { createElement(tag: string): Node },
  ) {}
  append(...nodes: (Node | string)[]) {
    for (const item of nodes) {
      if (typeof item !== 'string') this.children.push(item);
      else {
        const text = new Node('#text', this.ownerDocument);
        text.textContent = item;
        this.children.push(text);
      }
    }
  }
  replaceChildren(...nodes: Node[]) {
    this.children = [];
    this.append(...nodes);
  }
  setAttribute(name: string, value: string) {
    this.attributes[name] = value;
  }
  addEventListener(type: string, listener: () => unknown) {
    this.listeners[type] = [...(this.listeners[type] ?? []), listener];
  }
  focus() {}
  select() {
    this.selected = true;
  }
  all(): Node[] {
    return this.children.flatMap((child) => [child, ...child.all()]);
  }
}
const documentStub = { createElement: (tag: string): Node => new Node(tag, documentStub) };
const visible = (root: Node) =>
  JSON.stringify(
    [root, ...root.all()].map((n) => [n.textContent, n.value, n.attributes, n.dataset]),
  );
const only = (nodes: Node[], what: string) => {
  const [node] = nodes;
  if (!node) throw new Error(`missing ${what}`);
  return node;
};
const action = (root: Node, name: string) =>
  only(
    root.all().filter((n) => n.dataset.connectionAction === name),
    name,
  );
const click = async (node: Node) => {
  for (const listener of node.listeners.click ?? []) await listener();
};

function fixture(offered = true) {
  const calls: string[] = [];
  const host = {
    snapshot: () => ({ session: { sessionId: 's1' } }),
    issuedDelegation: () =>
      offered ? { label: 'Helper', expiresAt: '2099-01-01T08:30:00.000Z' } : null,
    connectionSecret: () => {
      calls.push('secret');
      return offered ? { sessionId: 's1', token: TOKEN } : null;
    },
    connectionConfig: (apiUrl: string) => {
      calls.push('config');
      return offered ? { api_url: apiUrl, session_id: 's1', token: TOKEN } : null;
    },
    dismissConnection: () => {
      calls.push('dismiss');
      offered = false;
    },
  };
  const copied: string[] = [];
  const deps = {
    origin: 'http://127.0.0.1:20020',
    notify: (text: string) => calls.push(`notify:${text}`),
    download: (data: unknown, name: string) =>
      calls.push(`download:${name}${JSON.stringify(data)}`),
    refresh: () => calls.push('refresh'),
    schedule: () => {},
    clipboard: {
      writeText: async (text: string) => {
        copied.push(text);
      },
    },
  };
  const target = new Node('div', documentStub);
  return { host, deps, target, calls, copied };
}

describe('agent connection card', () => {
  it('renders nothing once the grant is no longer offered', () => {
    const { host, deps, target } = fixture(false);
    renderAgentConnection(target as never, host, deps);
    expect(target.children).toEqual([]);
  });
  it('shows the endpoint and masked commands, never the token', () => {
    const { host, deps, target, calls } = fixture();
    renderAgentConnection(target as never, host, deps);
    const text = visible(target);
    expect(text).toContain(ENDPOINT);
    expect(text).toContain('Bearer ••••••');
    expect(text).toContain(HINT);
    expect(text).not.toContain(TOKEN);
    expect(calls).toEqual([]);
    for (const name of [
      'copy-endpoint',
      'copy-claude',
      'copy-codex',
      'copy-token',
      'download-config',
      'done',
    ])
      expect(action(target, name)).toBeDefined();
  });
  it('asks the host for the token only when the person copies', async () => {
    const { host, deps, target, calls, copied } = fixture();
    renderAgentConnection(target as never, host, deps);
    await click(action(target, 'copy-claude'));
    expect(copied).toEqual([claudeCodeCommand(ENDPOINT, TOKEN)]);
    expect(calls).toEqual(['secret', 'notify:已复制']);
    expect(visible(target)).not.toContain(TOKEN);
  });
  it('offers the text for manual selection when the clipboard is blocked', async () => {
    const { host, deps, target } = fixture();
    deps.clipboard.writeText = async () => {
      throw new Error('blocked');
    };
    renderAgentConnection(target as never, host, deps);
    await click(action(target, 'copy-codex'));
    const area = only(
      target.all().filter((n) => n.tagName === 'textarea'),
      'textarea',
    );
    expect(area.value).toBe(codexCommand(ENDPOINT, TOKEN));
    expect(area.readOnly && area.selected).toBe(true);
  });
  it('downloads the config, then hides everything when the person is done', async () => {
    const { host, deps, target, calls } = fixture();
    renderAgentConnection(target as never, host, deps);
    await click(action(target, 'download-config'));
    expect(calls[0]).toBe('config');
    expect(calls[1]).toContain('download:rolecraft-agent-config.json');
    await click(action(target, 'done'));
    expect(calls.slice(-3)).toEqual(['dismiss', 'notify:连接信息已收起。', 'refresh']);
    await click(action(target, 'copy-token'));
    expect(calls.slice(-3)).toEqual(['secret', expect.stringContaining('notify:'), 'refresh']);
  });
});

describe('agent connection offer while the practice is on screen', () => {
  it('says in one sentence where the token goes and when the card stops offering it', () => {
    const { host, deps, target } = fixture();
    renderAgentConnection(target as never, host, deps);
    // The first screen is the card's own lines; "Other clients" stays folded.
    const card = only(target.children, 'card');
    const hints = card.children
      .filter((n) => n.tagName === 'p' && n.textContent.includes('令牌'))
      .map((n) => n.textContent);
    expect(hints).toEqual([HINT]);
  });
  it('withdraws the offer when the person leaves the practice or switches to another', () => {
    const dismissed: string[] = [];
    const offering = (name: string) => {
      let open = true;
      return {
        issuedDelegation: () => (open ? { label: name, expiresAt: '2099-01-01T00:00:00Z' } : null),
        dismissConnection: () => {
          dismissed.push(name);
          open = false;
        },
        subscribe: () => () => {},
      };
    };
    const keeper = createConnectionKeeper(() => {});
    const first = offering('first');
    keeper.track(first);
    keeper.track(first);
    expect(dismissed).toEqual([]);
    keeper.track(null);
    expect(dismissed).toEqual(['first']);
    const second = offering('second');
    const third = offering('third');
    keeper.track(second);
    keeper.track(third);
    expect(dismissed).toEqual(['first', 'second']);
    keeper.track(third);
    expect(dismissed).toEqual(['first', 'second']);
  });
  it('re-renders once when the practice on screen stops offering its token by itself', () => {
    let listeners: (() => void)[] = [];
    const notify = () => {
      for (const listener of listeners) listener();
    };
    let open = true;
    const host = {
      issuedDelegation: () => (open ? { label: 'h', expiresAt: '2099-01-01T00:00:00Z' } : null),
      dismissConnection: () => {
        open = false;
      },
      subscribe: (listener: () => void) => {
        listeners = [...listeners, listener];
        return () => {
          listeners = listeners.filter((item) => item !== listener);
        };
      },
    };
    const renders: string[] = [];
    const keeper = createConnectionKeeper(() => renders.push('render'));
    keeper.track(host);
    notify();
    expect(renders).toEqual([]);
    // Revoked in another tab and read from the grant list, or expired: no page render follows.
    open = false;
    notify();
    expect(renders).toEqual(['render']);
    notify();
    expect(renders).toEqual(['render']);
    // Leaving the practice stops listening to its host.
    keeper.track(null);
    expect(listeners).toEqual([]);
  });
});
