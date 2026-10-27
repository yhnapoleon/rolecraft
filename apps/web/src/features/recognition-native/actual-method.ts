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
        category = t('引用核验', 'Citation verification');
        method = fallback
          ? t('引文定位规则', 'Citation-location rules')
          : t(
              '引文定位；关系模型参与情况未单列',
              'Citation lookup; relation-model participation not recorded separately',
            );
        if (out.delegated_to_llm) method += t('；已交评审模型复核', '; delegated to the reviewer');
        // fallback records the availability of C1, not whether every optional model branch ran.
        mode = fallback ? 'fallback' : 'unknown';
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
export type RetrievalKind =
  | 'fused'
  | 'semantic'
  | 'keyword_fallback'
  | 'keyword'
  | 'none'
  | 'unrecorded';
type RetrievalField = { method?: unknown; fallback?: unknown };
const recorded = (value: unknown): value is RetrievalField =>
  !!value && typeof value === 'object' && 'method' in value;
/** The retrieval method one sentence actually ran, from its own `retrieval`, the preview's
 * pass-wide `retrieval`, or an older record's `retrieval_method`. Absent means not recorded;
 * a recorded null means no candidate passages, never a guessed method. A keyword fallback
 * carries why in `note`. */
export function retrievalMethod(
  unit: { retrieval?: unknown; retrieval_method?: unknown } | null | undefined,
  preview: object | null | undefined,
  language: Language,
): { kind: RetrievalKind; label: string; note?: string } {
  const t = (zh: string, en: string) => (language === 'zh' ? zh : en);
  const field = recorded(unit?.retrieval)
    ? unit.retrieval
    : preview && 'retrieval' in preview && recorded(preview.retrieval)
      ? preview.retrieval
      : typeof unit?.retrieval_method === 'string'
        ? { method: unit.retrieval_method }
        : null;
  const kind: RetrievalKind = !field
    ? 'unrecorded'
    : field.method === null
      ? 'none'
      : field.method === 'rrf'
        ? 'fused'
        : field.method === 'dense'
          ? 'semantic'
          : field.method === 'bm25'
            ? field.fallback === true
              ? 'keyword_fallback'
              : 'keyword'
            : 'unrecorded';
  const label = {
    fused: t('语义检索 + 关键词检索融合', 'Semantic + keyword retrieval (fused)'),
    semantic: t('语义检索', 'Semantic retrieval'),
    keyword_fallback: t('关键词检索', 'Keyword retrieval'),
    keyword: t('关键词检索', 'Keyword retrieval'),
    none: t('没有候选段落', 'No candidate passages'),
    unrecorded: t(
      '这条记录没有记下检索方法',
      'This record does not say which retrieval method ran',
    ),
  }[kind];
  // The fallback is the same method run for a reason; the reason reads as a quieter aside.
  return kind === 'keyword_fallback'
    ? { kind, label, note: t('（语义模型未加载）', ' (semantic model not loaded)') }
    : { kind, label };
}
