import { describe, expect, it } from 'vitest';
import type { EvidenceRefV2 } from '../../aipm/types';
import {
  type Block,
  fromText,
  headings,
  insertAt,
  quoteRefs,
  readChoice,
  readMetric,
  type SheetDesign,
  toText,
  writeChoice,
  writeMetric,
} from './sheet-model';

const ref: EvidenceRefV2 = {
  session_id: 's',
  kind: 'material',
  object_id: 'demand',
  version: 1,
  span_start: 4,
  span_end: 30,
  observed_at_seq: 7,
  quote: 'elapsed_minutes: 从建单到结单的分钟数。',
};
const base: SheetDesign = { id: 'aipm-design', session_id: 's', revision: 1 };
const strip = (blocks: Block[]) => blocks.map(({ id: _id, ...rest }) => rest);

describe('worksheet text', () => {
  it('round-trips headings, paragraphs and exact quotes through plain PRD text', () => {
    const blocks: Block[] = [
      { id: '1', type: 'p', text: '新员工反复来问报销怎么办。' },
      { id: '2', type: 'h', text: '这个数字怎么算出来的' },
      { id: '3', type: 'quote', text: ref.quote ?? '', label: '《SD-120》v1', ref },
      { id: '4', type: 'p', text: '所以平均 429 分钟是总时长。' },
    ];
    const text = toText(blocks);
    expect(text).toContain('### 这个数字怎么算出来的');
    expect(text).toContain('> — 《SD-120》v1');
    const back = fromText(text, quoteRefs(blocks));
    expect(strip(back)).toEqual(strip(blocks));
    // The reference is copied as read, never rebased.
    expect(quoteRefs(back)[0]).toBe(ref);
  });
  it('keeps an unmatched quote as plain text instead of inventing a reference', () => {
    const back = fromText('> 没有出处的话\n> — 《X》v1', []);
    expect(back).toHaveLength(1);
    expect(back[0].type).toBe('p');
  });
  it('splits the paragraph at the caret when inserting a subheading', () => {
    const blocks: Block[] = [{ id: 'p', type: 'p', text: '前半句后半句' }];
    const out = insertAt(blocks, { id: 'p', offset: 3 }, { id: 'h', type: 'h', text: '角度' });
    expect(strip(out)).toEqual([
      { type: 'p', text: '前半句' },
      { type: 'h', text: '角度' },
      { type: 'p', text: '后半句' },
    ]);
    expect(headings(out)).toEqual(['角度']);
  });
  it('appends without a caret and leaves an empty paragraph to keep writing', () => {
    const out = insertAt([{ id: 'p', type: 'p', text: '' }], null, {
      id: 'h',
      type: 'h',
      text: 'A',
    });
    expect(strip(out)).toEqual([
      { type: 'h', text: 'A' },
      { type: 'p', text: '' },
    ]);
  });
});

describe('worksheet choice', () => {
  it.each([
    ['business', 'external'],
    ['stakeholders', 'chen'],
    ['need', 'supported'],
    ['solution', '方案 A'],
    ['decision', 'launch_narrow'],
  ] as const)('stores the %s choice where the rules read it', (step, value) => {
    const d = writeChoice(step, base, value);
    expect(readChoice(step, d)).toBe(value);
    expect(readChoice(step, writeChoice(step, d, value))).toBe(value);
  });
  it.each(['business', 'stakeholders', 'need', 'solution', 'decision'] as const)(
    'leaves the %s design untouched when nothing is chosen',
    (step) => {
      expect(writeChoice(step, base, '')).toBe(base);
    },
  );
  it('marks the chosen decision-maker as the approver, once', () => {
    const d = writeChoice('stakeholders', writeChoice('stakeholders', base, 'chen'), 'grace');
    expect(d.stakeholders).toEqual([
      expect.objectContaining({ name_or_role: 'grace', relationships: ['approver'] }),
    ]);
  });
  it('keeps the business text fields when only the audience changes', () => {
    const d = writeChoice(
      'business',
      { ...base, business: { audience: 'unknown', offering_explanation: 'x', task_goal: 'y' } },
      'internal',
    );
    expect(d.business).toEqual({ audience: 'internal', offering_explanation: 'x', task_goal: 'y' });
  });
});

describe('worksheet metric block', () => {
  it('writes nothing until the need status is chosen', () => {
    expect(writeMetric(base, '', { kind: 'labor_time' })).toBe(base);
  });
  it('stores the metric on the main need the metric_scope rule reads', () => {
    const d = writeMetric(writeMetric(base, 'supported', { kind: 'labor_time' }), 'supported', {
      source_field: 'elapsed_minutes',
    });
    expect(readMetric(d)).toMatchObject({ kind: 'labor_time', source_field: 'elapsed_minutes' });
    expect(readChoice('need', d)).toBe('supported');
    expect(d.needs).toHaveLength(1);
  });
});
