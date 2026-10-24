import { afterEach, describe, expect, it, vi } from 'vitest';
import { setPreference } from './app/i18n';
import type { EvidenceRefV2, ObjectRef, WorkspaceProductRead } from './contracts-v2';
import {
  answerEvidenceRequest,
  evidenceSummary,
  pickEvidence,
  pickerSections,
  type AskEvidence,
  type PickerRow,
  type PickerSources,
} from './evidence-picker';
import type { V4HostAdapter } from './v4-host';
import { regionHost } from './v4-region-test-support';

const passage = (id: string, version: number, quote: string, start = 0): EvidenceRefV2 => ({
  session_id: 's',
  kind: 'material',
  object_id: id,
  version,
  span_start: start,
  span_end: start + quote.length,
  quote,
  observed_at_seq: 2,
  valid_from_seq: version === 1 ? 0 : 5,
});
const test = (id: string, query: string, config: number, seq: number) => ({
  ref: { session_id: 's', kind: 'test', object_id: id, version: 1 },
  content: {
    query,
    status: 'answered',
    config_ref: {
      session_id: 's',
      kind: 'config',
      object_id: 'c',
      version: 1,
      config_version: config,
    },
    as_of: { business_seq: seq, workspace_revision: 1, storage_revision: seq },
  },
});
const work = (id: string, title: string, version: number, extra = {}) =>
  ({
    product_id: id,
    session_id: 's',
    version,
    title,
    purpose: 'commitment',
    author: { id: 'human:s', kind: 'human' },
    executor: { id: 'human:s', kind: 'human' },
    content_hash: 'h',
    created_at: '2026-10-14T00:00:00Z',
    cycle: { session_id: 's', kind: 'cycle', object_id: 'cy', version: 1 },
    removed_at: null,
    ...extra,
  }) as WorkspaceProductRead;
const cited = (kind: string, id: string, version: number, seq: number): EvidenceRefV2 => ({
  session_id: 's',
  kind,
  object_id: id,
  version,
  observed_at_seq: seq,
  valid_from_seq: 0,
});

function sources(): PickerSources {
  return {
    sessionId: 's',
    passages: [
      passage('policy', 1, '住宿上限 500 元。'),
      passage('policy', 2, '住宿上限 400 元。'),
      passage('brief', 1, '下周开放试点。'),
    ],
    titles: { 'policy:1': '差旅政策', 'policy:2': '差旅政策', 'brief:1': '经理委托' },
    current: { policy: 2, brief: 1 },
    tests: [
      test('t1', '住宿报销上限是多少？', 1, 3),
      test('t2', '能不能报销洗衣？', 1, 4),
      test('t3', '住宿报销上限是多少？', 2, 6),
    ],
    products: [
      work('p1', '试点决定草稿', 2),
      work('p2', '旧笔记', 1, { removed_at: '2026-10-14T01:00:00Z' }),
      work('p3', '探索笔记', 3),
    ],
  };
}
const all = ['material', 'test', 'product'] as const;
const rowsOf = (sections: ReturnType<typeof pickerSections>, kind: string) =>
  sections.find((s) => s.kind === kind)?.groups.flatMap((g) => g.rows) ?? [];

afterEach(() => setPreference('zh'));

describe('pickerSections', () => {
  it('lists read passages by document, test runs newest first and saved work', () => {
    const sections = pickerSections(sources(), {
      kinds: all,
      exclude: [{ session_id: 's', kind: 'product', object_id: 'p3', version: 3 }],
    });
    expect(sections.map((s) => s.title)).toEqual(['读过的资料段落', '测试运行', '作品版本']);
    const materials = sections[0].groups;
    expect(materials.map((g) => [g.title, g.note ?? ''])).toEqual([
      ['《差旅政策》· v1', '有新版本'],
      ['《差旅政策》· v2', ''],
      ['《经理委托》· v1', ''],
    ]);
    expect(materials[0].rows.map((r) => r.label)).toEqual(['住宿上限 500 元。']);
    expect(rowsOf(sections, 'test').map((r) => [r.label, r.meta])).toEqual([
      ['住宿报销上限是多少？', '配置 v2 · 已回答 · 第 2 次'],
      ['能不能报销洗衣？', '配置 v1 · 已回答 · 第 1 次'],
      ['住宿报销上限是多少？', '配置 v1 · 已回答 · 第 1 次'],
    ]);
    // Removed work and the work being edited are not offered.
    expect(rowsOf(sections, 'product').map((r) => [r.label, r.meta])).toEqual([
      ['《试点决定草稿》', '第 2 版 · 试点决定'],
    ]);
    expect(
      [...rowsOf(sections, 'test'), ...rowsOf(sections, 'product')].some((r) => r.checked),
    ).toBe(false);
  });

  it('keeps the current choice checked, including items no longer listed', () => {
    const selected = [
      passage('policy', 2, '住宿上限 400 元。'),
      cited('test', 't1', 1, 4),
      cited('product', 'p9', 4, 7),
    ];
    const sections = pickerSections(sources(), { kinds: all, selected });
    const checked = sections
      .flatMap((s) => s.groups.flatMap((g) => g.rows))
      .filter((r) => r.checked);
    expect(checked.map((r) => [r.kind, r.ref.object_id, r.ref.version])).toEqual([
      ['material', 'policy', 2],
      ['test', 't1', 1],
      ['product', 'p9', 4],
    ]);
    expect(checked[2].label).toBe('作品');
  });

  it('offers only read passages unless other kinds are asked for', () => {
    const sections = pickerSections(sources(), {});
    expect(sections.map((s) => s.kind)).toEqual(['material']);
  });

  it('puts the focused document first', () => {
    const sections = pickerSections(sources(), {
      kinds: all,
      focus: { session_id: 's', kind: 'material', object_id: 'brief', version: 1 },
    });
    expect(sections[0].groups[0].title).toBe('《经理委托》· v1');
  });

  it('preselects a focused test run', () => {
    const sections = pickerSections(sources(), {
      kinds: all,
      focus: { session_id: 's', kind: 'test', object_id: 't2', version: 1 },
    });
    expect(
      rowsOf(sections, 'test')
        .filter((r) => r.checked)
        .map((r) => r.ref.object_id),
    ).toEqual(['t2']);
  });

  it('writes English labels in the English interface', () => {
    setPreference('en');
    const sections = pickerSections(sources(), { kinds: all });
    expect(sections.map((s) => s.title)).toEqual([
      'Passages you read',
      'Test runs',
      'Work versions',
    ]);
    expect(sections[0].groups[0].title).toBe('“差旅政策” · v1');
    expect(sections[0].groups[0].note).toBe('Newer version');
    expect(rowsOf(sections, 'test')[0].meta).toBe('config v2 · answered · run 2');
    expect(rowsOf(sections, 'product')[0].meta).toBe('version 2 · Pilot decision');
  });
});

function host(objects: Record<string, unknown>): V4HostAdapter {
  const base = regionHost();
  const data = sources();
  return {
    ...base,
    draft: <T>(slot: string, key: string) =>
      (slot === 'workspace' && key === 'evidence-cache' ? data.passages : undefined) as T,
    query: vi.fn(async (operation: string, input?: Record<string, unknown>) => {
      if (operation === 'timeline')
        return {
          as_of: { business_seq: 9, workspace_revision: 3, storage_revision: 9 },
          objects: data.tests,
          role_mode: 'local_reference',
          workspace: {
            material_titles: data.titles,
            source_versions: data.current,
            indexed_versions: data.current,
            resources: {},
            config: {},
          },
        };
      if (operation === 'work_products.list')
        return { items: data.products, as_of: { business_seq: 9 }, shares: [] };
      if (operation === 'objects.read') {
        const key = `${input?.kind}:${input?.object_id}:${input?.version}`;
        if (!(key in objects)) throw Error('not found');
        return objects[key];
      }
      throw Error(`unexpected ${operation}`);
    }) as unknown as V4HostAdapter['query'],
  };
}
const read = (kind: string, id: string, version: number, seq?: number) => ({
  schema_version: 2,
  ref: { session_id: 's', kind, object_id: id, version },
  content: {},
  ...(seq === undefined ? {} : { evidence_ref: cited(kind, id, version, seq) }),
});
/** A person who ticks the given rows and confirms once. */
const ticks =
  (pick: (row: PickerRow) => boolean, seen: { error?: unknown } = {}): AskEvidence =>
  async (sections, confirm) => {
    const rows = sections.flatMap((s) => s.groups.flatMap((g) => g.rows)).filter(pick);
    try {
      return await confirm(rows);
    } catch (error) {
      seen.error = error;
      return null;
    }
  };

describe('pickEvidence', () => {
  it('cites tests and work with the exact reference the server gives', async () => {
    const h = host({
      'test:t3:1': read('test', 't3', 1, 6),
      'product:p1:2': read('product', 'p1', 2, 5),
    });
    const chosen = await pickEvidence(
      h,
      { kinds: all },
      ticks((r) => ['t3', 'p1'].includes(r.ref.object_id) || r.label === '下周开放试点。'),
    );
    expect(chosen).toEqual([
      passage('brief', 1, '下周开放试点。'),
      cited('test', 't3', 1, 6),
      cited('product', 'p1', 2, 5),
    ]);
  });

  it('adds nothing it cannot verify and says so', async () => {
    const seen: { error?: unknown } = {};
    const h = host({ 'test:t3:1': read('test', 't3', 1) });
    const chosen = await pickEvidence(
      h,
      { kinds: all, selected: [cited('product', 'p1', 2, 5)] },
      ticks((r) => r.ref.object_id === 't3', seen),
    );
    expect(String(seen.error)).toContain('1 项暂时无法核对确切版本');
    expect(chosen).toEqual([cited('product', 'p1', 2, 5)]);
  });

  it('rejects a server reference to another object', async () => {
    const seen: { error?: unknown } = {};
    const wrong = { ...read('test', 't3', 1), evidence_ref: cited('test', 't1', 1, 4) };
    const chosen = await pickEvidence(
      host({ 'test:t3:1': wrong }),
      { kinds: all },
      ticks((r) => r.ref.object_id === 't3', seen),
    );
    expect(seen.error).toBeTruthy();
    expect(chosen).toEqual([]);
  });

  it('keeps the current choice when the picker is closed', async () => {
    const selected = [passage('policy', 2, '住宿上限 400 元。'), cited('test', 't1', 1, 4)];
    const chosen = await pickEvidence(host({}), { kinds: all, selected }, async () => null);
    expect(chosen).toEqual(selected);
  });

  it('keeps references of kinds it does not offer', async () => {
    const config: EvidenceRefV2 = { ...cited('config', 'c', 1, 2), config_version: 1 };
    const chosen = await pickEvidence(
      host({}),
      { kinds: all, selected: [config, cited('test', 't1', 1, 4)] },
      ticks(() => false),
    );
    expect(chosen).toEqual([config]);
  });

  it('reads no work list when only passages are offered', async () => {
    const h = host({});
    await pickEvidence(h, {}, async () => null);
    expect(vi.mocked(h.query).mock.calls.map(([operation]) => operation)).toEqual(['timeline']);
  });
});

describe('a practice that changes while choosing', () => {
  const changed = {
    zh: '练习已切换，请核对后继续。',
    en: 'The practice changed. Check it before continuing.',
  };
  it('says so in the interface language when the practice is no longer on the server', async () => {
    const off = { ...host({}), snapshot: () => ({ ...regionHost().snapshot(), session: null }) };
    await expect(pickEvidence(off, { kinds: all }, async () => null)).rejects.toThrow(changed.zh);
    setPreference('en');
    await expect(pickEvidence(off, { kinds: all }, async () => null)).rejects.toThrow(changed.en);
  });

  it('adds nothing when another practice is open by the time the person confirms', async () => {
    let current: V4HostAdapter | null = host({});
    const outcome = new Promise((resolve, reject) =>
      answerEvidenceRequest(
        () => current,
        new CustomEvent('v4-choose-evidence', {
          detail: { sessionId: 's', pick: { kinds: all }, resolve, reject },
        }),
        async () => {
          current = {
            ...host({}),
            snapshot: () => ({
              ...regionHost().snapshot(),
              session: {
                protocol: 2 as const,
                sessionId: 'other',
                workLanguage: 'en' as const,
                scenarioHash: 'fixed',
              },
            }),
          };
          return [];
        },
      ),
    );
    await expect(outcome).rejects.toThrow(changed.zh);
  });
});

describe('evidenceSummary', () => {
  const refs: (EvidenceRefV2 | ObjectRef)[] = [
    passage('policy', 2, 'a'),
    passage('brief', 1, 'b'),
    cited('test', 't1', 1, 4),
    cited('product', 'p1', 2, 5),
  ];
  it('counts the chosen evidence by kind', () => {
    expect(evidenceSummary(refs)).toBe('已选依据：2 段资料 · 1 次测试 · 1 份作品');
    expect(evidenceSummary([])).toBe('还没有选择依据');
    setPreference('en');
    expect(evidenceSummary(refs)).toBe(
      'Selected evidence: 2 passages · 1 test run · 1 work version',
    );
    expect(evidenceSummary([])).toBe('No evidence selected');
  });
});
