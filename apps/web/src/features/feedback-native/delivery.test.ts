import { describe, expect, it } from 'vitest';
import { deliveryName, deliveryNumber, snapshotName, versionTitles } from './delivery';

const ref = (kind: string, id: string, version = 1) => ({
  session_id: 's',
  kind,
  object_id: id,
  version,
});

describe('which delivery a feedback belongs to', () => {
  // Every submission is its own record at version 1, so the version cannot tell rounds apart.
  const submissions = [{ ref: ref('submission', 'first') }, { ref: ref('submission', 'second') }];

  it('numbers deliveries in the order they were made', () => {
    expect(deliveryNumber(submissions, ref('submission', 'first'))).toBe(1);
    expect(deliveryNumber(submissions, ref('submission', 'second'))).toBe(2);
    expect(deliveryNumber(submissions, ref('submission', 'unknown'))).toBeUndefined();
  });

  it('names a delivery by its round in both languages, never by its record id', () => {
    expect(deliveryName('zh', 2)).toBe('第 2 次交付');
    expect(deliveryName('en', 2)).toBe('Submission 2');
    expect(snapshotName('zh', 1)).toBe('查看第 1 次交付的快照');
    expect(snapshotName('en', 1)).toBe('View the snapshot of submission 1');
    expect(snapshotName('zh', undefined)).toBe('查看提交快照');
    expect(snapshotName('en', undefined)).toBe('View submission snapshot');
  });
});

describe('the title shown for a submitted work version', () => {
  const products = [{ product_id: 'p', version: 3, title: '试点决定（第三稿）' }];

  it('uses the current title when the submitted version is the current one, without a read', () => {
    const reads: unknown[] = [];
    const titles = versionTitles(
      async (asked) => {
        reads.push(asked);
        return undefined;
      },
      () => {},
    );
    expect(titles.title(products, ref('product', 'p', 3))).toBe('试点决定（第三稿）');
    expect(reads).toEqual([]);
  });

  it('reads the title saved with an earlier version once, then shows it', async () => {
    const reads: unknown[] = [];
    let changed = 0;
    const titles = versionTitles(
      async (asked) => {
        reads.push(asked);
        return '试点决定草稿';
      },
      () => changed++,
    );
    const earlier = ref('product', 'p', 2);
    expect(titles.title(products, earlier)).toBeUndefined();
    expect(titles.title(products, earlier)).toBeUndefined();
    await Promise.resolve();
    await Promise.resolve();
    expect(reads).toEqual([earlier]);
    expect(changed).toBe(1);
    expect(titles.title(products, earlier)).toBe('试点决定草稿');
  });

  it('leaves the title unknown when the version cannot be read', async () => {
    let changed = 0;
    const titles = versionTitles(
      async () => {
        throw Error('not readable');
      },
      () => changed++,
    );
    expect(titles.title(products, ref('product', 'p', 1))).toBeUndefined();
    await Promise.resolve();
    await Promise.resolve();
    expect(changed).toBe(0);
    expect(titles.title(products, ref('product', 'p', 1))).toBeUndefined();
  });
});
