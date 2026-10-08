/** Native slot projection; the host activates it with the W03 mount, never over v1/local-only input. */
import type { LocalSession } from './types';
export function projectNativeWorkspace(a: any, s: LocalSession) {
  if (s.protocol === 2 && s.v2NativeWorkspace && s.v2Workspace) {
    a.tasks = s.v2Workspace.tasks
      .filter((t) => t.status !== 'removed')
      .map((t) => ({
        id: t.id,
        title: t.title,
        note: t.goal,
        priority: ['first', 'next', 'later'][t.priority] ?? 'next',
        status: t.status === 'active' ? 'working' : t.status,
        revision: t.revision,
        createdAt: t.created_at,
        updatedAt: t.updated_at,
      }));
    a.artifacts = s.v2Workspace.products.map((p) => ({
      id: p.product_id,
      taskId: p.task?.object_id ?? null,
      title: p.title,
      purpose:
        (
          {
            exploration: '探索笔记',
            test_plan: '测试计划',
            option: '方案比较',
            commitment: '试点决定',
            freeform: '自由作品',
            free_form: '自由作品',
          } as Record<string, string>
        )[p.purpose] ?? p.purpose,
      body: p.content,
      revision: p.version,
      kind:
        p.kind === 'test_plan' ? 'test_set' : p.kind === 'investigation' ? 'investigation' : 'text',
      // A returned agent work stays "to check" until the person adopts that exact version,
      // even though the person pressed import. Ordinary human writing is adopted by authorship.
      source: p.source_return_id || p.author.kind !== 'human' ? 'external-agent' : 'user',
      adopted:
        p.adoption?.status === 'adopted' || (!p.source_return_id && p.author.kind === 'human'),
      ...(p.source_return_id
        ? {
            returnId: p.source_return_id,
            ...(a.returnLinks?.[p.product_id]
              ? { requestId: a.returnLinks[p.product_id].requestId, packageLinked: true }
              : {}),
          }
        : {}),
      createdAt: p.created_at,
      updatedAt: p.created_at,
      removedAt: p.removed_at,
      evidence: (p.evidence_refs ?? []).map((r: any) => ({
        type: r.kind === 'test' ? 'test' : 'material',
        id: r.object_id,
        version: r.version,
      })),
      ...(p.kind === 'test_plan'
        ? {
            cases: (p.structured_payload?.cases ?? []).map((c: any) => ({
              ...c,
              question: c.query,
              expectation: c.declared_expected ?? '',
              refs: c.refs.map((r: any) => ({ id: r.object_id, version: r.version })),
            })),
          }
        : {}),
      ...(p.kind === 'investigation'
        ? {
            question: p.structured_payload?.question ?? '',
            blocks: (p.structured_payload?.blocks ?? []).map((b: any) => ({
              ...b,
              type: b.type === 'text' ? 'note' : b.type,
              testId: b.test_ref?.object_id,
              testIds: (b.test_refs ?? []).map((r: any) => r.object_id),
              material: b.source_ref
                ? { id: b.source_ref.object_id, version: b.source_ref.version }
                : undefined,
            })),
            review: {
              focus: p.structured_payload?.review_focus ?? 'uncertain',
              note: p.structured_payload?.review_note ?? '',
            },
          }
        : {}),
    }));
  }
}
