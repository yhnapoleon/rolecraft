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
    // A record line opens as a decision card line does ("开发人日：申请 6") and states the
    // decision in the panel's words with the decided amount in place ("还价 60，待接受" for
    // "还价待接受"); English writes them in lower case mid-sentence.
    const words = (text: string) => text.toLowerCase().replace(/[\d\s,，]/g, '');
    for (const record of records) {
      setPreference(record.language);
      const asked = record.language === 'en' ? ': requested' : '：申请';
      const lines = record.business_response.split('\n');
      for (const decision of record.decisions) {
        const opens = Object.keys(decision.requested).map(
          (key) => resourceNames()[key as ResourceKey] + asked,
        );
        const status = words(decisionNames()[decision.status]);
        expect(
          lines.filter(
            (line) => opens.every((open) => line.includes(open)) && words(line).includes(status),
          ),
          `${record.language} ${decision.status}`,
        ).toHaveLength(1);
      }
    }
  });
});
