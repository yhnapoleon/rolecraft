import { afterEach, describe, expect, it } from 'vitest';
import { setPreference } from '../../../app/i18n';
import { agentStatus, connectOffer, streamTarget } from './status';

afterEach(() => setPreference('zh'));

describe('engineer desk · your agent’s head follows the agent bus (G7)', () => {
  it('ED-R2-30 the status line is the bus’s connection, nothing else', () => {
    setPreference('en');
    expect(agentStatus({ state: 'connected', client: 'Claude Code' })).toEqual({
      state: 'on',
      text: 'Claude Code · connected',
    });
    expect(agentStatus({ state: 'idle', lastSeen: '2026-10-24T13:05:00Z' }).state).toBe('idle');
    expect(agentStatus({ state: 'waiting' })).toEqual({
      state: 'waiting',
      text: 'Access granted · waiting for it',
    });
    expect(agentStatus({ state: 'none' })).toEqual({ state: 'none', text: 'Not connected' });
  });

  it('ED-R2-31 Connect goes to My agent (open-agent); nothing to offer once it has connected', () => {
    const none = connectOffer({ state: 'none' });
    expect(none?.action).toBe('open-agent');
    expect(none?.label).toBe('连接');
    expect(connectOffer({ state: 'waiting' })?.action).toBe('open-agent');
    expect(connectOffer({ state: 'connected', client: 'Codex' })).toBeNull();
    expect(connectOffer({ state: 'idle' })).toBeNull();
  });
});

describe('engineer desk · a stream row opens its card (G7)', () => {
  it('ED-R2-32 experiments and drafts open their card; a review opens its report; others nothing', () => {
    expect(streamTarget('engineer.reproduce', 'exp-1')).toEqual({ kind: 'card', id: 'exp-1' });
    expect(streamTarget('engineer.trial', 'exp-2')).toEqual({ kind: 'card', id: 'exp-2' });
    expect(streamTarget('engineer.submissions.draft', 'd-1')).toEqual({ kind: 'card', id: 'd-1' });
    expect(streamTarget('engineer.reviews.read', 'r-1')).toEqual({ kind: 'review', id: 'r-1' });
    expect(streamTarget('engineer.tickets.read', 't-1')).toBeNull();
    expect(streamTarget('engineer.trial', undefined)).toBeNull();
  });
});
