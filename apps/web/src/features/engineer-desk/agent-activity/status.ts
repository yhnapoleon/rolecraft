/** The Agent panel's head and its one way to connect, from the agent bus alone (208 G7): the
 * connection the agent line reports (`agentConnection()`), and "Connect", which runs 205's
 * registered `open-agent` (My agent, #/agent). Access is issued only there; the desk shows no
 * grant, expiry or command. Pure logic. */
import { T } from '../../../app/i18n';
import type { AgentConnection } from '../../../shell';
import { clock } from '../model';

export type StatusState = 'on' | 'idle' | 'waiting' | 'none';

export function agentStatus(c: AgentConnection): { state: StatusState; text: string } {
  if (c.state === 'connected')
    return {
      state: 'on',
      text: c.client
        ? T(`${c.client} · 已连接`, `${c.client} · connected`)
        : T('已连接', 'Connected'),
    };
  if (c.state === 'idle') {
    const at = c.lastSeen ? clock(c.lastSeen) : '';
    return {
      state: 'idle',
      text: at ? T(`最近一次 ${at}`, `Last seen ${at}`) : T('暂时没在动', 'Idle for now'),
    };
  }
  if (c.state === 'waiting')
    return { state: 'waiting', text: T('已授权 · 等它开始', 'Access granted · waiting for it') };
  return { state: 'none', text: T('未连接', 'Not connected') };
}

/** Not connected yet: one sentence and a key to My agent. Connected (or seen): nothing. */
export function connectOffer(
  c: AgentConnection,
): { lead: string; label: string; action: 'open-agent' } | null {
  if (c.state === 'connected' || c.state === 'idle') return null;
  if (c.state === 'waiting')
    return {
      lead: T(
        '已经授权，还没连上。连接命令在 My agent 页。',
        'Access is granted, but it hasn’t connected yet. The command is on My agent.',
      ),
      label: T('去 My agent', 'Go to My agent'),
      action: 'open-agent',
    };
  return {
    lead: T(
      '把这份委托交给你的 Agent：它做的每一步都会出现在这里。',
      'Give this ticket to your agent: every step it takes shows up here.',
    ),
    label: T('连接', 'Connect'),
    action: 'open-agent',
  };
}

/** A row of the live stream, opened: an experiment or draft opens its card on the desk; a review
 * read opens that review's report; anything else (a ticket read) opens nothing. */
export function streamTarget(
  tool: string,
  objectId: string | undefined,
): { kind: 'card' | 'review'; id: string } | null {
  if (!objectId) return null;
  if (tool === 'engineer.reviews.read') return { kind: 'review', id: objectId };
  if (
    tool === 'engineer.reproduce' ||
    tool === 'engineer.trial' ||
    tool === 'engineer.submissions.draft'
  )
    return { kind: 'card', id: objectId };
  return null;
}
