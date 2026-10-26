import type { RecognitionRecord } from './badge';
import type { Language } from '../results-native/localization';
import { actualMethod } from './actual-method';
import { cardHtml, type CardOptions } from './profile-card';
import './moments.css';
import { layersIcon } from './record-inspector';

export const escapeMoment = (value: unknown) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c);
const words = (language: Language, zh: string, en: string) => language === 'zh' ? zh : en;
/** The signature describes this record's actual execution, never its model family alone. */
export function signatureText(record: RecognitionRecord, language: Language) {
  const t = (zh: string, en: string) => words(language, zh, en);
  const actual = actualMethod(record, language);
  const out = record.outputs ?? {};
  const rule = actual.mode === 'fallback' || actual.mode === 'rule';
  if (actual.mode === 'unknown') return t('实际方法未记录', 'Actual method not recorded');
  switch (record.task) {
    case 'scope': return `${rule ? t('规则判定', 'Rule check') : t('范围识别', 'Scope recognition')}：${record.label === 'out' ? t('超出资料范围', 'outside the material scope') : record.label === 'in' ? t('在资料范围内', 'within the material scope') : t('结果未说明', 'result not recorded')}`.replace('：', language === 'en' ? ': ' : '：');
    case 'retrieval': {
      const top = Array.isArray(out.top) ? out.top[0] : undefined;
      const rank = typeof top?.rank === 'number' && top.rank > 0 ? t(` · 第 ${top.rank} 位`, ` · rank ${top.rank}`) : '';
      const label = rule ? t('规则检索', 'Rule-based retrieval') : out.method === 'rrf' ? t('混合检索', 'Hybrid retrieval') : t('语义检索', 'Semantic retrieval');
      return label + (top ? t('命中', ' match') + rank : t(' · 未记录命中片段', ' · no matching passage recorded'));
    }
    case 'drift': {
      if (out.numeric_change === true) return t('数字规则核对：回答中的数字变了', 'Number-rule check: numbers in the answer changed');
      const changed = out.drift_anomaly === true || record.label === 'changed';
      return (rule || typeof record.score !== 'number' ? t('规则核对', 'Rule check') : t('语义变化识别', 'Semantic-change recognition')) + t(changed ? '：回答有变化' : '：未标记异常变化', changed ? ': the answer changed' : ': no anomalous change flagged');
    }
    case 'relation': return rule ? t('规则判定 · 逐句核对依据', 'Rule check · sentence evidence') : t('由关系识别判定', 'Judged by relation recognition');
    case 'decision': return t('代价规则：决定判定或暂缓', 'Cost rule: decide or defer');
    case 'behavior': return rule ? t('阶段规则 · 工作过程', 'Phase rules · work process') : t('序列识别 · 工作过程', 'Sequence recognition · work process');
    default: return rule ? t('规则判定', 'Rule check') : actual.method;
  }
}
function recordKey(record: RecognitionRecord, identity: string) {
  let hash = 2166136261;
  for (const char of JSON.stringify([identity, record])) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619);
  return (hash >>> 0).toString(36);
}
/** Same technical card and disclosure behavior as the existing lens. */
export function signatureHtml(record: RecognitionRecord, language: Language, options: CardOptions = {}, identity = '') {
  const id = `rc-moment-card-${recordKey(record, identity)}`;
  const actual = actualMethod(record, language);
  return `<div class="rc-signature-wrap"><button type="button" class="rc-signature" data-rc-card="${id}" aria-controls="${id}" aria-expanded="false" title="${escapeMoment(actual.method)}" data-recognition-method="${actual.mode}">${layersIcon}${language === 'zh' ? '系统如何判断' : 'How this was assessed'}<span aria-hidden="true"> ›</span></button><div id="${id}" class="rc-card-slot" hidden>${cardHtml(record, language, options)}</div></div>`;
}
