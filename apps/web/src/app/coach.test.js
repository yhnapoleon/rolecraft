import { describe, expect, it } from 'vitest';
import { notes } from './coach.js';

describe('index reminder follows the current workspace', () => {
  it('retires the reminder after the index catches up while keeping the old test', () => {
    const stale = { id: 'old-test', question: 'Hotel limit?', stale: true };
    const attempt = {
      world: { capacity: 30, policyVersion: 2, indexVersion: 1 },
      tasks: [], tests: [stale], events: [], conversations: {}, acks: [],
    };
    const engine = { currentArtifacts: () => [] };
    expect(notes(attempt, engine).map((n) => n.key)).toContain('stale-index');
    attempt.world.indexVersion = 2;
    expect(notes(attempt, engine).map((n) => n.key)).not.toContain('stale-index');
    expect(attempt.tests).toEqual([stale]);
  });
});
