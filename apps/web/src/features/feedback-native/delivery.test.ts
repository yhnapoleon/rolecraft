import { describe, expect, it } from 'vitest';
import { buildCatalog, referenceLabel } from '../../reference-catalog';
import {
  attachmentLine,
  snapshotHeading,
  snapshotName,
  stampTime,
  submitLabel,
} from './delivery';
import { decisionName } from './decision-cards';

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

describe('delivery panel attachments and stamp', () => {
  it('names a work version as a paper attachment in either language', () => {
    const product = { title: '试点决定草稿', version: 2, purpose: 'commitment' };
    expect(attachmentLine(product, 'zh')).toBe('《试点决定草稿》 · 第 2 版 · 试点决定');
    expect(attachmentLine({ ...product, title: 'Pilot decision draft' }, 'en')).toBe(
      '“Pilot decision draft” · version 2 · Pilot decision',
    );
  });
  it('keeps an unknown purpose as written and leaves out a missing one', () => {
    expect(attachmentLine({ title: 'A', version: 1, purpose: '路线图' }, 'zh')).toBe(
      '《A》 · 第 1 版 · 路线图',
    );
    expect(attachmentLine({ title: '', version: 1 }, 'en')).toBe('“Untitled work” · version 1');
  });
  it('stamps today with the time and another day with the date', () => {
    const now = new Date(2026, 9, 24, 16, 0);
    expect(stampTime(new Date(2026, 9, 24, 14, 5).toISOString(), 'zh', now)).toBe('14:05');
    expect(stampTime(new Date(2026, 9, 22, 9, 30).toISOString(), 'en', now)).toBe('22 Oct 09:30');
    expect(stampTime(undefined, 'zh', now)).toBe('');
    expect(stampTime('not a time', 'zh', now)).toBe('');
  });
  it('names each decision in the panel vocabulary and never guesses an unknown code', () => {
    expect(decisionName('launch_narrow', 'zh')).toBe('缩小范围推进');
    expect(decisionName('defer_with_conditions', 'en')).toBe('Defer until conditions are met');
    expect(decisionName('maybe_later', 'zh')).toBe('maybe_later');
  });
});

describe('the delivery button says what it will submit', () => {
  it('names the one version, the count, or the plain action', () => {
    expect(submitLabel([{ version: 1 }], 'zh')).toBe('提交第 1 版');
    expect(submitLabel([{ version: 3 }], 'en')).toBe('Submit version 3');
    expect(submitLabel([{ version: 1 }, { version: 2 }], 'zh')).toBe('提交 2 个版本');
    expect(submitLabel([{ version: 1 }, { version: 2 }], 'en')).toBe('Submit 2 versions');
    expect(submitLabel([], 'zh')).toBe('提交选中的版本');
  });
});
