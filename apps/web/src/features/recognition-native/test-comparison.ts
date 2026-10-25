import type { RecognitionRecord } from './badge';
export type TestRecord = {
  id: string;
  question: string;
  answer: string;
  indexVersion: number;
  policyVersion: number;
  configVersion: number;
  recognition?: RecognitionRecord[];
  citations?: { title?: string; version?: number; quote?: string }[];
};
/** Baseline selection belongs to the recognizer. Never replace a missing referenced run with a nearby run. */
export function comparisonFor(current: TestRecord, tests: TestRecord[]) {
  const drift = current.recognition?.find((r) => r.task === 'drift');
  const id = drift?.outputs?.previous_test_id;
  return {
    drift,
    previous: typeof id === 'string' ? tests.find((t) => t.id === id) : undefined,
    referenced: typeof id === 'string',
  };
}
