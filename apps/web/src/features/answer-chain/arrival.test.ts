import { describe, expect, it } from 'vitest';
import { holdsStageUnderDocument, selectSettled } from './arrival';

const fresh = () =>
  ({ testHistory: {}, testModes: {}, lastRun: null, settledRun: null }) as {
    testHistory: Record<string, string>;
    testModes: Record<string, string>;
    lastRun: string | null;
    settledRun: string | null;
  };

describe('a queued test that settles in the background', () => {
  it('selects the arrived result on its case and as the latest run', () => {
    const ui = fresh();
    selectSettled(ui, { caseId: 'case-1', testId: 't-9' });
    expect(ui).toEqual({
      testHistory: { 'case-1': 't-9' },
      testModes: { 'case-1': 'result' },
      lastRun: 't-9',
      settledRun: 't-9',
    });
    const bench = fresh();
    selectSettled(bench, { caseId: null, testId: 't-2' });
    expect(bench.testHistory).toEqual({});
    expect(bench.lastRun).toBe('t-2');
  });

  it('redraws the stage under an open document once the arrived run is loaded', () => {
    const ui = { settledRun: 't-9' };
    expect(holdsStageUnderDocument(ui, [], true)).toBe(true);
    expect(holdsStageUnderDocument(ui, [{ id: 't-9' }], true)).toBe(false);
    expect(holdsStageUnderDocument({ settledRun: null }, [{ id: 't-9' }], true)).toBe(true);
    expect(holdsStageUnderDocument({ settledRun: null }, [], false)).toBe(false);
  });
});
