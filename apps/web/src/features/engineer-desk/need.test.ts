// Whether this practice still has something for the engineer to fix (189's decision): the problem
// exists only while the policy is newer than the index and the settings give no warning. Read from
// the practice itself before any ticket is opened; only without those facts, from the ticket's
// first target test (the snapshot the ticket recorded).
import { describe, expect, it } from 'vitest';
import type { TargetTest } from './model';
import { fixNeed, fixNeedFromPractice, practiceFacts } from './need';

const practice = (policy: number, index: number, guard?: 'none' | 'warn' | 'fallback') => ({
  world: { policyVersion: policy, indexVersion: index },
  effectiveConfig:
    guard === undefined
      ? null
      : { effective: { freshness_guard: guard }, requested: {}, differences: {} },
});

const target = (over: Partial<TargetTest> = {}): TargetTest => ({
  test_id: 't1',
  origin: 'seeded',
  origin_label: '',
  executor: { kind: 'system', id: 'sys' } as TargetTest['executor'],
  query: 'What is the hotel limit?',
  status: 'answered',
  error_code: null,
  answer_summary: 'CNY 500 per night.',
  citations: [{ object_id: 'policy', version: 1 }],
  citation_count: 1,
  source_versions: { policy: 2 },
  indexed_versions: { policy: 1 },
  used_versions: { policy: 1 },
  config_version: 1,
  config: { same_as_baseline: true, changed_fields: [], differences: {} },
  ...over,
});

describe('fixNeed: from the practice, before a ticket is opened', () => {
  it('is broken while the policy is newer than the index and nothing warns', () => {
    expect(fixNeed(practiceFacts(practice(2, 1, 'none')))).toBe('broken');
  });

  it('is clear once the index was refreshed to the policy', () => {
    expect(fixNeed(practiceFacts(practice(2, 2, 'none')))).toBe('clear');
  });

  it('is clear when the settings already warn or fall back on stale sources', () => {
    expect(fixNeed(practiceFacts(practice(2, 1, 'warn')))).toBe('clear');
    expect(fixNeed(practiceFacts(practice(2, 1, 'fallback')))).toBe('clear');
  });

  it('reads a saved configuration without the field as the server default (no warning)', () => {
    const a = { world: { policyVersion: 2, indexVersion: 1 }, effectiveConfig: { effective: {} } };
    expect(fixNeed(practiceFacts(a))).toBe('broken');
  });

  it('cannot tell from the practice when the index lags and the settings were not read', () => {
    expect(fixNeedFromPractice(practiceFacts(practice(2, 1)))).toBeNull();
    expect(fixNeedFromPractice(practiceFacts({ world: {} }))).toBeNull();
  });

  it('is clear without knowing the settings when the index is not behind', () => {
    expect(fixNeed(practiceFacts(practice(2, 2)))).toBe('clear');
  });
});

describe('fixNeed: facts missing, falls back to the ticket’s recorded test', () => {
  it('is broken when the recorded answer cites an older version with no warning', () => {
    expect(fixNeed(practiceFacts(practice(2, 1)), target())).toBe('broken');
    expect(fixNeed(practiceFacts(null), target())).toBe('broken');
  });

  it('is clear when the recorded answer already cites the current version', () => {
    const fresh = target({
      citations: [{ object_id: 'policy', version: 2 }],
      indexed_versions: { policy: 2 },
      used_versions: { policy: 2 },
      answer_summary: 'CNY 400 per night.',
    });
    expect(fixNeed(practiceFacts({}), fresh)).toBe('clear');
  });

  it('is clear when the recorded answer already carried a warning', () => {
    expect(fixNeed(practiceFacts({}), target({ status: 'answered_with_warning' }))).toBe('clear');
  });

  it('assumes there is something to fix when neither source can tell', () => {
    expect(fixNeed(practiceFacts(null))).toBe('broken');
    expect(fixNeed(practiceFacts({}), undefined)).toBe('broken');
  });
});
