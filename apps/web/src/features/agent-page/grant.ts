// One press of "Connect your agent" issues the practice's agent access at once: the whole
// workspace, read and act (hand back drafts, run tests and trials), for a day. No form, duration
// or scope options (decision R3). Adopting, submitting and signing stay with the person.
import { GRANTED_TOOLS } from './verbs';

/** 23h55m: inside the server's 24-hour ceiling with room for clock skew. */
export const ACCESS_MS = (23 * 60 + 55) * 60_000;
/** Re-issue quietly when the grant on this page has less than this left. */
const RENEW_MS = 2 * 60 * 60_000;
export const AGENT_LABEL = 'My agent';

export type GrantHost = {
  snapshot(): { available?: Record<string, boolean>; state?: string };
  issuedDelegation(): { delegationId: string; expiresAt: string } | null;
  connectionSecret(): { sessionId: string; token: string } | null;
  command(operation: 'delegations.create', input: unknown): Promise<{ status: string }>;
  /** Requests whose outcome this page does not know yet (a response lost in transit). */
  pendingRequests?(): { requestId: string }[];
  recover?(requestId: string): Promise<{ status: string }>;
  query?(operation: 'delegations.list', input: object): Promise<unknown>;
};

/** Issuing ran but its answer never arrived: press again to recover the same grant. */
export class AccessUnconfirmed extends Error {}

export function accessInput(now = Date.now()) {
  return {
    capabilities: ['read', 'act'] as ('read' | 'act')[],
    allowed_actions: [...GRANTED_TOOLS],
    allowed_objects: null,
    create_under_tasks: [],
    expires_at: new Date(now + ACCESS_MS).toISOString(),
    agent_label: AGENT_LABEL,
  };
}

export const canConnect = (host: GrantHost | null) =>
  host?.snapshot().available?.['delegations.create'] === true;

/** Access usable for a command now, issuing it if the page holds none (or one about to lapse). */
export async function ensureAccess(host: GrantHost, now = Date.now()) {
  // A grant whose answer was lost is recovered first: the server replays the same grant, so a
  // second press never makes a second grant.
  for (const pending of host.pendingRequests?.() ?? []) {
    const outcome = await host.recover?.(pending.requestId);
    if (outcome && outcome.status !== 'confirmed' && outcome.status !== 'failed')
      throw new AccessUnconfirmed();
  }
  // The grant list withdraws a grant revoked or expired elsewhere before its token is handed out.
  if (host.issuedDelegation()) await host.query?.('delegations.list', {}).catch(() => null);
  const issued = host.issuedDelegation();
  if (issued && Date.parse(issued.expiresAt) - now > RENEW_MS && host.connectionSecret())
    return host.connectionSecret();
  const outcome = await host.command('delegations.create', accessInput(now));
  if (outcome.status === 'unconfirmed' || outcome.status === 'pending')
    throw new AccessUnconfirmed();
  if (outcome.status !== 'confirmed') return null;
  return host.connectionSecret();
}
