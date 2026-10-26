import { expect, it } from 'vitest';
import { loadModelIdentities, modelIdentitiesHtml } from './model-identities';
import type { SessionRecognition } from './client';
const saved: SessionRecognition = { session_id: 's', counts: {}, records: [], recognizers: [
  { id: 'intent-tfidf-lr-v1', revision: 'rev-one', fallback: false },
  { id: 'intent-tfidf-lr-v1', revision: 'rule-fallback', fallback: true },
] };
it.each(['zh','en'] as const)('shows exact saved identities and versions without claiming deployment identity in %s', language => {
  const html = modelIdentitiesHtml(saved, language);
  expect(html).toContain('rev-one');
  expect(html).toContain('rule-fallback');
  expect((html.match(/intent-tfidf-lr-v1/g) ?? []).length).toBe(2);
  expect(html).toContain(language === 'zh' ? '不代表当前部署版本' : 'not the current deployment');
  expect(html).toContain(language === 'zh' ? '规则回退' : 'Rule fallback');
  expect(modelIdentitiesHtml(null, language)).toContain(language === 'zh' ? '暂时读不到' : 'could not be read');
  expect(modelIdentitiesHtml({...saved, recognizers: []}, language)).toContain(language === 'zh' ? '尚无' : 'No recognizer identities');
});
it('escapes returned identity text', () => {
  expect(modelIdentitiesHtml({...saved, recognizers:[{id:'<script>',revision:'<img>',fallback:false}]}, 'en')).not.toMatch(/<script>|<img>/);
});
it('does not paint a late response into a closed panel', async () => {
  const target = { isConnected: false, textContent: '', innerHTML: 'closed' };
  await loadModelIdentities(target as unknown as HTMLElement, async () => saved, 'en');
  expect(target.innerHTML).toBe('closed');
});
