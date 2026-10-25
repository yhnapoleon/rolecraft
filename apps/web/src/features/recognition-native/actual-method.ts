import type { RecognitionRecord } from './badge';
import type { Language } from '../results-native/localization';
import { LENS_COPY } from './lens-copy';
/** Execution facts only. The method family remains in the separate reference panel. */
export function actualMethod(record: RecognitionRecord, language: Language) {
  const out = record.outputs ?? {};
  const t = (zh: string, en: string) => (language === 'zh' ? zh : en);
  const w = LENS_COPY[language];
  const fallback = !!record.fallback || /rule-fallback/.test(record.revision);
  const rule = t('规则', 'Rule');
  let category = rule,
    method = t('记录未说明实际方法', 'Actual method not recorded');
  let mode: 'real' | 'fallback' | 'rule' | 'unknown' = fallback ? 'fallback' : 'real';
  switch (record.task) {
    case 'retrieval':
      if (out.method === 'dense') {
        category = t('深度学习', 'Deep learning');
        method = t('e5 向量（dense）', 'e5 dense');
      } else if (out.method === 'rrf') {
        category = w.cat_hybrid;
        method = w.m_retrieval;
      } else if (out.method === 'bm25') {
        category = t('词项检索', 'Lexical retrieval');
        method = 'BM25';
        if (!fallback) mode = 'rule';
      } else {
        category = t('检索', 'Retrieval');
        mode = fallback ? 'fallback' : 'unknown';
      }
      break;
    case 'scope':
      category = fallback ? rule : w.cat_unsupervised;
      method = fallback ? t('检索命中规则', 'Retrieval-hit rule') : w.m_scope;
      break;
    case 'drift':
      if (typeof record.score === 'number') {
        category = w.cat_unsupervised;
        method =
          t('e5 余弦距离 + 数字核对', 'e5 cosine distance + number check') +
          (fallback ? t('（默认阈值）', ' (default threshold)') : '');
      } else {
        category = rule;
        method = t('文字变化核对', 'Text-change check');
      }
      break;
    case 'intent':
      category = fallback ? rule : w.cat_supervised_classic;
      method = fallback ? t('关键词规则', 'Keyword rule') : w.m_intent;
      break;
    case 'behavior':
      category = fallback ? rule : w.cat_behavior;
      method = fallback
        ? t('阶段与异常规则', 'Phase and anomaly rules')
        : t('DTW + HMM；异常提醒用规则', 'DTW + HMM; rule-based anomaly notices');
      break;
    case 'reply_check':
      category = fallback ? rule : w.cat_supervised;
      method = fallback
        ? t('检索 + 关系规则逐句核对', 'Retrieval + relation rules per sentence')
        : t('检索 + 关系模型逐句核对', 'Retrieval + relation model per sentence');
      break;
    case 'relation':
      category = fallback
        ? rule
        : /stack/.test(record.recognizer_id)
          ? w.cat_ensemble
          : w.cat_supervised_deep;
      method =
        out.mode === 'support_check'
          ? w.m_support
          : fallback
            ? w.m_relation_rule
            : /stack/.test(record.recognizer_id)
              ? w.m_relation_stack
              : w.m_relation;
      if (out.mode === 'support_check') {
        category = rule;
        mode = 'rule';
      }
      break;
    case 'decision':
      category = w.cat_decision;
      method = w.m_decision;
      mode = 'rule';
      break;
    case 'arbiter':
      category = w.cat_decision;
      method = w.m_arbiter;
      mode = 'rule';
      break;
    default:
      mode = 'unknown';
  }
  return { category, method, mode, fallback };
}
