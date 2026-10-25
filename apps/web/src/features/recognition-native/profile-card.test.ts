import { describe, expect, it } from 'vitest';
import type { RecognitionRecord } from './badge';
import { cardHtml, runMode, TASK_ROW } from './profile-card';
import { cardsHtml, lensSignal } from './signals';

const scope: RecognitionRecord = {
  recognizer_id: 'scope-mahalanobis-v1',
  revision: 'f05ba8',
  task: 'scope',
  label: 'in',
  score: 1.09,
  threshold: 1.32,
  outputs: { fit_key: 'pm_pilot/zh/scope_off' },
  fallback: false,
};
const drift: RecognitionRecord = {
  recognizer_id: 'drift-cosine-v1',
  revision: 'unhashed',
  task: 'drift',
  label: 'anomaly',
  score: 0.02,
  threshold: 0.14,
  outputs: { numeric_change: true, numbers_before: ['500'], numbers_after: ['400'] },
};
const ruleScope: RecognitionRecord = {
  recognizer_id: 'scope-mahalanobis-v1',
  revision: 'rule',
  task: 'scope',
  label: 'out',
  outputs: { rule: 'no_retrieval_hit' },
  fallback: true,
};
const dense: RecognitionRecord = {
  recognizer_id: 'retrieval-c2',
  revision: 'dense',
  task: 'retrieval',
  label: 'policy',
  outputs: { method: 'dense', top: [{ rank: 1, material_id: 'policy', quote: 'cap 500' }] },
};

describe('profile card', () => {
  it('draws the threshold point only from the call’s own score and threshold', () => {
    const html = cardHtml(scope, 'zh');
    expect(html).toContain('class="rc-axis"');
    expect(html).toContain('1.09');
    expect(html).toContain('1.32');
    expect(html).toContain('在范围内');
    expect(cardHtml(ruleScope, 'zh')).not.toContain('class="rc-axis"');
  });

  it('labels the run mode from the record, and the replay from the practice', () => {
    expect(runMode(scope)).toBe('real');
    expect(runMode(ruleScope)).toBe('fallback');
    expect(cardHtml(scope, 'en')).toContain('Real inference');
    const rule = cardHtml(ruleScope, 'en');
    expect(rule).toContain('Rule fallback');
    expect(rule).toContain('not this call');
    expect(cardHtml(scope, 'en', { replay: true })).toContain('Record replay');
    expect(cardHtml(scope, 'en')).not.toContain('Record replay');
  });

  it('says when the number rule, not the vector distance, caught a drift', () => {
    const html = cardHtml(drift, 'zh');
    expect(html).toContain('<s>500</s>');
    expect(html).toContain('<b>400</b>');
    expect(html).toContain('数字校验规则');
  });

  it('names the retrieval actually used and points to the system profile entry', () => {
    const html = cardHtml(dense, 'en', { materialName: () => 'Travel policy' });
    expect(html).toContain('e5 dense');
    expect(html).toContain('Travel policy');
    expect(html).toContain('RRF fusion is used by the relation chain');
    expect(html).toContain(`href="#/lab/${TASK_ROW.retrieval}"`);
  });

  it('escapes what comes from records', () => {
    expect(cardHtml({ ...scope, recognizer_id: '<img>' }, 'zh')).not.toContain('<img>');
  });

  it('chips open their own card, hidden until pressed', () => {
    const html = cardsHtml([scope, drift], 'zh', { context: 'test', lens: true, cards: {} });
    const ids = [...html.matchAll(/data-rc-card="(rc-card-\d+)"/g)].map((m) => m[1]);
    expect(ids).toHaveLength(2);
    for (const id of ids) expect(html).toContain(`id="${id}" hidden`);
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain('马氏距离单类');
  });
});

describe('actual method labels', () => {
 it.each(['zh','en'] as const)('separates dense, RRF and BM25 fallback in %s', language => {
  for (const method of ['dense','rrf','bm25']) {
   const record = {...dense, fallback: method === 'bm25', outputs: {method}};
   const signal = lensSignal(record, language);
   expect(signal.method.toLowerCase()).toContain(method === 'dense' ? 'e5' : method);
   if(method === 'bm25') {expect(signal.method).not.toContain('RRF');expect(signal.category).not.toMatch(/混合|Hybrid/);}
  }
 });
 it('does not call deterministic decisions neural inference', () => {
  expect(cardHtml({...scope,task:'decision',fallback:false},'en')).toContain('Rule calculation');
  expect(cardHtml({...scope,task:'decision',fallback:false},'en')).not.toContain('Real inference');
 });
 it('labels fallback scope and intent methods as the rules actually run', () => {
  expect(lensSignal(ruleScope,'en').method).not.toContain('Mahalanobis');
  expect(lensSignal({...ruleScope,task:'intent',outputs:{rule:'keywords'}},'en').method).toContain('Keyword');
 });
});

it('shows the referenced baseline, versions and source quotes in the drift comparison', () => {
 const first={id:'a',question:'Cap?',answer:'500',policyVersion:2,indexVersion:1,configVersion:1,recognition:[{...dense,outputs:{method:'bm25',top:[{quote:'Original cap 500'}]}}]};
 const middle={...first,id:'b',answer:'400',indexVersion:2};
 const last={...middle,id:'c',recognition:[{...drift,outputs:{...drift.outputs,previous_test_id:'a'}}]};
 const html=cardHtml(last.recognition[0],'en',{comparison:{current:last,tests:[first,middle,last]}});
 expect(html).toContain('Recognition baseline · Run  1');
 expect(html).toContain('This answer · Run  3');
 expect(html).toContain('Original cap 500');expect(html).toContain('<b>v1</b>');expect(html).toContain('<b>v2</b>');
 const missing=cardHtml(last.recognition[0],'en',{comparison:{current:last,tests:[middle,last]}});
 expect(missing).toContain('Baseline not loaded');expect(missing).not.toContain('Original cap 500');
});
it('puts delivery-record provenance on the closed summary and keeps current recomputation separate',()=>{
 expect(cardsHtml([scope],'en',{context:'feedback',lens:true,cards:{}}).split('rc-card-slot')[0]).toContain('Record at delivery');
 expect(cardHtml(scope,'en',{source:'current'})).toContain('Recomputed locally now');
});

it('does not mistake a saved support-check record for proof that a relation model ran', () => {
 const record={...scope,task:'relation',outputs:{mode:'support_check',quotes:2,quotes_grounded:1,delegated_to_llm:true},label:'unverified'};
 const html=cardHtml(record,'en');
 expect(html).toContain('1 / 2 located');expect(html).toContain('Support remains unverified');expect(html).toContain('Delegated to the reviewer this time');expect(html).not.toContain('Real inference');
 expect(lensSignal({...record,fallback:true},'en').method).toContain('Citation-location rules');
});
it('counts per-sentence retrieval groups as sentences rather than passages', () => {
 const html=cardHtml({...dense,outputs:{per_sentence_top:[{index:0,top:[]},{index:1,top:[]}],k:5}},'en');
 expect(html).toContain('candidates saved for 2 sentences');expect(html).not.toContain('Top 2 passages');expect(html).toContain('Actual method not recorded');
});
