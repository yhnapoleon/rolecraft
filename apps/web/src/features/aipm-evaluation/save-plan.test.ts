/** Saving the cases: the saved plan is found in the host's real response shape, and a retry
 * after a failed batch reuses that plan instead of saving another copy. */
import { describe, expect, it, vi } from 'vitest';
import en from '../../../../../scenarios/pm_pilot/aipm-phase1/public/evaluation.en.json';
import type { AipmDesign } from '../../aipm/types';
import { createEvaluationDesk, savedPlanOf } from './index';
import type { EvaluationContent } from './model';

const planRef = { session_id: 's', kind: 'product', object_id: 'plan', version: 1 };
/** `work_products.create` through the data host: a command envelope around `{ object, ref }`. */
const created = (cases: { id: string }[]) => ({
  requestId: 'r',
  status: 'confirmed',
  result: {
    object: { product_id: 'plan', version: 1, structured_payload: { type: 'test_plan', cases } },
    ref: planRef,
    as_of: { session_id: 's', seq: 3 },
  },
});
const design = {
  id: 'design',
  session_id: 's',
  revision: 2,
  rows: [{ id: 'r1', revision: 1, need_ref: 'n1', route: 'retrieval_generation' }],
} as unknown as AipmDesign;

describe('saving the evaluation plan', () => {
  it('reads the saved plan from the command envelope', () => {
    expect(savedPlanOf(created([{ id: 'c1' }, { id: 'c2' }]))).toEqual({
      ref: planRef,
      ids: ['c1', 'c2'],
    });
    expect(savedPlanOf({ status: 'confirmed', result: { ref: planRef } })).toBeUndefined();
  });

  it('creates the batch from the saved plan, and a retry does not save the plan twice', async () => {
    const createWorkVersion = vi.fn(async (input: { structured_payload: { cases: [] } }) =>
      created(input.structured_payload.cases),
    );
    let batchCalls = 0;
    const command = vi.fn(async (operation: string, payload: Record<string, unknown>) => {
      expect(operation).toBe('aipm.batch.create');
      expect(payload.plan_ref).toEqual(planRef);
      batchCalls += 1;
      if (batchCalls === 1) return { status: 'failed', result: { code: 'busy' } };
      return { status: 'confirmed', result: { batch: { id: 'batch', revision: 1, cases: [] } } };
    });
    const desk = createEvaluationDesk(
      {
        getSessionContext: () => ({ sessionId: 's', workLanguage: 'en', readOnly: false }),
        getClient: () => ({
          readBatch: async () => ({
            result: { batch: { id: 'batch', revision: 1, cases: [] }, summary: {} },
          }),
          readDesign: async () => ({}),
        }),
        readProgress: async () => ({}),
        command,
        createWorkVersion: createWorkVersion as never,
        sendPreparedTest: async () => ({}),
        readContent: async () => en,
      },
      { content: { en: en as EvaluationContent } },
    );
    desk.state.design = design;
    desk.state.drafts = [
      {
        key: 'd1',
        rowId: 'r1',
        route: 'retrieval_generation',
        caseType: 'in_scope',
        query: 'Hotel cap?',
        expected: 'Cites the current policy.',
        answerOnly: false,
      },
    ];
    await desk.savePlan();
    expect(desk.state.notice?.kind).toBe('error');
    await desk.savePlan();
    expect(createWorkVersion).toHaveBeenCalledTimes(1);
    expect(command).toHaveBeenCalledTimes(2);
    expect(desk.state.view?.batch.id).toBe('batch');
    expect(desk.state.tab).toBe('run');
  });
});
