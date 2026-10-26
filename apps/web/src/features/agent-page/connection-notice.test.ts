import { describe, expect, it } from 'vitest';
import type { FeedSnapshot } from './feed';
import { createConnectionNotice } from './connection-notice';
const snap = (
  state: 'none' | 'connected' | 'idle',
  seq = 1,
  client: string | null = 'claude-code',
  kind: 'connected' | 'tool_call' = 'tool_call',
): FeedSnapshot => ({
  loaded: true,
  liveFrom: 1,
  events: [],
  rows: [{ seq, at: '2026-10-25T12:00:00Z', delegation_id: 'd1', kind, status: 'ok' }],
  connection: { state, client, last_seen: '2026-10-25T12:00:00Z' },
});
const storage = () => {
  const map = new Map<string, string>();
  return {
    getItem: (key: string) => map.get(key) ?? null,
    setItem: (key: string, value: string) => {
      map.set(key, value);
    },
  };
};
describe('global MCP connection notice', () => {
  it('stays quiet for a setup handshake and speaks at the first tool call', () => {
    const texts: string[] = [];
    const watch = createConnectionNotice(
      'setup',
      (t) => texts.push(t),
      () => 'zh',
      storage(),
    );
    watch(snap('none'));
    watch(snap('connected', 2, 'claude-code', 'connected'));
    expect(texts).toEqual([]);
    watch(snap('connected', 3));
    expect(texts).toEqual(['你的 Agent 已连接 · 来自 Claude Code']);
  });
  it('notifies once on real connection, never on normal polls or a refresh', () => {
    const texts: string[] = [];
    const saved = storage();
    const watch = createConnectionNotice(
      'one',
      (t) => texts.push(t),
      () => 'zh',
      saved,
    );
    watch({ ...snap('none'), loaded: false });
    watch(snap('none'));
    watch(snap('connected', 2));
    watch(snap('connected', 3));
    expect(texts).toEqual(['你的 Agent 已连接 · 来自 Claude Code']);
    createConnectionNotice(
      'one',
      (t) => texts.push(t),
      () => 'zh',
      saved,
    )(snap('connected', 3));
    expect(texts).toHaveLength(1);
    watch(snap('idle', 3));
    watch(snap('connected', 4));
    expect(texts).toHaveLength(2);
  });
  it('uses local persisted identity across observers and omits an unknown client', () => {
    const texts: string[] = [];
    const saved = storage();
    for (let i = 0; i < 2; i++) {
      const watch = createConnectionNotice(
        'two',
        (t) => texts.push(t),
        () => 'en',
        saved,
      );
      watch(snap('none'));
      watch(snap('connected', 2, null));
    }
    expect(texts).toEqual(['Your agent is connected']);
  });
  it('does not replay initial connected history and isolates practices', () => {
    const texts: string[] = [];
    const saved = storage();
    createConnectionNotice(
      'history',
      (t) => texts.push(t),
      () => 'en',
      saved,
    )(snap('connected'));
    const other = createConnectionNotice(
      'other',
      (t) => texts.push(t),
      () => 'en',
      saved,
    );
    other(snap('none'));
    other(snap('connected', 1, 'codex-mcp-client'));
    expect(texts).toEqual(['Your agent is connected · from Codex']);
  });
  it('keeps in-tab behavior if local storage is blocked', () => {
    const texts: string[] = [];
    const watch = createConnectionNotice(
      'blocked',
      (t) => texts.push(t),
      () => 'zh',
      {
        getItem: () => {
          throw Error();
        },
        setItem: () => {
          throw Error();
        },
      },
    );
    watch(snap('none'));
    watch(snap('connected', 2, null));
    watch(snap('connected', 3, null));
    expect(texts).toEqual(['你的 Agent 已连接']);
  });
});
