import { afterEach, describe, expect, it } from 'vitest';
import { setPreference } from '../../app/i18n';
import { asFake, fakeDocument } from '../results-native/fake-dom';
import { decisionNames, resourceNames, type ResourceKey } from '../roles-native/decision-words';
import { renderDecisions } from './business-decisions';
// Records the backend wrote for one scenario; test_business_response_record.py keeps them true.
import recorded from './business-response.fixtures.json';
import type { Report } from './index';

const report = (subject: string, response: string): Report => ({
  id: 'f',
  version: 1,
  subject: { session_id: 's', kind: subject, object_id: 'x', version: 1 },
  items: [],
  business_response: response,
  next_options: [],
});
const records = (['zh', 'en'] as const).flatMap((language) =>
  Object.values(recorded[language]).map((record) => ({ language, ...record })),
);

afterEach(() => setPreference('zh'));

describe('recorded business decisions', () => {
  it('shows each line of the record as written, in its order', () => {
    for (const record of records) {
      const shown = asFake(
        renderDecisions(fakeDocument(), report('submission', record.business_response)),
      );
      expect(shown.className).toBe('business-decisions');
      expect(shown.byTag('p').map((line) => line.textContent)).toEqual(
        record.business_response.split('\n'),
      );
    }
    expect(records.some((record) => record.business_response.includes('\n'))).toBe(true);
  });

  it('keeps a review or a record without decisions as written', () => {
    for (const text of ['当前没有可核验的业务决定记录。', '']) {
      const shown = asFake(renderDecisions(fakeDocument(), report('review', text)));
      expect(shown.textContent).toBe(text);
    }
    const blank = asFake(renderDecisions(fakeDocument(), report('submission', 'a\n\nb\n')));
    expect(blank.byTag('p').map((line) => line.textContent)).toEqual(['a', 'b']);
  });

  it('names resources and decisions in the request panel the way the record does', () => {
    for (const record of records) {
      setPreference(record.language);
      const lines = record.business_response.split('\n');
      for (const decision of record.decisions) {
        const words = [
          ...Object.keys(decision.requested).map((key) => resourceNames()[key as ResourceKey]),
          decisionNames()[decision.status],
        ];
        expect(
          lines.filter((line) => words.every((word) => line.includes(word))),
          `${record.language} ${decision.status}`,
        ).toHaveLength(1);
      }
    }
  });
});
