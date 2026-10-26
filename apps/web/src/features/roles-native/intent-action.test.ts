import { it, expect } from 'vitest';
import { intentAction } from './intent-action';
import type { RecognitionRecord } from '../recognition-native/badge';
const record = (label: string, score?: number): RecognitionRecord => ({
  task: 'intent',
  recognizer_id: 'intent-tfidf-lr-v1',
  revision: 'test',
  label,
  score,
});
it('offers the request form only for a confident saved resource or approval intent', () => {
  for (const label of ['seek_approval', 'ask_resource'])
    expect(intentAction([record(label, 0.85)], [], 'en')?.kind).toBe('request');
});
it('hides other, missing, invalid and low confidence intents', () => {
  for (const r of [
    record('other', 1),
    record('ask_limit', 0.9),
    record('seek_approval', 0.69),
    record('seek_approval'),
    record('seek_approval', NaN),
    record('seek_approval', 1.2),
  ])
    expect(intentAction([r], [], 'zh')).toBeNull();
  expect(intentAction([], [], 'zh')).toBeNull();
});
it('opens only a process source cited in the same reply', () => {
  const ref = { id: 'approvals', title: 'Approval process', version: 2 };
  expect(intentAction([record('ask_process', 0.8)], [ref], 'en')).toMatchObject({
    kind: 'material',
    material: ref,
  });
  expect(intentAction([record('ask_process', 0.8)], [], 'en')).toBeNull();
});
it('uses the latest intent on this reply without reclassifying text', () => {
  expect(intentAction([record('seek_approval', 0.9), record('other', 0.9)], [], 'zh')).toBeNull();
});
