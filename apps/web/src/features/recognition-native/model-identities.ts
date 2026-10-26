/** Saved recognizer identities, not a claim about the currently installed weights. */
import type { SessionRecognition } from './client';
import type { Language } from '../results-native/localization';
import { escapeCheck } from './record-inspector';

export function modelIdentitiesHtml(data: SessionRecognition | null, language: Language) {
  const t = (zh: string, en: string) => language === 'zh' ? zh : en;
  const title = `<h4>${t('本局已记录的识别器身份', 'Recognizer identities recorded in this practice')}</h4>`;
  if (!data) return `${title}<p>${t('暂时读不到身份记录，请关闭后重试。', 'Identity records could not be read. Close this panel and try again.')}</p>`;
  if (!data.recognizers.length) return `${title}<p>${t('本局尚无识别器身份记录。', 'No recognizer identities have been recorded in this practice.')}</p>`;
  return `${title}<p>${t('这些版本来自本局保存的识别记录，不代表当前部署版本；同一识别器的不同版本分别保留。', 'These versions come from saved recognition records, not the current deployment. Different versions of one recognizer are kept separately.')}</p><dl class="kv ri-identities">${data.recognizers.map(row => `<div><dt><code>${escapeCheck(row.id)}</code></dt><dd><code>${escapeCheck(row.revision)}</code><br>${row.fallback ? t('规则回退', 'Rule fallback') : t('非回退记录', 'Non-fallback record')}</dd></div>`).join('')}</dl>`;
}

export async function loadModelIdentities(target: HTMLElement, read: () => Promise<SessionRecognition>, language: Language) {
  target.textContent = language === 'zh' ? '正在读取识别器身份…' : 'Reading recognizer identities…';
  let data: SessionRecognition | null = null;
  try { data = await read(); } catch { /* Keep an unreadable record explicit. */ }
  if (target.isConnected) target.innerHTML = modelIdentitiesHtml(data, language);
}
