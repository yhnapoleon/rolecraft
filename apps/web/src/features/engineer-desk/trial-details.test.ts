import { afterEach, describe, expect, it } from 'vitest';
import { setPreference } from '../../app/i18n';
import fallback from './fixtures/trial-245-fallback.en.json';
import realtime from './fixtures/trial-245-realtime.en.json';
import {
  experimentLimits,
  experimentRows,
  listedExperiment,
  type Experiment,
  type TicketDetail,
} from './model';
import { lineRows } from './steps/tape';
import { FakeElement, FakeNode } from '../results-native/fake-dom';

function documentForRows() {
  const doc = {
    createElement(tag: string) {
      const node = new FakeElement(tag);
      return Object.assign(node, {
        ownerDocument: doc,
        appendChild(child: FakeNode) {
          node.append(child);
          return child;
        },
      });
    },
    createTextNode: (text: string) => new FakeNode(text),
  };
  return doc as unknown as Document;
}

afterEach(() => setPreference('zh'));
describe('249 · original 245 engineer candidates', () => {
  it('keeps both failures and their exact cited versions on their own candidate', () => {
    setPreference('en');
    const first = experimentRows(fallback as unknown as Experiment);
    const second = experimentRows(realtime as unknown as Experiment);
    expect(first.map((row) => row.result)).toEqual(['fail', 'pass', 'pass', 'pass']);
    expect(second.map((row) => row.result)).toEqual(['fail', 'pass', 'pass', 'pass']);
    expect(first[0].actual).toBe('a handoff to a person');
    expect(first[0].citations).toBe('No citation');
    expect(second[0].citations).toBe('Cites Travel policy v1');
    expect(second[0].answer).toContain('CNY 500');
  });
});

describe('249 · engineering run details on the page', () => {
  it('renders expected, actual, answer, citation versions and effective limitations from the original runs', () => {
    setPreference('en');
    const ticket = { id: realtime.ticket_id, work_language: 'en' } as TicketDetail;
    for (const raw of [fallback, realtime]) {
      const full = listedExperiment(raw as unknown as Experiment, ticket.id);
      if (!full) throw new Error('Original trial rows must be available');
      const node = lineRows(documentForRows(), ticket, full, full, []) as unknown as FakeElement;
      expect(node.byClass('ed-row')).toHaveLength(4);
      expect(node.textContent).toContain('Expected:');
      expect(node.textContent).toContain('Got:');
      expect(node.textContent).toContain('Did not pass');
      expect(node.textContent).toContain(raw.rows[0].answer_summary);
      expect(node.textContent).toContain('Cites Office FAQ v1');
      expect(node.textContent).not.toContain('stay with your agent');
      if (raw.id === realtime.id) {
        expect(node.textContent).toContain('Cites Travel policy v1');
        expect(node.textContent).toContain(
          'Real-time sync was not provisioned; updates remain daily.',
        );
      }
    }
  });

  it('localizes recorded limitation codes and explicitly identifies omitted older rows', () => {
    expect(experimentLimits(realtime as unknown as Experiment)).toEqual([
      '实时同步未配置，仍按每日更新。',
    ]);
    const summary = { ...fallback, rows: undefined, rows_omitted: true } as unknown as Experiment;
    const ticket = { work_language: 'zh' } as TicketDetail;
    const node = lineRows(
      documentForRows(),
      ticket,
      summary,
      undefined,
      [],
    ) as unknown as FakeElement;
    expect(node.textContent).toContain('因读取上限未载入');
    expect(node.byClass('ed-row')).toHaveLength(0);
  });
});
