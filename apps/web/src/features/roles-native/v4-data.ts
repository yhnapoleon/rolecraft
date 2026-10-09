/** Public reads shared by the two W04 slots. No transport, tokens or command journal. */
import type { V4HostAdapter, V4CommandResult } from '../../v4-host';
import type { ObjectRef } from '../../contracts-v2';

export type Data = Record<string, any>;
export const object = (value: unknown): Data => {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw Error('Invalid public data');
  return value as Data;
};
export function body(value: unknown): Data {
  const data = object(value);
  return data.result && typeof data.result === 'object' && !Array.isArray(data.result)
    ? object(data.result)
    : data;
}
export function commandBody(result: V4CommandResult): Data {
  const data = body(result.result ?? {});
  return data.response ? body(data.response) : data;
}
export function session(host: V4HostAdapter, expected?: string) {
  const s = host.snapshot().session;
  if (
    !s ||
    s.protocol !== 2 ||
    (expected && s.sessionId !== expected) ||
    !['zh', 'en'].includes(s.workLanguage)
  )
    throw Error('Bound v2 session required');
  return s;
}
export function ref(value: unknown, sid: string, kind?: string): ObjectRef {
  const r = object(value);
  if (
    r.session_id !== sid ||
    typeof r.kind !== 'string' ||
    (kind && r.kind !== kind) ||
    typeof r.object_id !== 'string' ||
    !Number.isInteger(r.version) ||
    r.version < 1
  )
    throw Error('Invalid public reference');
  return {
    schema_version: 2,
    session_id: sid,
    kind: r.kind,
    object_id: r.object_id,
    version: r.version,
  } as ObjectRef;
}
export interface PublicRow {
  ref: ObjectRef;
  content: Data;
}
export interface Timeline {
  rows: PublicRow[];
  data: Data;
}
export async function timeline(host: V4HostAdapter, sid: string): Promise<Timeline> {
  session(host, sid);
  if (!host.snapshot().available.timeline) throw Error('Timeline unavailable');
  const data = body(await host.query('timeline'));
  session(host, sid);
  if (!Array.isArray(data.objects)) throw Error('Public timeline unavailable');
  const rows = data.objects.map((value: unknown) => {
    const row = object(value);
    const reference = ref(row.ref, sid);
    const content = object(row.content);
    if (content.session_id !== sid) throw Error('Foreign public row');
    return { ref: reference, content };
  });
  return { rows, data };
}
export async function recipientShares(
  host: V4HostAdapter,
  sid: string,
  roleId: string,
): Promise<ObjectRef[]> {
  if (!host.snapshot().available['work_products.list']) throw Error('Share projection unavailable');
  const shares: ObjectRef[] = [];
  let cursor = 0;
  let at: string | undefined;
  do {
    const data = body(await host.query('work_products.list', { cursor, limit: 100 }));
    session(host, sid);
    if (
      !Array.isArray(data.items) ||
      !Array.isArray(data.shares) ||
      data.sharing_complete !== true ||
      !data.as_of
    )
      throw Error('Complete share projection required');
    const point = JSON.stringify(data.as_of);
    if (at && at !== point) throw Error('Share projection changed');
    at = point;
    for (const value of data.shares) {
      const share = object(value);
      ref(share.product, sid, 'product');
      if (
        share.session_id !== sid ||
        typeof share.id !== 'string' ||
        !Number.isInteger(share.version) ||
        share.version < 1
      )
        throw Error('Invalid share');
      if (share.recipient_role === roleId && share.revoked_at == null)
        shares.push(
          ref(
            { session_id: sid, kind: 'share', object_id: share.id, version: share.version },
            sid,
            'share',
          ),
        );
    }
    if (data.next_cursor === null) break;
    if (!Number.isInteger(data.next_cursor) || data.next_cursor <= cursor)
      throw Error('Invalid page cursor');
    cursor = data.next_cursor;
  } while (true);
  return [...new Map(shares.map((r) => [r.object_id + ':' + r.version, r])).values()];
}
export const requestRefs = (host: V4HostAdapter, slot: 'roles' | 'resource-requests'): string[] => {
  const values = host.draft<unknown>(slot, 'requestRefs');
  if (values === undefined) return [];
  if (!Array.isArray(values) || values.some((x) => typeof x !== 'string'))
    throw Error('Invalid journal references');
  return values;
};
export async function rememberRequest(
  host: V4HostAdapter,
  slot: 'roles' | 'resource-requests',
  result: V4CommandResult,
) {
  if (typeof result.requestId !== 'string' || !result.requestId)
    throw Error('Missing original request identity');
  // References only. The one host journal owns payload, versions, outcome and recovery.
  await host.keepDraft(slot, 'requestRefs', [
    ...new Set([...requestRefs(host, slot), result.requestId]),
  ]);
}
