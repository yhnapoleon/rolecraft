import type { RecognitionRecord } from './badge';
import type { Language } from '../results-native/localization';
import { comparisonFor, type TestRecord } from './test-comparison';
import { escapeMoment as esc, signatureHtml } from './signature';

type Citation = { id?: string; title?: string; version?: number; quote?: string };
export type MomentRun = Omit<TestRecord, 'citations'> & { citations?: Citation[]; stale?: boolean; fallback?: boolean };
/** The recognizer keeps the first 120 characters of a passage. A cut passage ends on a word, with "…". */
const QUOTE_LIMIT = 120;
export function passageText(quote: string) {
  const text = quote.trim();
  if ([...quote].length < QUOTE_LIMIT) return text;
  const space = text.lastIndexOf(' ');
  const cut = /[A-Za-z0-9]$/.test(text) && space > QUOTE_LIMIT / 2 ? text.slice(0, space) : text;
  return `${cut.replace(/[\s,;:，；：、]+$/, '')}…`;
}
export function retrievalHit(run: MomentRun) {
  const record = run.recognition?.find((r) => r.task === 'retrieval');
  const top = Array.isArray(record?.outputs?.top) ? record.outputs.top[0] : undefined;
  if (!record || !top || typeof top.quote !== 'string' || !top.quote.trim()) return null;
  const matches = (run.citations ?? []).filter((c) => c.id === top.material_id && typeof c.version === 'number');
  const versions = new Set(matches.map((c) => c.version));
  return { record, quote: top.quote, citation: versions.size === 1 ? matches[0] : undefined };
}
/** Stale metadata is not a drift inference. No historical result is overwritten. */
export function testAgeText(run: MomentRun, policyVersion: number, language: Language) {
  const t = (zh: string, en: string) => language === 'zh' ? zh : en;
  if (run.policyVersion < policyVersion) {
    const affected = run.citations?.some((citation) => citation.id === 'policy' && typeof citation.version === 'number' && citation.version < policyVersion);
    return affected
      ? t('引用了旧政策，待重测 · 版本核对', 'Cites the previous policy; rerun needed · version check')
      : t('早于政策变化；是否受影响尚未核实 · 版本核对', 'Predates the policy change; impact not established · version check');
  }
  if (run.stale || run.indexVersion < run.policyVersion) return t('本次索引落后于政策，待重测 · 版本核对', 'This run used an index behind the policy; rerun needed · version check');
  return '';
}
export function testMomentHtml(run: MomentRun, tests: MomentRun[], language: Language, materialName: (id: string) => string) {
  const t = (zh: string, en: string) => language === 'zh' ? zh : en;
  const records = (run.recognition ?? []).filter((r) => ['scope', 'retrieval', 'drift'].includes(r.task));
  const options = { source: 'saved' as const, materialName, comparison: { current: run, tests } };
  const hit = retrievalHit(run);
  const { previous, drift } = comparisonFor(run, tests);
  const numbers = (value: unknown) => Array.isArray(value) && value.every((x) => typeof x === 'string' || typeof x === 'number') ? value.join(' / ') : '';
  const before = numbers(drift?.outputs?.numbers_before), after = numbers(drift?.outputs?.numbers_after);
  const change = drift?.outputs?.numeric_change === true && before && after
    ? `<p class="rc-moment-change">${esc(t('回答中的数字', 'Numbers in the answer'))} <span>${esc(before)}</span><span aria-hidden="true"> → </span><span class="sr-only">${t('变为', 'changed to')}</span><strong>${esc(after)}</strong></p>` : '';
  const config = previous && previous.configVersion !== run.configVersion
    ? `<p class="rc-moment-note">${esc(t(`配置也从 v${previous.configVersion} 变为 v${run.configVersion}；这不是只改变索引的对照。`, `The configuration also changed from v${previous.configVersion} to v${run.configVersion}; this comparison is not index-only.`))}</p>` : '';
  // Retrieval runs before the scope and source checks stop a question; a passage found then was
  // not used for an answer, and reads so.
  const scope = run.recognition?.find((r) => r.task === 'scope');
  const unused = run.fallback === true || scope?.label === 'out';
  const hitTitle = unused
    ? scope?.label === 'out'
      ? t('最接近的原文（范围外，未用来作答）', 'Closest passage (out of scope, not used to answer)')
      : t('最接近的原文（未用来作答）', 'Closest passage (not used to answer)')
    : t('本次检索命中的原文', 'Passage retrieved for this run');
  const excerpt = hit ? `<div class="rc-moment-hit" data-retrieval-hit${unused ? ' data-unused=""' : ''}><p class="rc-moment-hit-title">${esc(hitTitle)}${hit.citation ? ` · ${esc(hit.citation.title || materialName(hit.citation.id ?? ''))} · v${hit.citation.version}` : ''}</p><blockquote>${esc(passageText(hit.quote))}</blockquote>${unused ? '' : hit.citation ? `<button type="button" class="btn small quiet" data-action="run-hit" data-id="${esc(run.id)}">${t('定位这句原文', 'Locate this passage')}</button><button type="button" class="btn small quiet" data-action="cite-hit" data-id="${esc(run.id)}">${t('作为依据', 'Use as evidence')}</button>` : `<p class="rc-moment-note">${t('该片段未关联可定位的引用版本；不能据此认定答案有依据。', 'This passage has no uniquely cited version to open; retrieval alone does not ground the answer.')}</p>`}</div>` : '';
  return `<section class="rc-test-moment" aria-label="${t('这次测试的依据与识别', 'Evidence and recognition for this test')}">${change}${config}${excerpt}${records.length ? records.map((r: RecognitionRecord) => signatureHtml(r, language, options, run.id)).join('') : `<p class="rc-moment-note">${t('本次没有可用的识别记录', 'No recognition record is available for this run')}</p>`}</section>`;
}
