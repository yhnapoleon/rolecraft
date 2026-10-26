import { expect, it } from 'vitest';
import { methodsHtml } from './record-inspector';
import { tr } from '../recognition-lab/copy';

it.each(['zh', 'en'] as const)('gives each task its own category-to-work table in %s, consistent with c1/c5/c11', language => {
  const relation = methodsHtml(language, 'relation');
  const behavior = methodsHtml(language, 'behavior');
  const intent = methodsHtml(language, 'intent');
  const categories = (html: string) => [...html.matchAll(/<th scope="row">(.*?)<\/th>/g)].map(m => m[1]);
  expect(categories(relation)).toEqual(language === 'zh' ? ['监督学习', '深度学习', '集成与混合'] : ['Supervised learning', 'Deep learning', 'Ensemble and hybrid methods']);
  expect(categories(behavior)).toEqual(language === 'zh' ? ['无监督学习', '机器学习 · 序列距离'] : ['Unsupervised learning', 'Machine learning · sequence distance']);
  expect(categories(intent)).toEqual(language === 'zh' ? ['监督学习', '经典机器学习'] : ['Supervised learning', 'Classical machine learning']);
  expect(tr(language, 'cat_c1')).toBe(language === 'zh' ? '监督 · 深度学习' : 'Supervised · deep learning');
  expect(tr(language, 'cat_chain')).toBe(language === 'zh' ? '集成 · 混合' : 'Ensemble · hybrid');
  expect(tr(language, 'cat_c5')).toBe(language === 'zh' ? '机器学习 · 无监督' : 'Machine learning · unsupervised');
  expect(tr(language, 'cat_c11')).toBe(language === 'zh' ? '监督 · 经典机器学习' : 'Supervised · classical ML');
  for (const [html, experiment, method] of [[relation, 'c1', 'XLM-R'], [behavior, 'c5', 'HMM'], [intent, 'c11', 'TF-IDF']]) {
    expect(html).toContain(`<a href="#/lab/${experiment}">`);
    expect(html).toContain('<table class="ri-method-table">');
    expect(html).toContain(method);
    expect(html).toContain('data-action="about" data-ri-about');
    expect(html).toContain('<a href="#/lab">');
  }
  expect(behavior).toContain('DTW');
  expect(intent).not.toMatch(/深度学习|集成|Deep learning|Ensemble/);
  expect(behavior).not.toMatch(/<th scope="row">监督|<th scope="row">Supervised/);
});
