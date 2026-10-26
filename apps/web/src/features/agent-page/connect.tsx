// Desktop and terminal setup share persistent client configuration. Secrets are fetched only
// for an explicit copy/download; connection status comes from the server's activity feed.
import { Copy, Download } from 'lucide-react';
import { useEffect, useState } from 'react';
import {
  accessDuration,
  claudeCodeCommand,
  codexCommand,
  mcpEndpoint,
} from '../../app/agent-connection';
import type { AgentConnection } from '../../contracts-v2';
import { Button, type ButtonState } from '../../ui-kit';
import type { Pair } from './index';
import { clientName } from './verbs';

export type Client = 'claude-desktop' | 'codex-desktop' | 'claude' | 'codex' | 'other';
const t = (lang: 'zh' | 'en', zh: string, en: string) => (lang === 'en' ? en : zh);
const shell = (value: string) => `'${value.replaceAll("'", `'\\''`)}'`;
const MASK = '••••••••';
export const CLIENTS: [Client, Pair][] = [
  ['claude-desktop', ['Claude 桌面 App（Code）', 'Claude desktop app (Code)']],
  ['codex-desktop', ['Codex 桌面 App', 'Codex desktop app']],
  ['claude', ['Claude Code 命令行', 'Claude Code CLI']],
  ['codex', ['Codex 命令行', 'Codex CLI']],
  ['other', ['其他 · 配置文件', 'Other · config file']],
];

export function commandFor(client: Client, endpoint: string, token: string, opener: string) {
  if (client === 'claude-desktop') return claudeCodeCommand(endpoint, token);
  if (client === 'codex-desktop') return codexCommand(endpoint, token);
  if (client === 'claude')
    return `${claudeCodeCommand(endpoint, token)} && claude ${shell(opener)}`;
  if (client === 'codex') return `${codexCommand(endpoint, token)} && codex ${shell(opener)}`;
  return JSON.stringify(
    {
      mcpServers: {
        rolecraft: { type: 'http', url: endpoint, headers: { Authorization: `Bearer ${token}` } },
      },
    },
    null,
    2,
  );
}

export function connectionLabel(
  connection: AgentConnection | undefined,
  lang: 'zh' | 'en',
  reachable = false,
) {
  if (connection?.state === 'connected' && reachable)
    return t(lang, '已连通 · 配置已写好', 'Reachable · setup written');
  if (connection?.state === 'connected') {
    const name = connection.client?.trim();
    return name
      ? t(lang, `已连接 · 来自 ${clientName(name)}`, `Connected · from ${clientName(name)}`)
      : t(lang, '已连接', 'Connected');
  }
  if (connection?.state === 'idle')
    return t(lang, '已连接过 · 当前空闲', 'Previously connected · idle');
  return t(lang, '等待首次调用', 'Waiting for the first call');
}

/** Said while only the handshake arrived. An open session never picks up a newly added server
 * (the client's own behaviour), so this never suggests it works without a restart. */
export function reachableHint(lang: 'zh' | 'en', client: Client) {
  if (client === 'codex' || client === 'codex-desktop')
    return t(
      lang,
      '已经开着的 Codex 对话读不到新连接，要新开对话（仍没有就完全退出再打开 Codex）；新开的对话直接能用。',
      'An open Codex conversation does not see the new connection: start a new one (if it is still missing, quit and reopen Codex). New conversations can use it right away.',
    );
  return t(
    lang,
    '已经开着的 Claude Code 要重启，或者在 /mcp 里重连，才能用上；新开的会话直接能用。',
    'A Claude Code session that was already open must restart or reconnect in /mcp to use it; new sessions can use it right away.',
  );
}

/** After this long with no call, the waiting line turns into a short check. */
export const SLOW_MS = 2 * 60_000;

/** Whether a real call arrived after the setup command was copied. */
function arrived(connection: AgentConnection | undefined, copiedAt: number) {
  if (connection?.state === 'connected') return true;
  const seen = connection?.last_seen ? Date.parse(connection.last_seen) : NaN;
  return connection?.state === 'idle' && seen >= copiedAt;
}

/** The line between copying the setup and the agent's first real call; null once it arrived. */
export function waitingHint(
  lang: 'zh' | 'en',
  client: Client,
  copiedAt: number | null,
  now: number,
  connection?: AgentConnection,
): { slow: boolean; text: string } | null {
  if (copiedAt === null || arrived(connection, copiedAt)) return null;
  if (now - copiedAt < SLOW_MS)
    return {
      slow: false,
      text: t(
        lang,
        '已复制连接命令，正在等它的第一次调用。照下面三步做完，这里会亮绿灯。',
        'Setup command copied. Waiting for its first call: finish the three steps below and this turns green.',
      ),
    };
  const check =
    client === 'codex' || client === 'codex-desktop'
      ? t(
          lang,
          '在终端运行 codex mcp list，看 rolecraft 是否已列出并启用；',
          'Run codex mcp list in Terminal and check that rolecraft is listed and enabled;',
        )
      : client === 'other'
        ? t(
            lang,
            '在客户端的 MCP 设置里看 rolecraft 是否已启用；',
            'Check that rolecraft is enabled in your client’s MCP settings;',
          )
        : t(
            lang,
            '在终端运行 claude mcp list，看 rolecraft 是否显示 Connected；',
            'Run claude mcp list in Terminal and check that rolecraft shows Connected;',
          );
  return {
    slow: true,
    text:
      t(lang, '两分钟还没收到调用。', 'No call after two minutes. ') +
      check +
      t(
        lang,
        '正常的话，新开一个会话（已开着的要重启，或在 /mcp 里重连），再把第 3 步那句话发给它。',
        ' if it is, start a new session (restart one that was already open, or reconnect in /mcp) and send it the request in step 3.',
      ),
  };
}

export function CopyKey({
  label,
  getText,
  lang,
  onFail,
  onCopied,
}: {
  label: string;
  getText: () => Promise<string | null>;
  lang: 'zh' | 'en';
  onFail?: (text: string) => void;
  onCopied?: () => void;
}) {
  const [state, setState] = useState<ButtonState>('idle');
  return (
    <Button
      variant="icon"
      className="ag-copy"
      aria-label={label}
      title={label}
      state={state}
      icon={<Copy size={14} strokeWidth={1.6} />}
      disabled={state === 'loading'}
      onClick={async () => {
        setState('loading');
        let text: string | null = null;
        try {
          text = await getText();
          if (!text) {
            setState('idle');
            return;
          }
          await navigator.clipboard.writeText(text);
          setState('done');
          onCopied?.();
          setTimeout(() => setState('idle'), 1600);
        } catch {
          setState('idle');
          if (text) onFail?.(text);
        }
      }}
    >
      <span className="ag-sr" aria-live="polite">
        {state === 'done' ? t(lang, '已复制', 'Copied') : ''}
      </span>
    </Button>
  );
}

export function ConnectPanel({
  lang,
  sessionId,
  origin,
  opener,
  secret,
  connection,
  reachable = false,
}: {
  lang: 'zh' | 'en';
  sessionId: string;
  origin: string;
  opener: Pair;
  secret: () => Promise<string | null>;
  connection?: AgentConnection;
  /** Connected by a handshake only: setup is written, no tool call yet. */
  reachable?: boolean;
}) {
  const [client, setClient] = useState<Client>('claude-desktop');
  const [manual, setManual] = useState<string | null>(null);
  const [downloaded, setDownloaded] = useState(false);
  const [copiedAt, setCopiedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  // Re-check once the slow threshold passes; the activity feed re-renders on any real call.
  useEffect(() => {
    if (copiedAt === null) return;
    const left = copiedAt + SLOW_MS - Date.now();
    if (left <= 0) return;
    const timer = setTimeout(() => setNow(Date.now()), left + 50);
    return () => clearTimeout(timer);
  }, [copiedAt]);
  const waiting = waitingHint(lang, client, copiedAt, Math.max(now, Date.now()), connection);
  const endpoint = mcpEndpoint(origin, sessionId);
  const ask = opener[lang === 'en' ? 1 : 0];
  const isCodex = client === 'codex' || client === 'codex-desktop';
  const desktop = client === 'claude-desktop' || client === 'codex-desktop';
  const other = client === 'other';
  const shown = isCodex
    ? `[mcp_servers.rolecraft]\nurl = ${JSON.stringify(endpoint)}\nhttp_headers = { Authorization = "Bearer ${MASK}" }`
    : commandFor(client, endpoint, MASK, ask);
  const textToCopy = async () => {
    const token = await secret();
    return token ? commandFor(client, endpoint, token, ask) : null;
  };
  const connected = connection?.state === 'connected';
  return (
    <section className="ag-connect" aria-label={t(lang, '连接你的 Agent', 'Connect your agent')}>
      <header className="ag-connect-head">
        <h2>{t(lang, '选择你用的工具', 'Choose your tool')}</h2>
        <p className="ag-connect-status" role="status" data-connected={connected}>
          <span
            className="ag-status-dot rc-agent-light"
            data-state={reachable ? 'reachable' : (connection?.state ?? 'none')}
            aria-hidden="true"
          />
          {connectionLabel(connection, lang, reachable)}
        </p>
      </header>
      {reachable ? (
        <p className="ag-step-hint ag-connect-wait" role="note">
          {reachableHint(lang, client)}
        </p>
      ) : null}
      {waiting ? (
        <p className="ag-step-hint ag-connect-wait" role="status" data-slow={waiting.slow}>
          {waiting.text}
        </p>
      ) : null}
      <fieldset className="ag-client-options" aria-label={t(lang, '客户端', 'Client')}>
        {CLIENTS.map(([key, label]) => (
          <Button
            key={key}
            variant="ghost"
            data-client={key}
            aria-pressed={client === key}
            onClick={() => {
              setClient(key);
              setManual(null);
              setDownloaded(false);
            }}
          >
            {label[lang === 'en' ? 1 : 0]}
          </Button>
        ))}
      </fieldset>
      <ol className="ag-steps" key={client}>
        <li>
          <p className="ag-step-title">
            <span className="ag-step-n">1</span>
            {other
              ? t(lang, '导入连接配置', 'Import the connection config')
              : t(lang, '复制并在终端执行', 'Copy and run in Terminal')}
          </p>
          {isCodex ? (
            <p className="ag-step-hint">
              {t(
                lang,
                '将保存以下配置；右侧按钮复制完整连接命令。',
                'This config will be saved; the button copies the full setup command.',
              )}
            </p>
          ) : null}
          <div className="ag-cmd">
            <pre title={t(lang, '连接配置，令牌已隐藏', 'Connection config, token hidden')}>
              <code>{shown}</code>
            </pre>
            <CopyKey
              lang={lang}
              label={
                other ? t(lang, '复制配置', 'Copy config') : t(lang, '复制命令', 'Copy command')
              }
              getText={textToCopy}
              onFail={setManual}
              onCopied={() => setCopiedAt(Date.now())}
            />
          </div>
          {other ? (
            <Button
              variant="ghost"
              className="ag-download"
              icon={<Download size={14} />}
              onClick={async () => {
                const text = await textToCopy();
                if (!text) return;
                const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
                const link = document.createElement('a');
                link.href = url;
                link.download = 'rolecraft-mcp.json';
                link.click();
                setTimeout(() => URL.revokeObjectURL(url), 1000);
                setDownloaded(true);
                setCopiedAt(Date.now());
              }}
            >
              {downloaded
                ? t(lang, '已下载配置', 'Config downloaded')
                : t(lang, '下载配置文件', 'Download config file')}
            </Button>
          ) : null}
          <p className="ag-step-hint">
            {other
              ? t(
                  lang,
                  '下载或复制后，导入客户端的 MCP 设置；使用 Streamable HTTP。',
                  'Download or copy, then import into your client’s MCP settings using Streamable HTTP.',
                )
              : isCodex
                ? t(
                    lang,
                    '在这台 Mac 的终端粘贴并执行；需已安装 Codex 命令行和 Python 3。先备份，再更新 ~/.codex/config.toml，桌面与命令行共用。',
                    'Paste and run in Terminal on this Mac; requires the Codex CLI and Python 3. Backs up and updates ~/.codex/config.toml for both desktop and CLI.',
                  )
                : t(
                    lang,
                    '在这台 Mac 的终端粘贴并执行；需已安装 Claude Code 命令行。替换用户级连接，任何文件夹都可用。',
                    'Paste and run in Terminal on this Mac; requires the Claude Code CLI. Replaces the user-level connection, available in every folder.',
                  )}
          </p>
          {isCodex ? (
            <details className="ag-command-details">
              <summary>
                {t(lang, '查看完整命令（令牌已隐藏）', 'View full command (token hidden)')}
              </summary>
              <pre>
                <code>{commandFor(client, endpoint, MASK, ask)}</code>
              </pre>
            </details>
          ) : null}
          {manual ? (
            <textarea
              className="ag-manual"
              readOnly
              rows={3}
              value={manual}
              aria-label={t(
                lang,
                '浏览器没有允许复制，请手动复制',
                'Copying was blocked; copy this by hand',
              )}
              ref={(n) => n?.select()}
            />
          ) : null}
        </li>
        <li>
          <p className="ag-step-title">
            <span className="ag-step-n">2</span>
            {desktop
              ? t(lang, '新开一个对话', 'Open a new conversation')
              : other
                ? t(lang, '打开你的 Agent', 'Open your agent')
                : t(lang, '接着使用命令行', 'Continue in the CLI')}
          </p>
          <p className="ag-step-hint">
            {client === 'claude-desktop'
              ? t(
                  lang,
                  '在 Claude 桌面 App 的 Code 标签页选择本机文件夹，新开会话；Chat 标签页不使用这份配置。已经开着的会话读不到新连接：请新开一个，或在会话里输入 /mcp 重连 rolecraft。仍未出现时完全退出并重开 App。',
                  'In the Claude desktop app’s Code tab, choose a local folder and start a new session. The Chat tab does not use this config. A session that was already open does not see the new connection: start a new one, or type /mcp in it and reconnect rolecraft. If missing, fully quit and reopen the app.',
                )
              : client === 'codex-desktop'
                ? t(
                    lang,
                    '在 Codex 桌面 App 新开对话；若还没有 RoleCraft，完全退出 App，重新打开后再新开对话。',
                    'Start a new conversation in the Codex desktop app. If RoleCraft is missing, fully quit and reopen the app, then start another conversation.',
                  )
                : other
                  ? t(
                      lang,
                      '保存配置后新开会话，让客户端读取连接。',
                      'Save the config and start a new session so your client loads it.',
                    )
                  : t(
                      lang,
                      '命令会启动一个新的 Agent 并带上下面的请求；已经开着的命令行会话读不到新连接，要重启或在 /mcp 里重连。以后直接启动命令行即可。',
                      'The command starts a new agent with the request below. A CLI session that was already open does not see the new connection: restart it or reconnect in /mcp. Start the CLI normally next time.',
                    )}
          </p>
        </li>
        <li>
          <p className="ag-step-title">
            <span className="ag-step-n">3</span>
            {desktop || other
              ? t(lang, '把这句话发给它', 'Send it this request')
              : t(lang, '看看它的第一次调用', 'Watch for its first call')}
          </p>
          <div className="ag-cmd is-ask">
            <p className="ag-ask">{ask}</p>
            <CopyKey
              lang={lang}
              label={t(lang, '复制这句话', 'Copy the request')}
              getText={async () => ask}
              onFail={setManual}
            />
          </div>
          <p className="ag-step-hint">
            {t(
              lang,
              '收到真实调用后，上方会显示“已连接”，下方会留下传输记录。',
              'After a real call arrives, the status above changes to Connected and the activity appears below.',
            )}
          </p>
        </li>
      </ol>
      <p className="ag-fine">
        {t(
          lang,
          `令牌在页面上隐藏，复制或下载时才带上；每次授权有效 ${accessDuration('zh')}。复制时会核对并按需续发，到期或换一局后需重新执行连接命令。`,
          `The token stays hidden until you copy or download. Each grant lasts ${accessDuration('en')}. Copying checks and renews access when needed; run setup again after expiry or when switching practices.`,
        )}
      </p>
    </section>
  );
}
