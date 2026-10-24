import { describe, expect, it } from 'vitest';
import type { RecognitionRecord } from './badge';
import { LENS_COPY } from './lens-copy';
import { splitRecognitionPrefix } from './prefix';
import { categoryOf, lensSignal, renderExplanationTag, renderSignals, signalsHtml } from './signals';
import { asFake, fakeDocument } from '../results-native/fake-dom';

const scopeOut: RecognitionRecord = {
  recognizer_id: 'scope-mahalanobis-v1',
  revision: 'f05ba88712e6',
  task: 'scope',
  label: 'out',
  score: 1.14,
  threshold: 1.35,
  fallback: false,
};
const retrieval: RecognitionRecord = {
  recognizer_id: 'retrieval-c2',
  revision: 'dense',
  task: 'retrieval',
  label: 'faq',
  score: 0.84,
  outputs: { method: 'rrf', top: [{ material_id: 'faq', quote: '账号密码在自助页重置。' }] },
};
const drift: RecognitionRecord = {
  recognizer_id: 'drift-cosine-v1',
  revision: 'unhashed',
  task: 'drift',
  label: 'anomaly',
  score: 0.0242,
  threshold: 0.1364,
  outputs: { numeric_change: true, numbers_before: ['500'], numbers_after: ['400'] },
};
const intent: RecognitionRecord = {
  recognizer_id: 'intent-tfidf-lr-v1',
  revision: 'a9f95d7c3de5',
  task: 'intent',
  label: 'ask_resource',
  score: 0.84,
  outputs: {},
};
const reply: RecognitionRecord = {
  recognizer_id: 'reply-check-v1',
  revision: 'd12a5d8eb826',
  task: 'reply_check',
  label: 'partly_grounded',
  outputs: { grounded: 3, ungrounded: 3, leaks: 0 },
};
const behaviorFallback: RecognitionRecord = {
  recognizer_id: 'behavior-v1',
  revision: 'rule-fallback',
  task: 'behavior',
  label: null,
  fallback: true,
  outputs: {},
};
/** Strings the learner's default view must never carry. */
const INTERNAL = /\d\.\d|ask_|rrf|top-1|rule-fallback|recognizer|scope-|behavior-v1|faq|马氏|阈/;

describe('recognition signals', () => {
  it('keeps the two languages on the same keys', () => {
    expect(Object.keys(LENS_COPY.en).sort()).toEqual(Object.keys(LENS_COPY.zh).sort());
  });

  it('stays quiet on test records unless the answer’s numbers changed', () => {
    expect(signalsHtml([scopeOut, retrieval], 'zh', { context: 'test', lens: false })).toBe('');
    const html = signalsHtml([scopeOut, retrieval, drift], 'zh', { context: 'test', lens: false });
    expect(html).toContain('和上一次相比，回答里的数字从 500 变成 400');
    expect(html).not.toMatch(INTERNAL);
    expect(signalsHtml([drift], 'en', { context: 'test', lens: false })).toContain(
      'Compared with last time, the numbers in the answer changed from 500 to 400',
    );
  });

  it('shows nothing under a colleague reply or in feedback with the lens closed', () => {
    expect(signalsHtml([intent, reply], 'zh', { context: 'reply', lens: false })).toBe('');
    expect(signalsHtml([behaviorFallback], 'zh', { context: 'feedback', lens: false })).toBe('');
    const doc = fakeDocument();
    expect(renderSignals(doc, [intent, reply], 'zh', { context: 'reply', lens: false })).toBeNull();
  });

  it('opens each signal in plain words, a course category and a short bar with the lens on', () => {
    const html = signalsHtml([intent, reply, scopeOut], 'zh', { context: 'reply', lens: true });
    expect(html).toContain('你问的是：资源');
    expect(html).toContain('监督 · 经典机器学习');
    expect(html).toContain('与材料一致 3/6 句');
    expect(html).toContain('不在资料范围内，转人工');
    expect(html).toContain('无监督');
    expect(html).toContain('class="rc-meter"');
    // Bars carry the confidence, never a decimal in the text.
    expect(html.replace(/style="[^"]*"/g, '').replace(/title="[^"]*"/g, '')).not.toMatch(/\d\.\d/);
  });

  it('names materials by title, not their identifier', () => {
    const html = signalsHtml([retrieval], 'zh', {
      context: 'test',
      lens: true,
      materialName: (id) => (id === 'faq' ? '常见问题' : id),
    });
    expect(html).toContain('最相关：常见问题');
    expect(html).toContain('混合');
  });

  it('marks the rule fallback in words with a grey outline', () => {
    const html = signalsHtml([behaviorFallback], 'en', { context: 'feedback', lens: true });
    expect(html).toContain('data-fallback');
    expect(html).toContain('Rule fallback');
    expect(html).not.toContain('rule-fallback');
  });

  it('labels every recognizer with its course category', () => {
    expect(categoryOf(intent, 'zh')).toBe('监督 · 经典机器学习');
    expect(categoryOf({ ...intent, task: 'behavior' }, 'zh')).toBe('机器学习 · 无监督 · 智能感知');
    expect(categoryOf({ ...intent, task: 'arbiter' }, 'en')).toBe('Statistical decision · Hybrid');
    expect(categoryOf({ ...intent, task: 'relation', recognizer_id: 'xlm-r-pair-v1' }, 'zh')).toBe('监督 · 深度学习');
    expect(categoryOf({ ...intent, task: 'relation', recognizer_id: 'relation-stack-v1' }, 'zh')).toBe('集成 · 混合');
    expect(categoryOf({ ...intent, task: 'retrieval' }, 'zh')).toBe('混合');
  });

  it('words the arbiter by outcome in the lens', () => {
    const undecided = lensSignal(
      {
        recognizer_id: 'arbiter-v1',
        revision: 'r',
        task: 'arbiter',
        label: 'judge_undecided',
        outputs: { agreement: false, judge_label: 'INSUFFICIENT', recognizer_label: 'PARTIAL', final: 'INSUFFICIENT' },
      },
      'zh',
    );
    expect(undecided.text).toBe('评审未给出可比标签，保留评审结论');
  });

  it('escapes recorded text', () => {
    const html = signalsHtml([{ ...intent, label: '<b>x</b>' }], 'zh', { context: 'reply', lens: true });
    expect(html).not.toContain('<b>');
  });

  it('builds the same chips as DOM', () => {
    const doc = fakeDocument();
    const row = asFake(renderSignals(doc, [reply], 'zh', { context: 'reply', lens: true }) as unknown as HTMLElement);
    expect(row.textContent).toContain('与材料一致 3/6 句');
    expect(row.textContent).toContain('监督');
  });

  it('turns the reviewer’s prefix into a quiet tag, with a disagreement’s reason behind it', () => {
    const doc = fakeDocument();
    const agree = asFake(renderExplanationTag(doc, splitRecognitionPrefix('[识别一致] 正文'), 'zh'));
    expect(agree.textContent).toBe('识别一致');
    const disagree = asFake(
      renderExplanationTag(doc, splitRecognitionPrefix('[disagrees with recognition: too strict] Body'), 'en'),
    );
    expect(disagree.tagName).toBe('details');
    expect(disagree.textContent).toContain('Disagrees with recognition');
    expect(disagree.textContent).toContain('Reason: too strict');
    expect(renderExplanationTag(doc, splitRecognitionPrefix('普通说明'), 'zh')).toBeNull();
  });
});
