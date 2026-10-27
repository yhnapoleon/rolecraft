import { describe, expect, it } from 'vitest';
import { screenFromHistory } from './screen-history';
import type { AipmScreen } from '../../aipm/host';

describe('AIPM route history', () => {
  const screens: AipmScreen[] = [
    { kind: 'workbench' },
    { kind: 'worksheet', sheet: 'need' },
    { kind: 'worksheet', sheet: 'assurance', feature: 'evaluation' },
    { kind: 'worksheet', sheet: 'need', material: 'SD-120' },
    {
      kind: 'review',
      step: 'need',
      reviewRef: { session_id: 's', kind: 'aipm_section_review', object_id: 'r', version: 2 },
    },
  ];
  it('restores each previous screen, including the exact review and split material', () => {
    for (const screen of [...screens].reverse())
      expect(screenFromHistory({ aipm: screen, aipmSession: 's' }, 's')).toEqual(screen);
  });
  it('returns to the workbench for the original entry and never imports another session', () => {
    expect(screenFromHistory(null, 's')).toEqual(screens[0]);
    expect(screenFromHistory({ aipm: screens[2], aipmSession: 'other' }, 's')).toEqual(screens[0]);
    expect(
      screenFromHistory({ aipm: { kind: 'worksheet', sheet: 'oops' }, aipmSession: 's' }, 's'),
    ).toEqual(screens[0]);
  });
});
