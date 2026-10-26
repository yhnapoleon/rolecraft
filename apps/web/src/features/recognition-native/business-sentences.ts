import type { PreviewRecognition } from './chain';
import type { Language } from '../results-native/localization';
import { checkPresentation } from './check-presentation';
import { checkStatusHtml, evidenceCheckHtml } from './evidence-check';
import { escapeCheck as esc } from './record-inspector';
import { lensOn } from './lens';
import { actualMethod } from './actual-method';
export { businessSentenceState } from './check-presentation';
/** Each group is one response/feedback; indices are only deduplicated within that identity. */
export function businessSentencesHtml(
  preview: PreviewRecognition,
  language: Language,
  identity = '',
) {
  const t = (zh: string, en: string) => (language === 'zh' ? zh : en);
  const units = [...new Map((preview.units ?? []).map((u) => [u.index, u])).values()];
  const method = preview.recognizer && typeof preview.fallback === 'boolean' ? actualMethod({task:'relation',recognizer_id:preview.recognizer.split('@')[0],revision:preview.recognizer.split('@')[1] ?? '',fallback:preview.fallback},language).method : t('实际方法未记录','Actual method not recorded');
  return `<rc-evidence-list class="rc-business-reading" data-identity="${esc(identity || JSON.stringify(preview.units?.map((u) => [u.index, u.quote, u.decision, u.evidence])))}" aria-label="${t('依据核对', 'Evidence check')}"><header><p class="ec-caption">${preview.origin === 'delivery' ? t('交付时记录', 'Recorded at submission') : t('本次核对', 'This check')}</p><h3>${t('这一版的依据核对', 'Evidence behind this version')}</h3><p>${t('把说法和依据放在一起，再决定哪些需要修改。', 'Compare each claim with its source, then decide what to revise.')}</p><p class="ec-caption">${t(`当前显示 ${units.length} 句`, `Showing ${units.length} claims`)}</p>${lensOn()?`<p class="ec-caption">${esc(method)}</p>`:''}</header><ol>${units
    .map((u) => {
      const p = checkPresentation(u, preview, language);
      return `<li data-sentence-state="${p.state}"><details class="ec-sentence" data-index="${u.index}"><summary><span class="ec-line"><span class="ec-index">${String(u.index + 1).padStart(2, '0')}</span><span class="rc-business-quote">${esc(u.quote.replace(/^(business|stakeholders|need|boundary|solution|assurance|decision)\n+/, ''))}</span>${checkStatusHtml(u, preview, language)}</span><span class="ec-hint">${p.hint}</span><span class="ec-expand">${t('展开原句与依据', 'Compare claim and source')} →</span></summary>${evidenceCheckHtml(u, preview, language)}</details></li>`;
    })
    .join(
      '',
    )}</ol><p class="ec-caption">${t('本次逐句核对供修改时参考，不改变正式评分。', 'Use this check to guide your revision. It does not change the formal assessment.')}</p></rc-evidence-list>`;
}
export function renderBusinessSentences(
  doc: Document,
  preview: PreviewRecognition,
  language: Language,
  identity = '',
) {
  const node = doc.createElement('div');
  node.innerHTML = businessSentencesHtml(preview, language, identity);
  return node;
}
const opened = new Map<string, string>();
if (typeof customElements !== 'undefined' && !customElements.get('rc-evidence-list'))
  customElements.define(
    'rc-evidence-list',
    class extends HTMLElement {
      connectedCallback() {
        queueMicrotask(() => {
          const rows = [...this.querySelectorAll<HTMLDetailsElement>('.ec-sentence')];
          const key = this.dataset.identity || rows.map((r) => r.textContent).join('');
          const saved = opened.get(key);
          for (const row of rows) {
            row.open = row.dataset.index === saved;
            row.addEventListener('toggle', () => {
              if (!row.open) {
                if (!rows.some(r=>r.open)) {opened.delete(key);this.dataset.expanded='false';}
                return;
              }
              opened.set(key, row.dataset.index ?? '');
              for (const other of rows) if (other !== row) other.open = false;
              this.dataset.expanded = 'true';
            });
          }
          this.dataset.expanded = String(rows.some((r) => r.open));
        });
      }
    },
  );
