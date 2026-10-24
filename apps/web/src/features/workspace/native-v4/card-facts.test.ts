import { describe, expect, it } from 'vitest';
import { provideTaskCardFacts, taskCardFacts, testFacts } from './card-facts';

describe('board card facts', () => {
  it('counts only the tests run for that task', () => {
    const tests = [
      { taskId: 't1', policyVersion: 1 },
      { taskId: 't2', policyVersion: 1 },
      { taskId: 't1', policyVersion: 1 },
    ];
    expect(testFacts(tests, 't1', 1)).toEqual({ tests: 2, testsPredatePolicy: false });
  });
  it('marks tests as predating the policy update only when none ran on the current version', () => {
    expect(testFacts([{ taskId: 't1', policyVersion: 1 }], 't1', 2)).toEqual({
      tests: 1,
      testsPredatePolicy: true,
    });
    // A retest on the new policy clears the flag, whatever older runs exist.
    expect(
      testFacts(
        [
          { taskId: 't1', policyVersion: 1 },
          { taskId: 't1', policyVersion: 2 },
        ],
        't1',
        2,
      ).testsPredatePolicy,
    ).toBe(false);
  });
  it('does not claim staleness without tests or without a known policy version', () => {
    expect(testFacts([], 't1', 2).testsPredatePolicy).toBe(false);
    expect(testFacts([{ taskId: 't1', policyVersion: null }], 't1', 2).testsPredatePolicy).toBe(
      false,
    );
    expect(testFacts([{ taskId: 't1', policyVersion: 1 }], 't1', undefined).testsPredatePolicy).toBe(
      false,
    );
  });
  it('reads the registered provider and shows nothing when it is missing or fails', () => {
    provideTaskCardFacts(null);
    expect(taskCardFacts('t1')).toBeNull();
    provideTaskCardFacts((id) =>
      id === 't1' ? { tests: 1, testsPredatePolicy: false, reminders: ['technical'] } : null,
    );
    expect(taskCardFacts('t1')?.reminders).toEqual(['technical']);
    expect(taskCardFacts('t2')).toBeNull();
    provideTaskCardFacts(() => {
      throw new Error('projection not ready');
    });
    expect(taskCardFacts('t1')).toBeNull();
    provideTaskCardFacts(null);
  });
});
