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

/** One unambiguous monetary value in the saved answer; never infer a limit from other numbers. */
export function singleAnswerAmount(answer: string) {
  const found = new Map<string, {value: string; currency: string}>();
  const pattern = /(?:(CNY|RMB|USD|SGD)\s*(\d[\d,]*(?:\.\d+)?)|(\d[\d,]*(?:\.\d+)?)\s*元)/gi;
  for (const m of answer.matchAll(pattern)) {
    const value = (m[2] ?? m[3]).replaceAll(',', '');
    const currency = !m[1] || /CNY|RMB/i.test(m[1]) ? 'CNY' : m[1].toUpperCase();
    found.set(`${currency}:${value}`, {value,currency});
  }
  return found.size === 1 ? [...found.values()][0] : null;
}
