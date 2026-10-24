import { describe, expect, it } from 'vitest';
import type { AgentActivity } from '../../contracts-v2';
import { createAgentFeed, toEvent } from './feed';
import { accessInput } from './grant';
import { engineerCall, foldEvents } from './stream';
import { NEVER_GRANTED, refusal } from './verbs';

const row = (seq: number, extra: Partial<AgentActivity> = {}): AgentActivity => ({
  seq,
  at: `2026-10-24T12:00:${String(seq).padStart(2, '0')}Z`,
  delegation_id: 'd1',
  kind: 'tool_call',
  tool: 'objects.read',
  capability: 'read',
  objects: [{ kind: 'material', id: 'policy', version: 2, title: 'Travel policy' }],
  status: 'ok',
  ...extra,
});
const page = (items: AgentActivity[], state: 'none' | 'connected' = 'connected') => ({
  schema_version: 2 as const,
  items,
  next_cursor: items.at(-1)?.seq ?? 0,
  complete: true,
  connection: { state, client: 'claude-code', last_seen: '2026-10-24T12:00:09Z' },
  checked_at: '2026-10-24T12:00:10Z',
});

describe('agent activity feed', () => {
  it('names the direction, verb and object of a call', () => {
    const read = toEvent(row(1));
    expect(read.direction).toBe('to_agent');
    expect(read.object).toMatchObject({ kind: 'material', id: 'policy', title: 'Travel policy' });
    const back = toEvent(
      row(2, {
        tool: 'work_products.create',
        capability: 'act',
        objects: [{ kind: 'product', id: 'p1', version: 1, title: null }],
      }),
    );
    expect(back.direction).toBe('to_workspace');
    expect(back.object).toMatchObject({ kind: 'work_product', id: 'p1', version: 1 });
    const connected = toEvent(
      row(3, { kind: 'connected', tool: null, client: { name: 'codex-mcp-client', version: '1' } }),
    );
    expect(connected.object?.title).toBe('Codex');
  });

  it('emits only rows that arrive after the first read', async () => {
    const emitted: string[] = [];
    let next = page([row(1), row(2)]);
    const feed = createAgentFeed({
      read: async () => next,
      emit: (e) => emitted.push(e.id),
      changed: () => {},
    });
    await feed.poll();
    expect(emitted).toEqual([]);
    expect(feed.snapshot().events).toHaveLength(2);
    const same = feed.snapshot();
    expect(feed.snapshot()).toBe(same);
    next = page([row(3)]);
    await feed.poll();
    expect(emitted).toEqual(['3']);
    expect(feed.snapshot().liveFrom).toBe(3);
    expect(feed.state()).toMatchObject({ state: 'connected', client: 'Claude Code' });
  });

  it('folds a run of the same read into one row with a count, newest first', () => {
    const events = [row(1), row(2), row(3, { tool: 'tests.list', objects: [], count: 4 })].map(
      toEvent,
    );
    const rows = foldEvents(events);
    expect(rows.map((r) => [r.key, r.times])).toEqual([
      ['3', 1],
      ['1', 2],
    ]);
  });

  it('grants one day of read and act without anything only the person may do', () => {
    const input = accessInput(Date.parse('2026-10-24T00:00:00Z'));
    expect(input.capabilities).toEqual(['read', 'act']);
    expect(Date.parse(input.expires_at) - Date.parse('2026-10-24T00:00:00Z')).toBeLessThan(
      24 * 3600_000,
    );
    for (const tool of NEVER_GRANTED) expect(input.allowed_actions).not.toContain(tool);
    expect(input.allowed_actions).toContain('materials.list');
    expect(input.allowed_actions).toContain('engineer.trial');
    expect(refusal('version_conflict').tell[1]).toMatch(/versions\.list/);
    // One code, two refusals: the tool tells them apart, and neither sentence hedges.
    const stale = refusal('lifecycle_permission_unavailable', 'work_products.versions.create');
    const removal = refusal('lifecycle_permission_unavailable', 'work_products.remove');
    expect(stale.why[1]).toBe('The version it edited is no longer the latest.');
    expect(removal.why[1]).toBe('Only you can remove or restore work.');
    for (const r of [stale, removal])
      expect(`${r.why[1]} ${r.tell[1]}`).not.toMatch(/\bor\b.*\?|, or /);
  });

  it('gives the engineer desk its own calls, with the experiment as the object', () => {
    const trial = toEvent(
      row(5, {
        tool: 'engineer.trial',
        capability: 'act',
        objects: [
          { kind: 'experiment', id: 'x7', version: null, title: null },
          { kind: 'ticket', id: 't1', version: null, title: null },
        ],
      }),
    );
    expect(trial).toMatchObject({ direction: 'to_workspace', object: { kind: 'other', id: 'x7' } });
    expect([toEvent(row(4)), trial].filter(engineerCall).map((e) => e.tool)).toEqual([
      'engineer.trial',
    ]);
  });
});
