import type { LegacyProvenance, WorkspaceImport } from './contract-types';

const secrets = new Set([
  'token',
  'authorization',
  'sessiontoken',
  'apikey',
  'password',
  'credential',
  'accesstoken',
  'refreshtoken',
  'secret',
  'bearer',
  'cookie',
]);
export function sanitizeSelection(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sanitizeSelection);
  if (value && typeof value === 'object')
    return Object.fromEntries(
      Object.entries(value)
        .filter(
          ([key]) =>
            !secrets.has(key.toLowerCase().replace(/[_-]/g, '')) &&
            !['pending', 'failedTurn'].includes(key),
        )
        .map(([key, v]) => [key, sanitizeSelection(v)]),
    );
  return value;
}
export function canonical(value: any): string {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value && typeof value === 'object')
    return (
      '{' +
      Object.keys(value)
        .sort()
        .filter((k) => value[k] !== undefined)
        .map((k) => JSON.stringify(k) + ':' + canonical(value[k]))
        .join(',') +
      '}'
    );
  return JSON.stringify(value);
}
export async function hash(value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(canonical(value));
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)))
    .map((x) => x.toString(16).padStart(2, '0'))
    .join('');
}

/** Explicit selection only. Caller keeps the original two browser archives.
 * Preserves drafts/removed/unadopted work and historical event snapshots. This
 * helper never reads storage, performs network requests, or executes pending.
 */
export async function buildBrowserImport(
  attempt: any,
  selection: { taskIds: string[]; productIds: string[] },
  packageId?: string,
): Promise<WorkspaceImport & { mode: 'preview' }> {
  if (
    !attempt ||
    typeof attempt.id !== 'string' ||
    !Array.isArray(attempt.tasks) ||
    !Array.isArray(attempt.artifacts)
  )
    throw Error('无法读取这份练习；请保留原存档。');
  if (
    new Set(selection.taskIds).size !== selection.taskIds.length ||
    new Set(selection.productIds).size !== selection.productIds.length
  )
    throw Error('重复选择。');
  const selected: { raw: any; kind: string }[] = [];
  const taskIds = [...selection.taskIds].sort(
    (a, b) =>
      attempt.tasks.findIndex((t: any) => t.id === a) -
      attempt.tasks.findIndex((t: any) => t.id === b),
  );
  const productIds = [...selection.productIds].sort(
    (a, b) =>
      attempt.artifacts.findIndex((t: any) => t.id === a) -
      attempt.artifacts.findIndex((t: any) => t.id === b),
  );
  for (const id of taskIds) {
    const task = attempt.tasks.find((t: any) => t.id === id);
    if (!task) throw Error('所选事项不存在。');
    selected.push({ raw: structuredClone(task), kind: 'task' });
  }
  for (const id of productIds) {
    const product = attempt.artifacts.find((p: any) => p.id === id);
    if (!product) throw Error('所选作品不存在。');
    const history = (attempt.events ?? []).filter(
      (e: any) => e.type === 'artifact_saved' && e.detail?.artifactId === id,
    );
    selected.push({
      raw: { ...structuredClone(product), sourceHistory: structuredClone(history) },
      kind: product.kind ?? 'text',
    });
  }
  if (!selected.length) throw Error('请先选择要导入的事项或作品。');
  const items: LegacyProvenance[] = [];
  for (const s of selected) {
    const raw = sanitizeSelection(s.raw) as LegacyProvenance['raw'];
    items.push({
      schema_version: 2,
      source_schema: 'browser-v1',
      source_session_id: attempt.id,
      original_id: s.raw.id,
      original_kind: s.kind,
      original_purpose: s.raw.purpose ?? null,
      raw,
      original_hash: await hash(raw),
    });
  }
  const stableId = packageId ?? 'browser-' + (await hash(items));
  return {
    schema_version: 2,
    package_id: stableId,
    mode: 'preview',
    source_schema: 'browser-v1',
    source_session_id: attempt.id,
    items,
    references: [],
    package_hash: await hash(items),
    preview_storage_revision: null,
  };
}
