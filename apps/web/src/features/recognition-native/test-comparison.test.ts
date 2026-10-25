import { expect, it } from 'vitest';
import { comparisonFor, type TestRecord } from './test-comparison';
const old: TestRecord = {
  id: 'old',
  question: 'cap?',
  answer: '500',
  indexVersion: 1,
  policyVersion: 1,
  configVersion: 0,
};
const previous = { ...old, id: 'previous', answer: '400', indexVersion: 2 };
const latest = {
  ...previous,
  id: 'latest',
  recognition: [
    { task: 'drift', recognizer_id: 'drift', revision: 'r', outputs: { previous_test_id: 'old' } },
  ],
};
it('uses the recognizer baseline even when the immediate previous run also answered 400', () => {
  expect(comparisonFor(latest, [old, previous, latest]).previous).toBe(old);
});
it('leaves unavailable baselines unknown instead of substituting the previous run', () => {
  expect(comparisonFor(latest, [previous, latest])).toMatchObject({
    referenced: true,
    previous: undefined,
  });
});
