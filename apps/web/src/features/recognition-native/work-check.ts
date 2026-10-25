import type { PreviewRecognition } from './chain';
import type { Language } from '../results-native/localization';
import type { SentenceResult } from '../feedback-native/presubmit';
import { businessSentencesHtml } from './business-sentences';
import { escapeMoment as esc } from './signature';

export type WorkCheckResult = { kind: 'running' | 'ready' | 'disabled' | 'empty' | 'failed' | 'stale'; basis: string; decisionLabel?: string; preview?: PreviewRecognition };
/** Memory-only preview. Starting, invalidating or closing supersedes in-flight responses. */
export function createWorkChecks() {
  const values = new Map<string, WorkCheckResult>();
  const epochs = new Map<string, number>();
  const invalidate = (key: string) => {
    epochs.set(key, (epochs.get(key) ?? 0) + 1);
    const old = values.get(key);
    if (old) values.set(key, { ...old, kind: 'stale' });
  };
  return {
    get: (key: string) => values.get(key),
    invalidate,
    async run(key: string, basis: string, load: () => Promise<SentenceResult>, stillCurrent: () => boolean, decisionLabel?: string) {
      const epoch = (epochs.get(key) ?? 0) + 1;
      epochs.set(key, epoch);
      values.set(key, { kind: 'running', basis, ...(decisionLabel ? { decisionLabel } : {}) });
      let result: WorkCheckResult;
      try {
        const found = await load();
        result = { basis, kind: !found.enabled ? 'disabled' : found.recognition?.units?.length ? 'ready' : 'empty', ...(found.recognition ? { preview: found.recognition } : {}) };
      } catch { result = { kind: 'failed', basis }; }
      if (decisionLabel) result.decisionLabel = decisionLabel;
      if (epochs.get(key) === epoch) values.set(key, stillCurrent() ? result : { kind: 'stale', basis });
      return values.get(key);
    },
  };
}
export function workCheckHtml(value: WorkCheckResult | undefined, language: Language, currentBasis: string, dirty = false) {
  const t = (zh: string, en: string) => language === 'zh' ? zh : en;
  if (!value) return '';
  const state = dirty || currentBasis !== value.basis ? 'stale' : value.kind;
  const notices = { running: t('正在核对这份已保存版本…', 'Checking this saved version…'), disabled: t('未启用识别，未生成逐句结论。', 'Recognition is not enabled; no sentence judgements were generated.'), empty: t('本次没有返回逐句结论，不能视为通过。', 'No sentence judgements were returned; this is not a pass.'), failed: t('核对失败，请重试；作品和交付状态未改变。', 'The check failed. Try again; your work and submission status are unchanged.'), stale: t('核对已过期：文字、版本或工作记录有变化。保存后重新核对。', 'This check is out of date: text, version or work records changed. Save and check again.') };
  if (state === 'ready' && value.preview) return `<p class="rc-moment-note">${esc(value.decisionLabel ? t(`按「${value.decisionLabel}」核对`, `Checked for “${value.decisionLabel}”`) : '')}</p>${businessSentencesHtml(value.preview, language, value.basis)}`;
  return `<p class="rc-work-check-note ${state === 'stale' ? 'warn' : ''}" role="status" data-work-check-state="${state}">${esc(notices[state === 'ready' ? 'empty' : state])}</p>`;
}
