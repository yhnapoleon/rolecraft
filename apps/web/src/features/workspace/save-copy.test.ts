import { describe, expect, it } from 'vitest';
import { draftOf, type Transport } from './client';
import type { WorkProductVersion } from './contract-types';
import { memoryClient } from './test-support';

const original = {
  product_id: 'p1',
  session_id: 's',
  version: 2,
  kind: 'text',
  title: 'Plan',
  purpose: 'commitment',
  content: 'base',
  content_hash: '0'.repeat(64),
  cycle: { session_id: 's', kind: 'cycle', object_id: 'c', version: 1 },
  author: { id: 'h', kind: 'human' },
  executor: { id: 'h', kind: 'human' },
  created_at: '2026-10-14T00:00:00Z',
  legacy: null,
  removed_at: null,
} as WorkProductVersion;
const exact = {
  session_id: 's',
  kind: 'product',
  object_id: 'p1',
  version: 2,
  observed_at_seq: 3,
  valid_from_seq: 0,
};

function fixture(citation: object | undefined) {
  const storage = new Map<string, string>();
  const sent: { operation: string; payload: { evidence_refs?: unknown[] } }[] = [];
  const asOf = { business_seq: 9, workspace_revision: 4, storage_revision: 12 };
  const transport: Transport = async (path, body) => {
    if (path.includes('/objects/product/p1/2'))
      return { schema_version: 2, ref: { ...exact }, content: {}, ...citation };
    if (!body)
      return {
        items: path.includes('work-products') ? [structuredClone(original)] : [],
        as_of: asOf,
        next_cursor: null,
      };
    sent.push(structuredClone(body) as (typeof sent)[number]);
    const object = { ...original, product_id: 'copy', version: 1 };
    return { object, ref: { ...exact, object_id: 'copy', version: 1 }, as_of: asOf };
  };
  const client = memoryClient(
    's',
    {
      getItem: (key) => storage.get(key) ?? null,
      setItem: (key, value) => {
        storage.set(key, value);
      },
    },
    transport,
  );
  return { client, sent };
}

describe('saving a draft as a copy', () => {
  it('cites the original version with the exact reference the server gives', async () => {
    const { client, sent } = fixture({ evidence_ref: exact });
    await client.refresh();
    await client.keepDraft('p1', { ...draftOf(original), content: 'edited' });
    await client.saveCopy('p1');
    const created = sent.find((command) => command.operation === 'work_products.create');
    expect(created?.payload.evidence_refs).toEqual([exact]);
  });

  it('adds no guessed reference when the server gives none', async () => {
    const { client, sent } = fixture(undefined);
    await client.refresh();
    await client.keepDraft('p1', { ...draftOf(original), content: 'edited' });
    await client.saveCopy('p1');
    const created = sent.find((command) => command.operation === 'work_products.create');
    expect(created?.payload.evidence_refs).toEqual([]);
  });
});
