import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { codexCommand } from '../../app/agent-connection';
import { CLIENTS, commandFor, ConnectPanel, connectionLabel, SLOW_MS, waitingHint } from './connect';

const endpoint = 'http://127.0.0.1:18910/api/sessions/example/mcp';

describe('desktop agent connection card', () => {
  it('offers five distinct clients and keeps the desktop commands separate from launching a CLI', () => {
    expect(CLIENTS.map(([key]) => key)).toEqual([
      'claude-desktop',
      'codex-desktop',
      'claude',
      'codex',
      'other',
    ]);
    expect(commandFor('claude-desktop', endpoint, 'secret', 'first request')).not.toContain(
      '&& claude',
    );
    expect(commandFor('claude', endpoint, 'secret', "it's a request")).toContain(
      "&& claude 'it'\\''s a request'",
    );
    expect(commandFor('codex-desktop', endpoint, 'secret', 'request')).toBe(
      codexCommand(endpoint, 'secret'),
    );
    expect(commandFor('codex', endpoint, 'secret', 'request')).toBe(
      `${codexCommand(endpoint, 'secret')} && codex 'request'`,
    );
  });
  it('exports the same authenticated HTTP endpoint for other clients', () => {
    expect(JSON.parse(commandFor('other', endpoint, 'secret', 'request'))).toEqual({
      mcpServers: {
        rolecraft: { type: 'http', url: endpoint, headers: { Authorization: 'Bearer secret' } },
      },
    });
  });
  it('shows connection evidence without inferring the selected client', () => {
    expect(connectionLabel(undefined, 'zh')).toBe('等待首次调用');
    expect(connectionLabel({ state: 'connected', client: null, last_seen: null }, 'zh')).toBe(
      '已连接',
    );
    expect(
      connectionLabel({ state: 'connected', client: 'codex-mcp-client', last_seen: null }, 'en'),
    ).toBe('Connected · from Codex');
    expect(connectionLabel({ state: 'idle', client: 'Claude', last_seen: null }, 'zh')).toBe(
      '已连接过 · 当前空闲',
    );
    expect(connectionLabel({ state: 'none', client: 'Codex', last_seen: null }, 'en')).toBe(
      'Waiting for the first call',
    );
  });
  it('renders both languages without fetching a token and masks the command', () => {
    for (const lang of ['zh', 'en'] as const) {
      let secretReads = 0;
      const html = renderToStaticMarkup(
        <ConnectPanel
          lang={lang}
          sessionId="example"
          origin="http://127.0.0.1:18910"
          opener={['读取委托', 'Read the brief']}
          secret={async () => {
            secretReads++;
            return 'DO_NOT_RENDER';
          }}
        />,
      );
      expect(secretReads).toBe(0);
      expect(html.match(/<li>/g)).toHaveLength(3);
      expect(html).not.toContain('DO_NOT_RENDER');
      expect(html).toContain('Bearer ••••••••');
      expect(html).toContain(lang === 'zh' ? '23 小时 55 分钟' : '23 h 55 min');
      expect(html).toContain(lang === 'zh' ? '读取委托' : 'Read the brief');
      if (lang === 'en') expect(html).not.toMatch(/[\u4e00-\u9fff]/);
    }
  });
});

describe('waiting for the first call', () => {
  const copied = Date.parse('2026-10-26T08:00:00Z');
  it('says nothing before a command is copied and after a real call arrives', () => {
    expect(waitingHint('zh', 'claude-desktop', null, copied, undefined)).toBeNull();
    expect(
      waitingHint('zh', 'claude-desktop', copied, copied + 1000, {
        state: 'connected',
        client: 'claude-code',
        last_seen: null,
      }),
    ).toBeNull();
    expect(
      waitingHint('en', 'claude', copied, copied + 1000, {
        state: 'idle',
        client: 'claude-code',
        last_seen: '2026-10-26T08:00:05Z',
      }),
    ).toBeNull();
  });
  it('waits, then after two minutes names the check for the chosen client', () => {
    const waiting = waitingHint('zh', 'claude-desktop', copied, copied + 1000);
    expect(waiting?.slow).toBe(false);
    expect(waiting?.text).toContain('等它的第一次调用');
    const slow = waitingHint('zh', 'claude-desktop', copied, copied + SLOW_MS);
    expect(slow?.slow).toBe(true);
    expect(slow?.text).toContain('claude mcp list');
    expect(slow?.text).toContain('/mcp');
    expect(waitingHint('en', 'codex', copied, copied + SLOW_MS)?.text).toContain('codex mcp list');
    const en = waitingHint('en', 'claude', copied, copied + SLOW_MS)?.text ?? '';
    expect(en).not.toMatch(/[一-鿿]/);
    // An idle state from before the copy is an older connection, not this setup.
    expect(
      waitingHint('en', 'claude', copied, copied + 1000, {
        state: 'idle',
        client: 'claude-code',
        last_seen: '2026-10-26T07:00:00Z',
      })?.slow,
    ).toBe(false);
  });
});
