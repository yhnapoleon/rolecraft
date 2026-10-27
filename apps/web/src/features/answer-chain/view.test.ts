import { beforeEach, describe, expect, it } from 'vitest';
import type { RecognitionRecord } from '../recognition-native/badge';
import { registeredAction } from '../../shell/registry';
import { answerChain, type ChainInput } from './model';
import { answerChainHtml, resetChainMemory } from './view';

const records: RecognitionRecord[] = [
  { recognizer_id: 's', revision: 'fit', task: 'scope', label: 'in', score: 1, threshold: 2 },
  {
    recognizer_id: 'r',
    revision: 'rrf',
    task: 'retrieval',
    outputs: { method: 'rrf', passing: 3, min_score: 0.35 },
  },
];
const input = (over: Partial<ChainInput> = {}): ChainInput => ({
  status: 'answered',
  errorCode: null,
  mode: 'extractive',
  stale: true,
  citations: [{ id: 'policy', version: 1, title: 'Travel <lodging>' }],
  sourceVersions: { policy: 2 },
  indexedVersions: { policy: 1 },
  config: {
    fallback: 'human',
    update_strategy: 'daily',
    freshness_guard: 'none',
    retrieval_limit: 3,
  },
  recognition: records,
  ...over,
});
const render = (over: Partial<ChainInput> = {}, options = {}) =>
  answerChainHtml(
    answerChain(input(over), 'en'),
    'run-1',
    { language: 'en', handover: true, inspect: true, ...options },
    ['scope', 'retrieval'],
  );
/** Buttons a keyboard reaches while the steps are folded: everything outside the hidden rows. */
const tabbable = (html: string) =>
  (html.replace(/<ul class="ac-rows"[^>]*hidden>.*?<\/ul>/s, '').match(/<button\b/g) ?? []).length;

beforeEach(() => resetChainMemory());

describe('answer chain markup', () => {
  it('is one labelled ordered list of five readable steps', () => {
    const html = render();
    expect(html).toMatch(/<ol class="ac-path" aria-label="Path this question took">/);
    expect(html.match(/<li class="ac-step"/g)).toHaveLength(5);
    expect(html).toContain('<span class="sr-only">Up to date?: source out of date</span>');
    expect(html).toContain('<span class="sr-only">Result: answered, stopped here</span>');
    // Names and identities are visual only; the sentence carries the meaning.
    expect(html).toContain('<span class="ac-name" aria-hidden="true">In scope?</span>');
    expect(html).toContain('<span class="ac-who" aria-hidden="true">Daniel tunes</span>');
    expect(html).toContain('data-tone="warn"');
    expect(html).toContain('Travel &lt;lodging&gt;');
  });

  it('lets Tab stop only at "Show each step" and "Hand to Daniel"', () => {
    const html = render();
    expect(tabbable(html)).toBe(2);
    expect(html).toContain('data-action="engineer-handover"');
    expect(html).toMatch(
      /data-action="chain-steps" aria-expanded="false" aria-controls="ac-rows-run-1"/,
    );
    expect(html).not.toMatch(/<li class="ac-step"[^>]*tabindex/);
  });

  it('shows "Hand to Daniel" only where the chain and the practice allow it', () => {
    expect(render({ stale: false, sourceVersions: { policy: 1 } })).not.toContain(
      'engineer-handover',
    );
    expect(render({}, { handover: false })).not.toContain('engineer-handover');
    expect(tabbable(render({ stale: false, sourceVersions: { policy: 1 } }))).toBe(1);
  });

  it('links the expanded steps to the same run’s records by their saved order', () => {
    const html = render();
    expect(html).toContain('data-action="chain-inspect" data-index="0"');
    expect(html).toContain('data-action="chain-inspect" data-index="1"');
    expect(render({}, { inspect: false })).not.toContain('chain-inspect');
  });

  it('puts the reason on its own line and the keys under it, the toggle with a turning chevron', () => {
    const html = render();
    expect(html.indexOf('class="ac-reason"')).toBeLessThan(html.indexOf('class="ac-keys"'));
    expect(html).not.toContain('ac-foot');
    expect(html).toMatch(
      /data-action="chain-steps"[^>]*><svg class="ac-chev"[^>]*>.*?<\/svg><span class="ac-key-label">Show each step<\/span>/,
    );
  });

  it('marks a flagged outdated source as handled', () => {
    expect(render({ status: 'answered_with_warning' })).toContain('data-handled=""');
    expect(render()).not.toContain('data-handled');
  });

  it('keeps the compact form for the evaluation desk', () => {
    const html = answerChainHtml(answerChain(input(), 'en'), 'run-1', {
      language: 'en',
      handover: true,
      compact: true,
    });
    expect(html).not.toContain('ac-who');
    expect(html).not.toContain('chain-steps');
    expect(html).not.toContain('ac-rows');
    expect(html).toContain('engineer-handover');
    expect(html).toContain('class="ac-reason"');
  });

  it('lets a fresh result arrive once', () => {
    expect(render({}, { fresh: true })).toContain('data-arriving');
    expect(render({}, { fresh: true })).not.toContain('data-arriving');
  });

  it('registers the step toggle and the record link with the shell', () => {
    expect(registeredAction('chain-steps')).toBeTypeOf('function');
    expect(registeredAction('chain-inspect')).toBeTypeOf('function');
  });
});
