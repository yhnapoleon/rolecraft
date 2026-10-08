import { describe, it, expect } from 'vitest';
import { feedbackSemanticPresentation } from './index';

const advice = {
  criterion: 'R2.support',
  source: 'model_advice',
  label: 'PARTIAL',
  explanation: 'Persisted model advice',
  citations: [],
};
const pending = { ...advice, source: 'pending', label: 'INSUFFICIENT' };
describe('feedback slot is independent of colleague configuration', () => {
  it.each(['placeholder', 'provider'] as const)(
    'role mode %s cannot imply feedback availability',
    (modelMode) => {
      expect(
        feedbackSemanticPresentation({ items: [pending] }, { modelMode }).waitingForModel,
      ).toBe(true);
      expect(
        feedbackSemanticPresentation(
          { semantic_status: 'waiting_for_model', items: [advice] },
          { modelMode },
        ).advice,
      ).toEqual([]);
    },
  );
  it('uses a report status before the current slot state', () => {
    const result = feedbackSemanticPresentation(
      { semantic_status: 'waiting_for_model', items: [advice] },
      { semanticStatus: 'available', modelMode: 'provider' },
    );
    expect(result.waitingForModel).toBe(true);
    expect(result.advice).toEqual([]);
  });
  it('does not hide actual feedback advice when colleagues are local', () => {
    const result = feedbackSemanticPresentation(
      { semantic_status: 'available', items: [advice, pending] },
      { modelMode: 'placeholder' },
    );
    expect(result.waitingForModel).toBe(false);
    expect(result.advice).toEqual([advice]);
  });
  it.each(['pending', 'failed'] as const)(
    'own %s state means verification remains pending',
    (semanticStatus) => {
      expect(
        feedbackSemanticPresentation(
          { items: [pending] },
          { semanticStatus, modelMode: 'placeholder' },
        ).waitingForModel,
      ).toBe(false);
    },
  );
  it('retains historical model advice without inferring current provider availability', () => {
    const result = feedbackSemanticPresentation({ items: [advice] }, { modelMode: 'placeholder' });
    expect(result.status).toBeUndefined();
    expect(result.advice).toEqual([advice]);
  });
});
