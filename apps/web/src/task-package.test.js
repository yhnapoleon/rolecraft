import { describe, expect, it, vi } from 'vitest';
import { engine, memory } from './workbench-live-test-support';
import { LiveWorkbench } from './workbench-live';

/** A server-backed practice whose exact material versions come from the session host. */
function practice() {
  const live = new LiveWorkbench(engine, memory());
  const a = engine.createAttempt(engine.newState(), 'pilot');
  a.events.push({
    server: true,
    type: 'material_read',
    detail: { materialId: 'policy', version: 2 },
  });
  const session = {
    id: 's',
    protocol: 2,
    world: { version: 4 },
    tests: [],
    v2MaterialTitles: {},
    materials: [
      { id: 'brief', version: 1, title: 'Brief', content: '' },
      { id: 'policy', version: 2, title: 'Travel policy', content: '' },
    ],
  };
  vi.spyOn(live, 'session').mockReturnValue(session);
  // The session host is the server boundary: it answers exact-version reads.
  vi.spyOn(live.v4, 'host').mockReturnValue({
    query: async (_operation, input) => ({
      content: {
        title: `${input.object_id} title`,
        fragments: [
          { text: `Exact text of ${input.object_id}`, ref: { object_id: input.object_id } },
        ],
      },
    }),
    draft: () => [],
    keepDraft: async () => {},
  });
  return { live, a };
}

describe('task package documents', () => {
  it('carries each read document text once, in the content field', async () => {
    const { live, a } = practice();
    const pkg = await live.preparePackageExact(a, null, { requestId: 'request-1' });
    expect(pkg.schema).toBe('practice-task-package/v1');
    expect(pkg.materials).toEqual([
      { id: 'brief', version: 1, title: 'brief title', content: 'Exact text of brief' },
      { id: 'policy', version: 2, title: 'policy title', content: 'Exact text of policy' },
    ]);
    expect(JSON.stringify(pkg).split('Exact text of policy')).toHaveLength(2);
  });
});
