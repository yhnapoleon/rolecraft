import { afterEach, describe, expect, it, vi } from 'vitest';
import { setPreference } from './app/i18n';
import type { EvidenceRefV2 } from './contracts-v2';
import { EVIDENCE_KINDS } from './evidence-picker';
import { chooseWorkEvidence, evidenceChips, type EvidenceNames } from './native-evidence';
import type { EvidencePick } from './v4-host';
import { regionHost } from './v4-region-test-support';

const cited = (kind: string, id: string, version: number, extra = {}): EvidenceRefV2 => ({
  session_id: 's',
  kind,
  object_id: id,
  version,
  observed_at_seq: 3,
  valid_from_seq: 0,
  ...extra,
});
const work = { session_id: 's', kind: 'product', object_id: 'p1', version: 2 };
const passage = cited('material', 'policy', 2, {
  span_start: 0,
  span_end: 9,
  quote: '住宿上限 400 元。',
  valid_from_seq: 5,
});

afterEach(() => setPreference('zh'));

describe('choosing evidence for a work version', () => {
  it('offers every kind, keeps the current choice checked and never offers the work itself', async () => {
    const host = regionHost();
    const chosen = [passage, cited('test', 't1', 1)];
    vi.mocked(host.chooseEvidence).mockResolvedValue(chosen);
    const focus = { session_id: 's', kind: 'test', object_id: 't1', version: 1 };
    expect(await chooseWorkEvidence(host, work, [passage], focus)).toEqual(chosen);
    expect(vi.mocked(host.chooseEvidence).mock.calls[0][0]).toEqual({
      kinds: EVIDENCE_KINDS,
      selected: [passage],
      exclude: [work],
      focus,
    } satisfies EvidencePick);
  });

  it('reports no change when the person keeps the same evidence', async () => {
    const host = regionHost();
    vi.mocked(host.chooseEvidence).mockResolvedValue([passage]);
    expect(await chooseWorkEvidence(host, work, [passage])).toBeNull();
  });
});

describe('evidence chips', () => {
  const names: EvidenceNames = {
    material: (id, version) => (id === 'policy' && version === 2 ? '差旅政策' : undefined),
    test: (id) => (id === 't1' ? { query: '住宿报销上限是多少？', config: 2 } : undefined),
    product: (id) => (id === 'p9' ? '试点决定草稿' : undefined),
  };
  it('names each cited passage, test run and work version with its version', () => {
    const chips = evidenceChips(
      [passage, cited('test', 't1', 1), cited('product', 'p9', 3), cited('product', 'gone', 1)],
      names,
    );
    expect(chips.map((chip) => [chip.kind, chip.label, chip.version])).toEqual([
      ['material', '差旅政策', 'v2'],
      ['test', '测试：住宿报销上限是多少？', '配置 v2'],
      ['product', '《试点决定草稿》', '第 3 版'],
      ['product', '作品', '第 1 版'],
    ]);
    expect(chips[0].description).toBe('差旅政策 · v2：住宿上限 400 元。');
    setPreference('en');
    expect(evidenceChips([cited('test', 't1', 1)], names)[0]).toMatchObject({
      label: 'Test: 住宿报销上限是多少？',
      version: 'config v2',
    });
  });
});
