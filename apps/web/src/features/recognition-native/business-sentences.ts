import type { PreviewRecognition, ChainUnit } from './chain';
import type { Language } from '../results-native/localization';
import { escapeMoment as esc, signatureHtml } from './signature';
import type { RecognitionRecord } from './badge';

export function businessSentenceState(unit: Pick<ChainUnit, 'label' | 'decision'>) {
  if (unit.decision === 'defer') return 'deferred';
  return ['supported', 'contradicted', 'insufficient'].includes(unit.label) ? unit.label : 'unknown';
}
/** All phrases and evidence are the server's exact response, including incorrect matches. */
export function businessSentencesHtml(preview: PreviewRecognition, language: Language, identity = '') {
  const t = (zh: string, en: string) => language === 'zh' ? zh : en;
  const names: Record<string, string> = { supported: t('有依据', 'Supported'), contradicted: t('矛盾', 'Contradicted'), insufficient: t('依据不足', 'Insufficient evidence'), deferred: t('暂缓判定', 'Deferred judgement'), unknown: t('未返回判定', 'No judgement returned') };
  const [id, revision] = (preview.recognizer ?? '').split('@');
  const record: RecognitionRecord = { task: 'relation', recognizer_id: id, revision: revision || '', ...(typeof preview.fallback === 'boolean' ? { fallback: preview.fallback } : {}), outputs: { units: preview.units ?? [] } };
  const signature = id && typeof preview.fallback === 'boolean'
    ? signatureHtml(record, language, { source: 'current' }, identity)
    : `<p class="rc-moment-note">${t('实际方法未记录', 'Actual method not recorded')}</p>`;
  return `<section class="rc-business-reading" aria-label="${t('逐句核对依据', 'Sentence evidence check')}"><h3>${t('这一版的依据核对', 'Evidence check for this version')}</h3>${signature}<ol>${(preview.units ?? []).map((unit) => {
    const state = businessSentenceState(unit);
    const reason = state === 'deferred' ? `<p class="rc-moment-note">${t('自动判定的预期代价较高，暂缓判定，留待人工核验。', 'The expected cost of an automatic judgement is high; deferred for human checking.')}</p>` : '';
    const source = unit.source;
    const evidence = unit.evidence ? `<blockquote>${esc(unit.evidence)}</blockquote>` : `<p class="rc-moment-note">${t('这次没有返回可展示的原文。', 'No source passage was returned for this sentence.')}</p>`;
    const sourceKind: Record<string, string> = { material: t('资料', 'Material'), test: t('测试记录', 'Test record'), product: t('作品', 'Work'), role_reply: t('同事回复', 'Colleague reply') };
    const location = [source?.title || (source ? sourceKind[source.kind ?? ''] || t('依据记录', 'Evidence record') : ''), typeof source?.version === 'number' ? `v${source.version}` : ''].filter(Boolean).join(' · ');
    return `<li data-sentence-state="${state}"><p class="rc-business-quote">${esc(unit.quote)}</p><span class="rc-business-label">${names[state]}</span>${reason}<details ${state === 'contradicted' ? 'open' : ''}><summary>${t('查看本次依据', 'View this check’s evidence')}${location ? ` · ${esc(location)}` : ''}</summary>${evidence}</details></li>`;
  }).join('')}</ol></section>`;
}
export function renderBusinessSentences(doc: Document, preview: PreviewRecognition, language: Language) {
  const node = doc.createElement('div');
  node.innerHTML = businessSentencesHtml(preview, language);
  return node;
}
