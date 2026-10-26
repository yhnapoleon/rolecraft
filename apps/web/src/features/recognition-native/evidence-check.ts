import type { ChainUnit, PreviewRecognition } from './chain';
import type { Language } from '../results-native/localization';
import { checkPresentation } from './check-presentation';
import { judgmentChainHtml } from './judgment-chain';
import { escapeCheck as esc, inspectorEntryHtml, methodsHtml } from './record-inspector';
import './evidence-check.css';
export function checkStatusHtml(unit: ChainUnit, preview: PreviewRecognition, language: Language) {
  const p = checkPresentation(unit, preview, language);
  return `<span class="ec-status" data-state="${p.state}"><span aria-hidden="true">${p.state === 'supported' ? '✓' : p.state === 'contradicted' ? '≠' : '◌'}</span>${p.status}</span>`;
}
/** Mark only exact numeric tokens present in the untouched source text. */
export function markNumber(text: string, number: string | undefined, kind: 'claim' | 'source') {
  if (!number) return esc(text);
  const pieces = text.split(/(\d+(?:\.\d+)?)/);
  return pieces
    .map((p) =>
      p === number ? `<mark class="ec-number ec-number--${kind}">${esc(p)}</mark>` : esc(p),
    )
    .join('');
}
export function evidenceCheckHtml(
  unit: ChainUnit,
  preview: PreviewRecognition,
  language: Language,
  canOpenMaterial = false,
) {
  const t = (zh: string, en: string) => (language === 'zh' ? zh : en);
  const p = checkPresentation(unit, preview, language);
  const quote = unit.quote.replace(
    /^(business|stakeholders|need|boundary|solution|assurance|decision)\n+/,
    '',
  );
  const location = [
    unit.source?.title,
    typeof unit.source?.version === 'number' ? `v${unit.source.version}` : '',
  ]
    .filter(Boolean)
    .join(' · ');
  const selected =
    unit.evidence ??
    unit.top?.find(
      (h) => typeof h.evidence_id === 'string' && unit.evidence_ids?.includes(h.evidence_id),
    )?.quote;
  const passage = typeof selected === 'string' ? selected : '';
  const candidates = (unit.top ?? []).filter((h) => typeof h.quote === 'string');
  const title =
    p.state === 'deferred'
      ? t('为什么留给你核验', 'Why this needs your review')
      : t('这句话的核对记录', 'The check behind this claim');
  return `<section class="evidence-check" data-state="${p.state}"><div class="ec-comparison"><div><p class="ec-caption">${t('你写的', 'Your claim')}</p><blockquote>${markNumber(quote, p.comparison?.value, 'claim')}</blockquote><p class="ec-caption">${t('本次核对的原句', 'Claim saved with this check')}</p></div><div><p class="ec-caption">${t('本次选中的原文', 'Passage selected for this check')}</p>${passage ? `<blockquote>${markNumber(passage, p.comparison?.limit, 'source')}</blockquote>` : `<p>${t(candidates.length ? '选中的原文未记录；可以查看候选原文。' : '这次没有返回可展示的原文。', candidates.length ? 'The selected passage was not saved. Retrieved candidates are available below.' : 'No source passage is available for this check.')}</p>`}${location ? `<p class="ec-caption">${t('记录附带的来源信息', 'Source information attached to the record')} · ${esc(location)}</p>` : ''}</div></div><dl class="ec-checks"><div><dt>${t('内容理解', 'Meaning check')}</dt><dd>${p.meaning}</dd></div><div><dt>${t('数字核对', 'Number check')}</dt><dd>${p.numberHint}</dd></div></dl><p class="ec-relation">${p.relation}</p><p class="ec-next">${t('可以先看这条依据适用于谁、什么时间，再决定这句怎么改。', 'Check who this source covers and when it applies before revising the claim.')}</p><div class="ec-actions"><a class="ec-source" href="#/investigate">${canOpenMaterial?t('打开资料 · 打开后请核对版本','Open source · check its version'):t('去资料里核对', 'Check the source documents')} →</a>${inspectorEntryHtml(title, judgmentChainHtml(unit, preview, language), methodsHtml(language), language)}</div>${candidates.length ? `<details class="ec-candidates"><summary>${t('查看其他候选原文', 'See other retrieved passages')}</summary><p class="ec-caption">${t('候选不一定是本次选中的依据。', 'Retrieved candidates are not necessarily the selected evidence.')}</p>${candidates.map((h) => `<blockquote>${esc(h.quote)}</blockquote>`).join('')}</details>` : ''}</section>`;
}
export function renderEvidenceCheck(
  doc: Document,
  unit: ChainUnit,
  preview: PreviewRecognition,
  language: Language,
  canOpenMaterial = false,
) {
  const host = doc.createElement('div');
  host.innerHTML = evidenceCheckHtml(unit, preview, language, canOpenMaterial);
  return host;
}
