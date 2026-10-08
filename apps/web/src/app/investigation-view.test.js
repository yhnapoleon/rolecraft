import { describe, it, expect, vi } from 'vitest';
import { investigationView, investigationSourceKey } from './investigation-view.js';

function fixture() {
  const run = {
    id: 'baseline',
    question: 'Which policy applies?',
    answer: 'Answer from v1',
    citations: [{ id: 'policy', title: 'Policy', version: 1 }],
    configVersion: 1,
    policyVersion: 2,
    indexVersion: 1,
  };
  const work = {
    id: 'work',
    title: 'Check policy',
    revision: 1,
    adopted: true,
    evidence: [],
    question: 'Why did the answer not change?',
    review: { focus: 'uncertain', note: '' },
    blocks: [
      {
        id: 'source',
        type: 'source_check',
        testId: run.id,
        material: { id: 'policy', version: 2 },
      },
      { id: 'rerun', type: 'retest', testId: run.id },
    ],
  };
  return {
    work,
    attempt: {
      id: 'attempt',
      tests: [run],
      world: { policyVersion: 3, indexVersion: 1 },
      backend: { materials: [{ id: 'policy', title: 'Policy', version: 3 }] },
    },
    session: {},
    mutable: true,
    canRun: true,
    cache: {},
    md: (text) => String(text ?? ''),
    diffHtml: vi.fn(() => '<p>verified diff</p>'),
    viewState: { modes: {}, open: {} },
  };
}

describe('investigation workpaper evidence and action boundaries', () => {
  it('does not fabricate a diff when either exact source is missing', () => {
    const f = fixture();
    f.cache[investigationSourceKey('attempt', f.work.blocks[0])] = {
      loading: false,
      selected: { content: 'v2 text' },
    };
    const html = investigationView(f);
    expect(f.diffHtml).not.toHaveBeenCalled();
    expect(html).toContain('investigation-load');
    expect(html).not.toContain('verified diff');
  });
  it('compares the selected versions even when the current source is newer', () => {
    const f = fixture();
    f.cache[investigationSourceKey('attempt', f.work.blocks[0])] = {
      loading: false,
      citation: { material: { id: 'policy', content: 'actual v1' } },
      selected: { id: 'policy', content: 'selected v2' },
    };
    const html = investigationView(f);
    expect(f.diffHtml).toHaveBeenCalledWith('actual v1', 'selected v2');
    expect(html).toContain('v3');
    expect(html).toContain('v2');
  });
  it('only offers explicit index refresh for an actual policy citation that is behind', () => {
    const f = fixture();
    expect(investigationView(f)).toContain('data-action="investigation-refresh-index"');
    f.attempt.world.indexVersion = 3;
    expect(investigationView(f)).not.toContain('data-action="investigation-refresh-index"');
    f.attempt.world.indexVersion = 1;
    f.attempt.tests[0].citations = [{ id: 'faq', version: 1 }];
    expect(investigationView(f)).not.toContain('data-action="investigation-refresh-index"');
  });
  it('keeps every rerun and restored reading state without turning results into a pass', () => {
    const f = fixture();
    f.attempt.tests.push(
      ...[1, 2, 3].map((i) => ({
        ...f.attempt.tests[0],
        id: 'run-' + i,
        answer: 'record-' + i,
        investigationId: f.work.id,
        blockId: 'rerun',
      })),
    );
    f.viewState.open['rerun:run-history'] = true;
    const html = investigationView(f);
    for (const i of [1, 2, 3]) expect(html).toContain('record-' + i);
    expect(html).toContain('data-key="rerun:run-history" open');
    expect(html).not.toContain('已验证通过');
  });
  it('keeps review text escaped and read-only actions disabled', () => {
    const f = fixture();
    f.mutable = false;
    f.canRun = false;
    f.readOnly = true;
    f.work.review.note = '</textarea><script>bad()</script>';
    const html = investigationView(f);
    expect(html).toContain('&lt;/textarea&gt;&lt;script&gt;');
    expect(html).not.toContain('<script>bad');
    expect(html).toMatch(/data-action="investigation-review-save"[^>]*disabled/);
    expect(html).toMatch(/data-action="investigation-refresh-index"[^>]*disabled/);
  });
});
