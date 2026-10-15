import { describe, expect, it } from 'vitest';
import { buildCatalog, referenceLabel } from '../../reference-catalog';
import { snapshotHeading, snapshotName } from './delivery';

const submission = (id: string) => ({
  session_id: 's',
  kind: 'submission',
  object_id: id,
  version: 1,
});
// Every submission is a new record at version 1; the timeline says which came first.
const first = submission('first'),
  second = submission('second');
const catalog = buildCatalog({
  events: [
    { id: 'e-2', seq: 9, type: 'submitted', refs: [second] },
    { id: 'e-1', seq: 4, type: 'submitted', refs: [first] },
  ],
});

describe('one delivery, one name', () => {
  // Feedback, its history and every evidence button name a delivery from the same catalog.
  it.each([
    ['zh', '第 2 次交付', '查看第 2 次交付的快照', '已保存的提交快照 · 第 2 次交付'],
    [
      'en',
      'Delivery 2',
      'View the snapshot of Delivery 2',
      'Saved submission snapshot · Delivery 2',
    ],
  ] as const)(
    'names a delivery the way evidence buttons do (%s)',
    (language, name, view, heading) => {
      expect(referenceLabel(second, catalog, language).text).toBe(name);
      expect(snapshotName(second, catalog, language)).toBe(view);
      expect(snapshotHeading(second, catalog, language)).toBe(heading);
    },
  );

  it('numbers deliveries in the order they were submitted', () => {
    expect(snapshotName(first, catalog, 'zh')).toBe('查看第 1 次交付的快照');
    expect(snapshotHeading(first, catalog, 'en')).toBe('Saved submission snapshot · Delivery 1');
  });

  it('keeps a plain name for a delivery the timeline does not list yet', () => {
    const unlisted = submission('not-yet-read');
    expect(snapshotName(unlisted, catalog, 'zh')).toBe('查看交付快照');
    expect(snapshotName(unlisted, catalog, 'en')).toBe('View the delivery snapshot');
    expect(snapshotHeading(unlisted, catalog, 'zh')).toBe('已保存的提交快照');
  });
});
