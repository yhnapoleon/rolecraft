import { describe, expect, it } from 'vitest';
import { retrievalMethod } from './actual-method';
import { judgmentChainHtml } from './judgment-chain';
import type { ChainUnit } from './chain';

const unit = (retrieval?: unknown): ChainUnit =>
  ({
    index: 0,
    quote: 'Claim',
    label: 'supported',
    confidence: 0.9,
    decision: 'decide',
    ...(retrieval === undefined ? {} : { retrieval }),
  }) as ChainUnit;

describe('retrieval method actually run', () => {
  it.each([
    [
      { method: 'rrf', fallback: false },
      'fused',
      '语义检索 + 关键词检索融合',
      'Semantic + keyword retrieval (fused)',
    ],
    [{ method: 'dense', fallback: false }, 'semantic', '语义检索', 'Semantic retrieval'],
    [
      { method: 'bm25', fallback: true },
      'keyword_fallback',
      '关键词检索',
      'Keyword retrieval',
    ],
    [{ method: null, fallback: false }, 'none', '没有候选段落', 'No candidate passages'],
    [
      undefined,
      'unrecorded',
      '这条记录没有记下检索方法',
      'This record does not say which retrieval method ran',
    ],
  ])('reads %j as %s in both languages', (field, kind, zh, en) => {
    expect(retrievalMethod(unit(field), null, 'zh')).toMatchObject({ kind, label: zh });
    expect(retrievalMethod(unit(field), null, 'en')).toMatchObject({ kind, label: en });
  });

  it('says why a keyword fallback ran as a separate aside, and only then', () => {
    const fallback = unit({ method: 'bm25', fallback: true });
    expect(retrievalMethod(fallback, null, 'zh').note).toBe('（语义模型未加载）');
    expect(retrievalMethod(fallback, null, 'en').note).toBe(' (semantic model not loaded)');
    expect(retrievalMethod(unit({ method: 'bm25', fallback: false }), null, 'en').note).toBeUndefined();
    const html = judgmentChainHtml(fallback, {}, 'zh');
    expect(html).toContain(
      '<span class="jc-retrieval" data-kind="keyword_fallback">关键词检索<span class="jc-retrieval-note">（语义模型未加载）</span></span>',
    );
  });

  it('prefers the sentence, then the pass-wide preview field, then an older record field', () => {
    const preview = { retrieval: { method: 'bm25', fallback: true } };
    expect(retrievalMethod(unit({ method: 'rrf', fallback: false }), preview, 'en').kind).toBe(
      'fused',
    );
    expect(retrievalMethod(unit(), preview, 'en').kind).toBe('keyword_fallback');
    expect(retrievalMethod({ retrieval_method: 'dense' }, null, 'en').kind).toBe('semantic');
    // BM25 chosen on purpose is not reported as a fallback; unknown names are not guessed.
    expect(retrievalMethod(unit({ method: 'bm25', fallback: false }), null, 'en').label).toBe(
      'Keyword retrieval',
    );
    expect(retrievalMethod(unit({ method: 'tfidf' }), null, 'en').kind).toBe('unrecorded');
    expect(retrievalMethod(unit({}), { retrieval: null }, 'en').kind).toBe('unrecorded');
  });

  it('shows the method on the technical record of the check, without expanding it', () => {
    const html = judgmentChainHtml(unit({ method: 'rrf', fallback: false }), {}, 'zh');
    expect(html).toMatch(
      /<summary><span class="jc-hits-count">取回候选原文 0 段<\/span><span class="jc-retrieval" data-kind="fused">语义检索 \+ 关键词检索融合<\/span><svg class="jc-chev" aria-hidden="true" width="12" height="12"[^>]*><path d="m6 9 6 6 6-6"\/><\/svg><\/summary>/,
    );
    const en = judgmentChainHtml(unit({ method: 'dense' }), {}, 'en');
    expect(en).toContain('<span class="jc-hits-count">0 retrieved passages</span>');
    expect(en.match(/<summary>[\s\S]*?<\/summary>/)?.[0]).not.toContain('·');
    const none = judgmentChainHtml(
      unit(),
      { retrieval: { method: null, fallback: false } } as never,
      'en',
    );
    expect(none).toContain('No candidate passages');
    expect(none).not.toMatch(/[一-鿿]/);
  });
});
