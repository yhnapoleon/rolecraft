import { describe, expect, it } from 'vitest';
import { type ProgressFacts, carried, distillation, progressOf } from './progress';

const base = (over: Partial<ProgressFacts> = {}): ProgressFacts => ({
  tests: [],
  asked: [],
  works: [],
  policyVersion: 1,
  configVersion: 0,
  baseConfigVersion: 0,
  pendingRequests: 0,
  approvedRequests: 0,
  delivered: false,
  feedback: false,
  ...over,
});
const test = (id: string, over: Partial<ProgressFacts['tests'][number]> = {}) => ({
  id,
  policyVersion: 1,
  configVersion: 0,
  noted: false,
  ...over,
});
const state = (f: ProgressFacts) =>
  Object.fromEntries(progressOf(f).layers.map((l) => [l.id, l.state]));

describe('progressOf', () => {
  it('starts on taking the brief on, with the next two layers named', () => {
    const p = progressOf(base());
    expect(p.current).toBe('own');
    expect(p.next).toEqual(['understand', 'decide']);
    expect(p.layers[0].missing.length).toBeGreaterThan(0);
  });

  it('a first test passes taking it on, not understanding', () => {
    const p = progressOf(base({ tests: [test('t1')] }));
    expect(p.current).toBe('understand');
    expect(state(base({ tests: [test('t1')] })).own).toBe('done');
  });

  it('accepting in the walk-in counts as taking it on', () => {
    expect(progressOf(base({ accepted: true })).current).toBe('understand');
  });

  it('understanding needs a judgement tied to evidence, not just a test', () => {
    expect(progressOf(base({ tests: [test('t1')], asked: ['business'] })).current).toBe(
      'understand',
    );
    expect(progressOf(base({ tests: [test('t1', { noted: true })] })).current).toBe('decide');
    const cited = base({
      tests: [test('t1')],
      works: [{ id: 'w', decision: false, hasBody: true, evidence: [{ kind: 'test', id: 't1' }] }],
    });
    expect(progressOf(cited).current).toBe('decide');
  });

  it('a draft decision alone never forms the decision', () => {
    const f = base({
      tests: [test('t1', { noted: true })],
      works: [{ id: 'd', decision: true, hasBody: true, evidence: [] }],
    });
    const p = progressOf(f);
    expect(p.current).toBe('decide');
    expect(p.layers[2].confirmed.length).toBe(1);
    expect(p.layers[2].missing[0][1]).toMatch(/draft alone/);
  });

  it('a cited decision moves on to verifying; applying without a retest does not pass it', () => {
    const decided = {
      tests: [test('t1', { noted: true })],
      works: [
        { id: 'd', decision: true, hasBody: true, evidence: [{ kind: 'test' as const, id: 't1' }] },
      ],
    };
    expect(progressOf(base(decided)).current).toBe('verify');
    const applied = base({ ...decided, configVersion: 1 });
    expect(progressOf(applied).current).toBe('verify');
    expect(progressOf(applied).layers[3].missing[0][1]).toMatch(/Test again on settings v1/);
    const retested = base({
      ...decided,
      configVersion: 1,
      tests: [...decided.tests, test('t2', { configVersion: 1 })],
    });
    expect(progressOf(retested).current).toBe('deliver');
  });

  it('a pending request is listed as still missing, never as done', () => {
    const p = progressOf(base({ pendingRequests: 1 }));
    expect(p.layers[3].missing.some((m) => /waiting/.test(m[1]))).toBe(true);
  });

  it('a policy change reopens understanding only; the frontier stays', () => {
    const f = base({
      policyVersion: 2,
      tests: [test('t1', { noted: true })],
      works: [{ id: 'd', decision: true, hasBody: true, evidence: [{ kind: 'test', id: 't1' }] }],
    });
    const p = progressOf(f);
    expect(p.current).toBe('verify');
    expect(state(f).understand).toBe('reopened');
    expect(state(f).decide).toBe('reopened');
    expect(state(f).own).toBe('done');
    expect(carried(p).length).toBe(2);
  });

  it('testing on the new policy closes the reopening', () => {
    const f = base({
      policyVersion: 2,
      tests: [test('t1', { noted: true }), test('t2', { policyVersion: 2 })],
    });
    expect(state(f).understand).toBe('done');
  });

  it('a practice that started on the new policy is not reopened', () => {
    const f = base({ policyVersion: 2, tests: [test('t1', { policyVersion: 2, noted: true })] });
    expect(state(f).understand).toBe('done');
  });

  it('delivered: reviewing is current, skipped layers are uncovered, not failed', () => {
    const f = base({ tests: [test('t1')], delivered: true });
    const s = state(f);
    expect(progressOf(f).current).toBe('reflect');
    expect(s.deliver).toBe('done');
    expect(s.understand).toBe('uncovered');
    expect(s.verify).toBe('uncovered');
    expect(progressOf(f).next).toEqual([]);
  });

  it('the distillation repeats only what the records show', () => {
    const f = base({ tests: [test('t1', { noted: true })], pendingRequests: 1 });
    const d = distillation(progressOf(f), 'understand');
    expect(d?.confirmed.map((t) => t[1])).toContain('Expectations or diagnoses are recorded; you still judge the match');
    expect(d?.kept.some((t) => /waiting/.test(t[1]))).toBe(true);
    expect(distillation(progressOf(f), 'decide')).toBeNull();
  });
});

it('distills actual indexed answers without treating inherited expectations as independent judgements', () => {
 const tests=[test('old',{answer:'cap 500',indexVersion:1}),test('near',{answer:'cap 400',indexVersion:2}),test('now',{answer:'cap 400',indexVersion:2,previousTestId:'old',noted:true})];
 const facts=progressOf(base({tests})).layers.find(l=>l.id==='understand')?.confirmed.map(t=>t[1]).join(' ');
 expect(facts).toContain('Index v1 answered “cap 500”');expect(facts).toContain('Index v2 answered “cap 400”');expect(facts).not.toContain('Your judgement on 3');
});

it('retains the actual amount in a long English answer instead of clipping it after the lead-in', () => {
 const answer='Expense-management notice: the hotel reimbursement cap for domestic business travel is now CNY 400 per person per night. Costs above the cap require approval.';
 const p=progressOf(base({tests:[test('now',{answer,indexVersion:2,noted:true})]}));
 const summary=p.layers.find(l=>l.id==='understand')?.confirmed.map(t=>t[1]).join(' ');
 expect(summary).toContain('CNY 400');expect(summary).toContain('per person per night');expect(summary).not.toContain('CNY 500');
});
