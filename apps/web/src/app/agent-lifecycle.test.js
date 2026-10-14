import { describe, expect, it } from 'vitest';
import { engine } from '../workbench-live-test-support';
import * as Coach from './coach.js';

/** A test plan the person's agent brought back for the first task, adopted. */
function adoptedPlan() {
  const a = engine.createAttempt(engine.newState(), 'pilot');
  const pkg = engine.preparePackage(a, a.tasks[0].id, { record: true });
  const plan = engine.importReturn(
    a,
    JSON.stringify({
      schemaVersion: 1,
      returnId: 'return-plan',
      requestId: pkg.requestId,
      artifact: {
        kind: 'test_set',
        title: '上线前检查',
        purpose: '测试计划',
        cases: [{ question: '国内出差住宿每晚上限是多少？', intent: '核对政策版本', refs: [] }],
      },
    }),
    a.tasks[0].id,
  ).artifact;
  engine.adoptArtifact(a, plan.id);
  return { a, plan };
}

/** A recorded run, linked to a plan row when the person ran it from the plan. */
const run = (id, link = {}) => ({
  id,
  question: '国内出差住宿每晚上限是多少？',
  createdAt: new Date().toISOString(),
  ...link,
});

describe('the lifecycle strip of a test plan from the agent', () => {
  it('counts the runs of the plan’s own questions as linked tests', () => {
    const { a, plan } = adoptedPlan();
    expect(engine.agentProgress(a, plan)).toMatchObject({ adopted: true, linkedRuns: 0 });
    a.tests.push(run('run-1', { workId: plan.id, caseId: plan.cases[0].id }));
    expect(engine.agentProgress(a, plan)).toMatchObject({ linked: true, linkedRuns: 1 });
    a.tests.push(run('run-2', { workId: plan.id, caseId: plan.cases[0].id }));
    expect(engine.agentProgress(a, plan)).toMatchObject({ linked: true, linkedRuns: 2 });
  });

  it('does not count a run asked on the bench outside the plan', () => {
    const { a, plan } = adoptedPlan();
    a.tests.push(run('bench-run'));
    expect(engine.agentProgress(a, plan)).toMatchObject({ linked: false, linkedRuns: 0 });
  });

  it('stops the colleague reminder and the feedback check once the plan has run', () => {
    const { a, plan } = adoptedPlan();
    const reminded = () => Coach.notes(a, engine).some((n) => n.key === `adopt-${plan.id}`);
    const flagged = () =>
      Coach.observations(a, engine).some((o) => o.refs.some((ref) => ref.id === plan.id));
    expect([reminded(), flagged()]).toEqual([true, true]);
    a.tests.push(run('run-1', { workId: plan.id, caseId: plan.cases[0].id }));
    expect([reminded(), flagged()]).toEqual([false, false]);
  });
});
