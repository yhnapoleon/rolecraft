// "Connect your agent": one press issues access and shows one command per client. Copy, paste in
// a terminal, and the agent starts already connected with its first request. The token is only in
// what is copied; the command on screen is masked. Command block after the AI Elements Snippet
// (Apache-2.0): the copy key crossfades to a check through a 2px blur and comes back after 1.6s.
import { Copy } from 'lucide-react';
import { useState } from 'react';
import { claudeCodeCommand, codexCommand, mcpEndpoint } from '../../app/agent-connection';
import { Button, type ButtonState, Segmented } from '../../ui-kit';
import type { Pair } from './index';

export type Client = 'claude' | 'codex' | 'other';
const t = (lang: 'zh' | 'en', zh: string, en: string) => (lang === 'en' ? en : zh);
const shell = (value: string) => `'${value.replaceAll("'", `'\\''`)}'`;
const MASK = '••••••••';

/** The exact text a client needs. `token` is the secret, or the mask for display. */
export function commandFor(client: Client, endpoint: string, token: string, opener: string) {
  if (client === 'claude')
    return `${claudeCodeCommand(endpoint, token)} && claude ${shell(opener)}`;
  if (client === 'codex') return `${codexCommand(endpoint, token)} ${shell(opener)}`;
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

export function CopyKey({
  label,
  getText,
  lang,
  onFail,
}: {
  label: string;
  getText: () => Promise<string | null>;
  lang: 'zh' | 'en';
  onFail?: (text: string) => void;
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
        const text = await getText();
        if (!text) {
          setState('idle');
          return;
        }
        try {
          await navigator.clipboard.writeText(text);
          setState('done');
          setTimeout(() => setState('idle'), 1600);
        } catch {
          setState('idle');
          onFail?.(text);
        }
      }}
    >
      <span className="ag-sr">{state === 'done' ? t(lang, '已复制', 'Copied') : ''}</span>
    </Button>
  );
}

export function ConnectPanel({
  lang,
  sessionId,
  origin,
  opener,
  secret,
}: {
  lang: 'zh' | 'en';
  sessionId: string;
  origin: string;
  opener: Pair;
  /** Issues access if needed and returns the token for one copy. */
  secret: () => Promise<string | null>;
}) {
  const [client, setClient] = useState<Client>('claude');
  const [manual, setManual] = useState<string | null>(null);
  const endpoint = mcpEndpoint(origin, sessionId);
  const ask = opener[lang === 'en' ? 1 : 0];
  // Agents read English best; the opener follows the interface language.
  // On screen only: flags keep their hyphens on one line (the copy is the real command).
  const shown = commandFor(client, endpoint, MASK, ask).replace(
    /(^|\s)(--?)(?=\w)/g,
    (_, a, d) => a + d.replaceAll('-', '\u2011'),
  );
  const tabs: [Client, string][] = [
    ['claude', 'Claude Code'],
    ['codex', 'Codex'],
    ['other', t(lang, '其他 MCP 客户端', 'Other MCP client')],
  ];
  const hint =
    client === 'claude'
      ? t(
          lang,
          '粘贴到终端：加上 RoleCraft，再带着第一句请求启动 Claude Code。',
          'Paste in a terminal. It adds RoleCraft and starts Claude Code with its first request.',
        )
      : client === 'codex'
        ? t(
            lang,
            '粘贴到终端：直接启动已连好的 Codex，不改它的配置。',
            'Paste in a terminal. It starts Codex already connected, without touching its config.',
          )
        : t(
            lang,
            '放进客户端的 MCP 配置（Streamable HTTP）。',
            'Put this in your client’s MCP config (Streamable HTTP).',
          );
  return (
    <section className="ag-connect" aria-label={t(lang, '连接你的 Agent', 'Connect your agent')}>
      <Segmented
        className="ag-seg"
        label={t(lang, '客户端', 'Client')}
        value={client}
        onChange={(key) => {
          setClient(key);
          setManual(null);
        }}
        items={tabs.map(([value, label]) => ({ value, label }))}
      />
      <ol className="ag-steps">
        <li>
          <p className="ag-step-title">
            <span className="ag-step-n">1</span>
            {client === 'other'
              ? t(lang, '配置', 'Configure')
              : t(lang, '粘贴到终端', 'Paste in your terminal')}
          </p>
          <div className="ag-cmd">
            <pre
              title={
                client === 'other'
                  ? t(lang, '配置，令牌已隐藏', 'Config, token hidden')
                  : t(lang, '命令，令牌已隐藏', 'Command, token hidden')
              }
            >
              <code>{shown}</code>
            </pre>
            <CopyKey
              lang={lang}
              label={
                client === 'other'
                  ? t(lang, '复制配置', 'Copy config')
                  : t(lang, '复制命令', 'Copy command')
              }
              getText={async () => {
                const token = await secret();
                return token ? commandFor(client, endpoint, token, ask) : null;
              }}
              onFail={setManual}
            />
          </div>
          <p className="ag-step-hint">{hint}</p>
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
            {client === 'other'
              ? t(lang, '然后对它说', 'Then tell your agent')
              : t(lang, '它会从这句话开始', 'It starts with this request')}
          </p>
          <div className="ag-cmd is-ask">
            <p className="ag-ask">{ask}</p>
            <CopyKey
              lang={lang}
              label={t(lang, '复制这句话', 'Copy the request')}
              getText={async () => ask}
            />
          </div>
        </li>
      </ol>
      <p className="ag-fine">
        {client === 'other'
          ? t(
              lang,
              '这段配置带着这一局的钥匙，到明天这个时候都有效。只放进你自己的客户端。',
              'This config carries a key to this practice and works until this time tomorrow. Put it only in your own client.',
            )
          : t(
              lang,
              '命令里带着这局练习的钥匙，到明天这个时候都有效。只粘贴到你自己的终端。',
              'The command carries a key to this practice and works until this time tomorrow. Paste it only into your own terminal.',
            )}
      </p>
    </section>
  );
}
