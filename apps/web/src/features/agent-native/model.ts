import type { DelegationInput } from '../../contracts-v2';
import type { V4HostSnapshot } from '../../v4-host';
export type Ref = NonNullable<V4HostSnapshot['currentProduct']>;
export type Language = 'zh' | 'en';
export type Connection = {
  id: string;
  label: string;
  capabilities: string[];
  expiresAt: string;
  status: 'active' | 'revoked' | 'expired' | 'unknown';
};
export type Activity = {
  id: string;
  type: string;
  executor: string;
  refs: Ref[];
  summary: string;
  semanticStatus?: string;
  verification?: string;
};
export type ReturnedWork = {
  ref: Ref;
  title: string;
  purpose: string;
  adoption: string;
  semanticStatus?: string;
  verification?: string;
};
export type Pending = { requestId: string; action: string; status: string };
export type Draft = {
  name: string;
  act: boolean;
  all: boolean;
  minutes: number;
  refs: Ref[];
  pending?: Pending;
  dispatchUnknown?: boolean;
};
export const t = (language: Language, zh: string, en: string) => (language === 'zh' ? zh : en);
const object = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw Error('agent_data_invalid');
  return value as Record<string, unknown>;
};
const text = (value: unknown, fallback = '') => (typeof value === 'string' ? value : fallback);
export function listData(value: unknown, key: string): { rows: unknown[]; cursor?: number } {
  let row = object(value);
  for (let i = 0; i < 4; i++) {
    if (Array.isArray(row[key]))
      return {
        rows: row[key],
        cursor: typeof row.next_cursor === 'number' ? row.next_cursor : undefined,
      };
    row = object(row.result);
  }
  throw Error('agent_data_invalid');
}
export function ref(value: unknown, sessionId: string): Ref {
  const row = object(value);
  if (
    row.session_id !== sessionId ||
    typeof row.kind !== 'string' ||
    typeof row.object_id !== 'string' ||
    !Number.isInteger(row.version) ||
    (row.version as number) < 0 ||
    ['role_context', 'scenario_state', 'job_context'].includes(row.kind)
  )
    throw Error('agent_reference_invalid');
  return {
    session_id: sessionId,
    kind: row.kind,
    object_id: row.object_id,
    version: row.version as number,
  } as Ref;
}
export function connections(value: unknown, sessionId: string): Connection[] {
  return listData(value, 'items').rows.map((value) => {
    const row = object(value),
      actor = object(row.executor);
    if (
      row.session_id !== sessionId ||
      typeof row.id !== 'string' ||
      actor.kind !== 'external_agent' ||
      actor.delegation_id !== row.id ||
      !Array.isArray(row.capabilities) ||
      !row.capabilities.every((x) => ['read', 'act', 'submit'].includes(String(x))) ||
      typeof row.expires_at !== 'string' ||
      Number.isNaN(Date.parse(row.expires_at))
    )
      throw Error('agent_connection_invalid');
    const state = row.revoked === true ? 'revoked' : row.effective_status;
    return {
      id: row.id,
      label: text(row.agent_label),
      capabilities: row.capabilities as string[],
      expiresAt: row.expires_at,
      status: ['active', 'revoked', 'expired'].includes(String(state))
        ? (state as Connection['status'])
        : 'unknown',
    };
  });
}
export function activities(value: unknown, sessionId: string): Activity[] {
  return listData(value, 'events').rows.map((value) => {
    const row = object(value),
      actor = object(row.executor),
      data = object(row.data ?? {});
    if (
      row.session_id !== sessionId ||
      typeof row.id !== 'string' ||
      typeof row.type !== 'string' ||
      !['human', 'external_agent', 'reference_agent', 'system'].includes(String(actor.kind))
    )
      throw Error('agent_activity_invalid');
    return {
      id: row.id,
      type: row.type,
      executor: String(actor.kind),
      refs: Array.isArray(row.refs) ? row.refs.map((x) => ref(x, sessionId)) : [],
      summary: text(data.summary),
      semanticStatus: text(data.semantic_status) || undefined,
      verification: text(data.verification) || undefined,
    };
  });
}
export function returnedWorks(value: unknown, sessionId: string): ReturnedWork[] {
  return listData(value, 'items').rows.flatMap((value) => {
    const row = object(value);
    if (row.session_id !== sessionId) throw Error('agent_product_session_invalid');
    const author = object(row.author),
      executor = object(row.executor);
    if (
      (author.kind !== 'external_agent' && executor.kind !== 'external_agent') ||
      row.removed_at != null
    )
      return [];
    return [
      {
        ref: ref(
          {
            session_id: row.session_id,
            kind: 'product',
            object_id: row.product_id,
            version: row.version,
          },
          sessionId,
        ),
        title: text(row.title),
        purpose: text(row.purpose),
        adoption: text(object(row.adoption).status),
        semanticStatus: text(row.semantic_status) || undefined,
        verification: text(row.verification) || undefined,
      },
    ];
  });
}
export function restoreDraft(value: unknown, sessionId: string): Draft {
  const blank = { name: '', act: false, all: false, minutes: 30, refs: [] };
  if (!value || typeof value !== 'object') return blank;
  try {
    const row = object(value);
    const pending = row.pending ? object(row.pending) : undefined;
    return {
      name: text(row.name).slice(0, 64),
      act: row.act === true,
      all: row.all === true,
      dispatchUnknown: row.dispatchUnknown === true,
      minutes: [15, 30, 60].includes(Number(row.minutes)) ? Number(row.minutes) : 30,
      refs: Array.isArray(row.refs) ? row.refs.map((x) => ref(x, sessionId)) : [],
      ...(pending && typeof pending.requestId === 'string' && typeof pending.action === 'string'
        ? {
            pending: {
              requestId: pending.requestId,
              action: pending.action,
              status: text(pending.status, 'unconfirmed'),
            },
          }
        : {}),
    };
  } catch {
    return blank;
  }
}
export function semanticLabel(language: Language, status?: string, verification?: string): string {
  if (['waiting_model', 'awaiting_model', 'unavailable', 'placeholder'].includes(status ?? ''))
    return t(language, '等待模型接入', 'Waiting for model connection');
  if (['rule_verified', 'rules_verified'].includes(verification ?? ''))
    return t(language, '规则核实', 'Rule verified');
  return '';
}
export function grantInput(draft: Draft, sessionId: string, now: Date): DelegationInput {
  const name = draft.name.trim();
  if (!name || name.length > 64 || /[\x00-\x1f\x7f]/.test(name)) throw Error('agent_name_required');
  if (!draft.all && !draft.refs.length) throw Error('agent_scope_required');
  const refs = draft.refs.map((x) => ref(x, sessionId));
  return {
    agent_label: name,
    capabilities: draft.act ? ['read', 'act'] : ['read'],
    expires_at: new Date(now.getTime() + draft.minutes * 60_000).toISOString(),
    ...(!draft.all
      ? {
          allowed_objects: [...new Set(refs.map((x) => x.object_id))],
          create_under_tasks: refs.filter((x) => x.kind === 'task').map((x) => x.object_id),
        }
      : {}),
  };
}
