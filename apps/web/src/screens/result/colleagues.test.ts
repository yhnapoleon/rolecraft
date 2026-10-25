import { describe, expect, it } from 'vitest';
import { criterionLabels } from '../../features/feedback-native/criteria';
import { COLLEAGUE_CRITERIA, colleagueOf } from './colleagues';

describe('206 result: by colleague', () => {
  const ids = Object.values(COLLEAGUE_CRITERIA).flat();
  it('names each rubric criterion by its id, once, fourteen in all', () => {
    const known = criterionLabels('en');
    expect(ids).toHaveLength(14);
    expect(new Set(ids).size).toBe(14);
    for (const id of ids) expect(known[id], id).toBeTruthy();
  });
  it('follows the plan’s table', () => {
    expect(colleagueOf('R3.capacity')).toBe('manager');
    expect(colleagueOf('R2.support')).toBe('business');
    expect(colleagueOf('R6.consistency')).toBe('technical');
    expect(colleagueOf('decision.rationale')).toBeNull();
  });
});
