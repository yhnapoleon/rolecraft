/** Words of the knowledge assistant's answer path, shared by the test bench (answer chain),
 * the evaluation desk and the solution diagram (design view). Plain text only, never markup. */
import { copyText, type CopyTable, type Language } from '../results-native/localization';

/** The five steps every question goes through, in order. */
export const STAGE_KEYS = ['scope', 'found', 'fresh', 'answer', 'result'] as const;
export type StageKey = (typeof STAGE_KEYS)[number];
/** The three offline steps that bring sources into the index (design view only). */
export const OFFLINE_KEYS = ['sources', 'index', 'passages'] as const;
export type OfflineKey = (typeof OFFLINE_KEYS)[number];
/** Who decides or performs a step. */
export type Identity = 'yours' | 'recognizer' | 'daniel' | 'rule' | 'llm';

const ZH = {
  // Step names. The fifth step is "Result" on a run and "Who takes over" in the design.
  stage_scope: '能不能答',
  stage_found: '找到什么',
  stage_fresh: '资料新不新',
  stage_answer: '怎么答',
  stage_result: '结果',
  stage_takeover: '答不了谁接',
  offline_sources: '开放哪些资料',
  offline_index: '多久更新索引',
  offline_passages: '段落怎么切',
  row_offline: '资料怎么进来 · 离线',
  row_online: '每个问题怎么走 · 在线',
  // Identities.
  id_yours: '你的设置',
  id_recognizer: '识别模型',
  id_daniel: 'Daniel 调',
  id_rule: '规则',
  id_llm: '大模型',
  // Setting values.
  update_daily: '每日',
  update_daily_note: '最长滞后 24 小时',
  update_realtime: '实时',
  update_realtime_note: '源文件一变就重建',
  update_manual_policy: '政策人工核',
  update_manual_policy_note: '政策问题转人工',
  guard_none: '不处理',
  guard_warn: '提醒',
  guard_fallback: '转人工',
  generator_extractive: '原文摘录',
  generator_llm: '模型生成',
  on: '开',
  off: '关',
  scope_filter: '范围过滤：{state}',
  scope_detection: '范围外检测',
  human_fallback: '人工兜底：{state}',
  passages_value: '每段 {size} 字 · 取前 {limit} 段',
  threshold_value: '阈值 {value}',
  // Retrieval methods, product names only. Model names stay in the technical layer.
  method_dense: '语义检索',
  method_rrf: '语义检索 + 关键词检索融合',
  method_bm25: '关键词检索',
  method_not_loaded: '（语义模型未加载）',
  method_missing: '这条记录没有记下检索方法',
  // Reasons under the chain.
  reason_prohibited_topic: '没有作答：问题碰到了禁区话题，按规则不答。',
  reason_outside_scope_ood: '没有作答：范围检测认为它不是这个助手该答的问题。',
  reason_outside_scope: '没有作答：它属于你没开放的知识范围。',
  reason_no_retrieval_hit: '没有作答：在开放的资料里没找到足够相关的段落。',
  reason_manual_verification_required: '转给人工：按你的设置，这类政策问题由人工核验。',
  reason_stale_source_guard: '转给人工：引用的资料比现行版本旧，按设置转人工。',
  reason_answered_with_warning: '作答并提醒：用的是旧版本资料，回答前加了「资料可能已更新」。',
  reason_answered_stale: '作答，但资料过期：《{title}》现行是 v{cur}，回答引用了 v{n}。',
  reason_answered_current: '作答：引用《{title}》v{n}，与现行版本一致。',
  reason_answered_uncited: '作答：这次回答没有附引用。',
  reason_no_fallback: '没开人工兜底，所以这次失败。',
  reason_generation_failed: '找到了资料，但模型生成没有通过校验，没有回答。',
  reason_model_unavailable: '选了模型生成，但当时没有接入模型，没有回答。',
  reason_insufficient_sources: '没有作答：模型认为找到的资料不足以回答。',
  reason_unrecorded: '这条记录没有记下它走了哪条路。',
  // Each step's state, read aloud as "In scope?: in scope".
  sr_sentence: '{stage}：{state}',
  sr_stopped: '在这里停下',
  sr_unrecorded: '这一步没有记录',
  state_not_reached: '没走到这一步',
  state_unrecorded: '这条记录没有记下这一步',
  state_in_scope: '在范围内',
  state_out_of_scope: '不在范围内',
  state_prohibited: '碰到禁区话题',
  state_area_closed: '属于没开放的知识范围',
  state_found: '找到了相关段落',
  state_not_found: '没找到足够相关的段落',
  state_current: '与现行版本一致',
  state_outdated: '资料过期',
  state_no_citation: '没有引用，无法核对版本',
  state_manual: '转人工核验',
  state_stale_guard: '资料过期，转人工',
  state_answer_failed: '生成没有通过校验',
  state_answer_unavailable: '没有接入模型',
  state_answer_insufficient: '模型认为资料不足',
  state_answer_unrecorded: '这条记录没有记下回答方式',
  outcome_answered: '作答',
  outcome_warned: '带提醒作答',
  outcome_handed: '转人工',
  outcome_failed: '失败',
  outcome_unrecorded: '这条记录没有记下结果',
  // Expanded rows.
  row_scope_real: '范围外检测：{state}（距离 {score}，阈值 {threshold}）',
  row_scope_fallback: '范围检测未加载，按检索结果判断（规则）',
  row_scope_missing: '这条记录没有记下范围检测',
  row_prohibited: '禁区话题：碰到了（规则）',
  row_found: '{method}：{passing} 段过了阈值 {min_score}，取前 {limit} 段',
  row_found_missing: '这条记录没有记下这一步',
  row_update: '更新方式：{value}',
  row_guard: '过期处理：{value}',
  row_versions: '《{title}》现行 v{cur}，索引 v{idx}',
  // Controls.
  path_label: '这一题走了哪条路',
  show_steps: '展开每一步',
  hide_steps: '收起每一步',
  handover: '交给 Daniel 试修',
  how_judged: '系统如何判断 ›',
} as const;

export type ChainCopyKey = keyof typeof ZH;

const EN: Record<ChainCopyKey, string> = {
  stage_scope: 'In scope?',
  stage_found: 'Found',
  stage_fresh: 'Up to date?',
  stage_answer: 'Answer',
  stage_result: 'Result',
  stage_takeover: 'Who takes over',
  offline_sources: 'Sources opened',
  offline_index: 'Index updates',
  offline_passages: 'Passages',
  row_offline: 'How sources come in · offline',
  row_online: 'How each question runs · online',
  id_yours: 'Your setting',
  id_recognizer: 'Recognition model',
  id_daniel: 'Daniel tunes',
  id_rule: 'Rule',
  id_llm: 'Language model',
  update_daily: 'Daily',
  update_daily_note: 'up to 24 hours behind',
  update_realtime: 'Real-time',
  update_realtime_note: 'rebuilt whenever a source changes',
  update_manual_policy: 'Manual policy check',
  update_manual_policy_note: 'policy questions go to people',
  guard_none: 'no action',
  guard_warn: 'warn',
  guard_fallback: 'hand to a person',
  generator_extractive: 'Extractive',
  generator_llm: 'Model-generated',
  on: 'on',
  off: 'off',
  scope_filter: 'scope filter {state}',
  scope_detection: 'Out-of-scope detection',
  human_fallback: 'human fallback {state}',
  passages_value: '{size} characters each · top {limit} used',
  threshold_value: 'threshold {value}',
  method_dense: 'Semantic retrieval',
  method_rrf: 'Semantic + keyword retrieval (fused)',
  method_bm25: 'Keyword retrieval',
  method_not_loaded: ' (semantic model not loaded)',
  method_missing: 'This record does not say which retrieval method ran',
  reason_prohibited_topic:
    'Not answered: the question touches a restricted topic, so the rules stop it.',
  reason_outside_scope_ood:
    'Not answered: scope detection judged it outside what this assistant should answer.',
  reason_outside_scope: 'Not answered: it belongs to a knowledge area you have not opened.',
  reason_no_retrieval_hit: 'Not answered: nothing relevant enough was found in the open sources.',
  reason_manual_verification_required:
    'Handed to a person: your settings send this kind of policy question to manual checking.',
  reason_stale_source_guard:
    'Handed to a person: the cited source is older than the current version, so it was handed over.',
  reason_answered_with_warning:
    'Answered with a warning: it used an older source version and says the source may have changed.',
  reason_answered_stale:
    'Answered from an outdated source: {title} is now v{cur}, but the answer cites v{n}.',
  reason_answered_current: 'Answered from {title} v{n}, the current version.',
  reason_answered_uncited: 'Answered without a citation.',
  reason_no_fallback: 'Human fallback is off, so this run failed.',
  reason_generation_failed:
    "Sources were found, but the model's answer failed validation, so there is no answer.",
  reason_model_unavailable:
    'Model generation was selected, but no model was connected, so there is no answer.',
  reason_insufficient_sources: 'Not answered: the model judged the sources it found insufficient.',
  reason_unrecorded: 'This record does not say which path it took.',
  sr_sentence: '{stage}: {state}',
  sr_stopped: 'stopped here',
  sr_unrecorded: 'this step was not recorded',
  state_not_reached: 'not reached',
  state_unrecorded: 'this record does not cover this step',
  state_in_scope: 'in scope',
  state_out_of_scope: 'out of scope',
  state_prohibited: 'touches a restricted topic',
  state_area_closed: 'in a knowledge area not opened',
  state_found: 'relevant passages found',
  state_not_found: 'nothing relevant enough found',
  state_current: 'matches the current version',
  state_outdated: 'source out of date',
  state_no_citation: 'no citation, so the version cannot be checked',
  state_manual: 'sent to manual checking',
  state_stale_guard: 'source out of date, handed over',
  state_answer_failed: 'generation failed validation',
  state_answer_unavailable: 'no model connected',
  state_answer_insufficient: 'model found the sources insufficient',
  state_answer_unrecorded: 'this record does not say how it answered',
  outcome_answered: 'answered',
  outcome_warned: 'answered with a warning',
  outcome_handed: 'handed to a person',
  outcome_failed: 'failed',
  outcome_unrecorded: 'this record does not say how it ended',
  row_scope_real: 'out-of-scope detection: {state} (distance {score}, threshold {threshold})',
  row_scope_fallback: 'Scope model not loaded; judged from retrieval (rule)',
  row_scope_missing: 'This record does not include scope detection',
  row_prohibited: 'restricted topic: matched (rule)',
  row_found: '{method}: {passing} passages cleared {min_score}; top {limit} used',
  row_found_missing: 'This record does not cover this step',
  row_update: 'updates: {value}',
  row_guard: 'when outdated: {value}',
  row_versions: '{title} now v{cur}, index v{idx}',
  path_label: 'Path this question took',
  show_steps: 'Show each step',
  hide_steps: 'Hide steps',
  handover: 'Hand to Daniel',
  how_judged: 'How the system judged ›',
};

export const CHAIN_COPY: CopyTable<ChainCopyKey> = { zh: ZH, en: EN };

export const chainText = (
  language: Language,
  key: ChainCopyKey,
  values: Readonly<Record<string, string | number>> = {},
) => copyText(CHAIN_COPY, language, key, values);

/** Name of an online step; `design` names the fifth step "Who takes over". */
export const stageName = (key: StageKey, language: Language, design = false) =>
  chainText(language, key === 'result' && design ? 'stage_takeover' : `stage_${key}`);
export const offlineName = (key: OfflineKey, language: Language) =>
  chainText(language, `offline_${key}`);
export const identityName = (identity: Identity, language: Language) =>
  chainText(language, `id_${identity}`);

/** The main identity of each step, as shown under its name. */
export const STAGE_IDENTITY: Readonly<Record<StageKey, Identity>> = {
  scope: 'recognizer',
  found: 'recognizer',
  fresh: 'daniel',
  answer: 'yours',
  result: 'yours',
};
export const OFFLINE_IDENTITY: Readonly<Record<OfflineKey, Identity>> = {
  sources: 'yours',
  index: 'yours',
  passages: 'daniel',
};

/** Setting values in product words; unknown values come back as null, never guessed. */
export function updateStrategyText(value: unknown, language: Language) {
  if (value !== 'daily' && value !== 'realtime' && value !== 'manual_policy') return null;
  return {
    value: chainText(language, `update_${value}`),
    note: chainText(language, `update_${value}_note`),
  };
}
export function guardText(value: unknown, language: Language) {
  return value === 'none' || value === 'warn' || value === 'fallback'
    ? chainText(language, `guard_${value}`)
    : null;
}
export function generatorText(value: unknown, language: Language) {
  return value === 'extractive' || value === 'llm'
    ? chainText(language, `generator_${value}`)
    : null;
}
export const onOff = (value: boolean, language: Language) =>
  chainText(language, value ? 'on' : 'off');

/** Retrieval method in product words; `fallback` adds that the semantic model was not loaded. */
export function methodText(method: unknown, fallback: boolean, language: Language) {
  const name =
    method === 'dense' || method === 'rrf' || method === 'bm25'
      ? chainText(language, `method_${method}`)
      : null;
  if (!name) return chainText(language, 'method_missing');
  return fallback ? name + chainText(language, 'method_not_loaded') : name;
}
