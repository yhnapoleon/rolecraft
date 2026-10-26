/** Deterministic display projection. Never changes a recorded decision or fills a missing score. */
import type { ChainUnit, PreviewRecognition } from './chain';
import type { Language } from '../results-native/localization';
export const relationLabels = ['supported', 'contradicted', 'insufficient'] as const;
export function validDistribution(p?: Record<string, number> | null) {
  return (
    !!p &&
    Object.keys(p).length === 3 &&
    relationLabels.every(
      (k) => typeof p[k] === 'number' && Number.isFinite(p[k]) && p[k] >= 0 && p[k] <= 1,
    ) &&
    Math.abs(relationLabels.reduce((s, k) => s + p[k], 0) - 1) <= 0.010000000001
  );
}
export function leadingProbability(p?: Record<string, number> | null) {
  if (!validDistribution(p)) return null;
  const values = p as Record<string, number>;
  const value = Math.max(...relationLabels.map((k) => values[k]));
  return { labels: relationLabels.filter((k) => values[k] === value), value };
}
export function businessSentenceState(unit: Pick<ChainUnit, 'label' | 'decision'>) {
  if (unit.decision === 'defer') return 'deferred';
  return unit.decision === 'decide' && relationLabels.some((k) => k === unit.label)
    ? unit.label
    : 'unknown';
}
export function checkPresentation(
  unit: ChainUnit,
  preview: PreviewRecognition,
  language: Language,
) {
  const t = (zh: string, en: string) => (language === 'zh' ? zh : en);
  const state = businessSentenceState(unit);
  const model =
    leadingProbability(unit.branches?.stack) ?? leadingProbability(unit.branches?.encoder);
  const rule = leadingProbability(unit.branches?.rule);
  const ruleOnly = preview.fallback === true && !!preview.recognizer;
  const invalid = [unit.branches?.stack, unit.branches?.encoder, unit.branches?.rule].some(
    (p) => p != null && !validDistribution(p),
  );
  const agreement = ruleOnly
    ? 'rule'
    : invalid
      ? 'incomplete'
      : model?.labels.length === 2 ||
          model?.labels.length === 3 ||
          rule?.labels.length === 2 ||
          rule?.labels.length === 3
        ? 'tie'
        : model && rule
          ? model.labels[0] === rule.labels[0]
            ? 'agree'
            : 'disagree'
          : model || rule
            ? 'single'
            : 'incomplete';
  const relation = {
    rule: t('仅规则核对', 'Checked by rules only'),
    incomplete: t('分支记录不完整', 'Branch details are incomplete'),
    tie: t('倾向未分开', 'No single result stands out'),
    agree: t('检查意见一致', 'Both checks point the same way'),
    disagree: t('检查有分歧', 'The checks disagree'),
    single: t('只记录了一项检查', 'Only one check was recorded'),
  }[agreement];
  const status =
    {
      deferred: t('待你核验', 'Needs your review'),
      supported: t('有资料支持', 'Supported by the source'),
      contradicted: t('与资料有冲突', 'Conflicts with the source'),
      insufficient: t('依据待补', 'Needs supporting evidence'),
      unknown: t('核对记录不完整', 'Check details are incomplete'),
    }[state] ?? t('核对记录不完整', 'Check details are incomplete');
  const hint =
    state === 'deferred'
      ? agreement === 'disagree'
        ? t(
            '两项检查有分歧，这句先留给你确认。',
            'The checks disagree, so this claim needs your review.',
          )
        : t('这次核对把判断留给你。', 'This check leaves the decision to you.')
      : state === 'supported'
        ? t('本次资料支持这句话。', 'The selected source supports this claim.')
        : state === 'contradicted'
          ? t(
              '这句话与本次选中的资料有冲突。请对照原文核验。',
              'This claim conflicts with the selected source. Compare it with the passage.',
            )
          : state === 'insufficient'
            ? t('本次核对还未找到足够依据。', 'This check did not find enough supporting evidence.')
            : t(
                '已有记录不足以说明最终处理方式。',
                'The record does not establish a final decision.',
              );
  const match =
    /^(?:late_fusion:(?:0(?:\.\d+)?|1(?:\.0+)?)\|)?exceeds_limit:(\d+(?:\.\d+)?)>(\d+(?:\.\d+)?) (cny|days|people)$/.exec(
      unit.reason ?? '',
    );
  const comparison =
    match && Number(match[1]) > Number(match[2])
      ? { value: match[1], limit: match[2], unit: match[3] }
      : null;
  const meaning = ruleOnly
    ? t('本次仅记录规则核对。', 'Only rule checks were recorded.')
    : !model
      ? t('未记录内容理解结果。', 'No meaning-check result was recorded.')
      : model.labels.length > 1
        ? t('内容理解的倾向未分开。', 'No single meaning-check result stands out.')
        : model.labels[0] === 'insufficient'
          ? t(
              '还没有找到足够依据支持这句话。',
              'Not enough evidence was found to support this claim.',
            )
          : model.labels[0] === 'supported'
            ? t('内容理解倾向于资料支持这句话。', 'The meaning check leans towards support.')
            : t('内容理解发现说法与资料有冲突。', 'The meaning check points to a conflict.');
  const numberHint = comparison
    ? t(
        `你写的 ${comparison.value} ${comparison.unit === 'cny' ? '元' : comparison.unit === 'days' ? '天' : '人'}超过了记录里的 ${comparison.limit} ${comparison.unit === 'cny' ? '元' : comparison.unit === 'days' ? '天' : '人'}上限。`,
        `Your claim says ${comparison.unit.toUpperCase()} ${comparison.value}; the recorded limit is ${comparison.unit.toUpperCase()} ${comparison.limit}.`,
      )
    : unit.branches?.rule === null
      ? t('这次没有可比较的数字。', 'No comparable numbers were found.')
      : !rule
        ? t('未记录数字核对结果。', 'No number-check result was recorded.')
        : rule.labels.length > 1
          ? t('数字核对的倾向未分开。', 'No single number-check result stands out.')
          : rule.labels[0] === 'contradicted'
            ? t(
                '数字核对发现冲突，请对照原文。',
                'The number check found a conflict. Compare the source.',
              )
            : rule.labels[0] === 'supported'
              ? t('数字核对与记录相符。', 'The number check agrees with the record.')
              : t('数字核对还没有足够依据。', 'The number check has insufficient evidence.');
  return {
    state,
    status,
    hint,
    agreement,
    relation,
    model,
    rule,
    ruleOnly,
    meaning,
    numberHint,
    comparison,
  };
}
