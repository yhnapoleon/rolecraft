import { copyText, type CopyTable } from '../results-native/localization';

/** Authored UI copy uses paired texts. Stored feedback and quotes are untouched. */
export type FeedbackLanguage = 'zh' | 'en';
export function feedbackText(language: FeedbackLanguage, zh: string, en: string) {
  return language === 'en' ? en : zh;
}

const zh = {
  statusLabel: '反馈概况',
  factsVerified: '事实记录已核实',
  factsPartial: '事实记录部分核实',
  factsUnknown: '事实记录待核验',
  verified: '规则核实 {n} 项',
  pending: '待核验 {n} 项',
  undetermined: '待确认适用 {n} 项',
  notApplicable: '本次不适用 {n} 项',
  noItems: '尚无适用项。',
  coverageEmpty: '尚无适用项',
  purposeUnknown: '作品用途未明确，{n} 项责任都待确认。先说明这份作品现在用来做什么。',
  showItems: '展开 {n} 项',
  showRecords: '查看记录与依据',
  purposeQuestion: '这份作品现在用来做什么？',
  purposeSubmit: '按这个用途重新评审',
  purposeNote: '会另存一次评审，原反馈保留。',
  purposeChosen: '已按「{purpose}」重新评审，新的反馈另列。',
  reviewedAs: '按「{purpose}」评审',
  exploration: '探索笔记',
  option: '方案比较',
  test_plan: '测试计划',
  commitment: '试点决定',
  result: '结果报告',
  // 2026-10-11 decision 5: a range of the rule-anchored part only; never a single total.
  rangeFull: '规则已定标部分：{lower}–{upper} 分（满分 {full}）',
  rangePart: '规则已定标部分：{lower}–{upper} 分（适用项共 {denominator} 分，满分 {full}）',
  // 2026-10-12 item 2: name the undetermined share of the denominator.
  rangeUndetermined:
    '规则已定标部分：{lower}–{upper} 分（适用项共 {denominator} 分，其中 {undetermined} 分适用性待确认，满分 {full}）',
  // 2026-10-12 item 3: item counts only, never a percentage.
  coverageLine:
    '已核实 {verified} 项／共 {total} 项适用 · 模型建议 {model} 项 · 待核验 {pending} 项',
  rangeNote: '模型建议不计分；待核验项使区间变宽。',
  rangeEmpty: '规则已定标部分：尚无适用项，不形成区间。',
  rangeVersion: '分数区间：此评价标准版本不汇总。',
  rangeUnrecorded: '分数区间：这份反馈生成时未记录。',
  rangeWithheld: '分数区间：当前权限下部分依据不可核验，暂不显示。',
  weightAnchored: '权重 {weight} 分（满分 {full}）· 规则已定标：计 {points} 分',
  weightBounded: '权重 {weight} 分（满分 {full}）· 规则限定 {lower}–{upper} 分，其余待核验',
  weightPending: '权重 {weight} 分（满分 {full}）· 待核验：不计分，区间因此加宽 {weight} 分',
  weightUndetermined:
    '权重 {weight} 分（满分 {full}）· 适用性待确认：不计分，区间因此加宽 {weight} 分',
  weightNotApplicable: '权重 {weight} 分（满分 {full}）· 本次不适用：不计入分母',
  delivery: '第 {n} 次交付',
  deliverySnapshot: '查看第 {n} 次交付的快照',
  deliverySnapshotUnnumbered: '查看提交快照',
};
export type FeedbackCopyKey = keyof typeof zh;
export const FEEDBACK_COPY: CopyTable<FeedbackCopyKey> = {
  zh,
  en: {
    statusLabel: 'Feedback overview',
    factsVerified: 'Fact records verified',
    factsPartial: 'Fact records partly verified',
    factsUnknown: 'Fact records awaiting verification',
    verified: 'Verified by rules: {n}',
    pending: 'Pending verification: {n}',
    undetermined: 'Applicability undetermined: {n}',
    notApplicable: 'Not applicable this time: {n}',
    noItems: 'No applicable items yet.',
    coverageEmpty: 'No applicable items yet',
    purposeUnknown:
      'The purpose of this work is not specified, so all {n} items are undetermined. Say what the work is for first.',
    showItems: 'Show all {n} items',
    showRecords: 'Show records and evidence',
    purposeQuestion: 'What is this work for right now?',
    purposeSubmit: 'Review again for this purpose',
    purposeNote: 'This saves another review; the original feedback is kept.',
    purposeChosen: 'Reviewed again as “{purpose}”; the new feedback is listed separately.',
    reviewedAs: 'Reviewed as “{purpose}”',
    exploration: 'Exploration note',
    option: 'Option comparison',
    test_plan: 'Test plan',
    commitment: 'Pilot decision',
    result: 'Result report',
    rangeFull: 'Rule-anchored part: {lower}–{upper} of {full}',
    rangePart:
      'Rule-anchored part: {lower}–{upper} of {denominator} (applicable items; full rubric {full})',
    rangeUndetermined:
      'Rule-anchored part: {lower}–{upper} of {denominator} (applicable items, including {undetermined} points whose applicability is undetermined; full rubric {full})',
    coverageLine:
      'Verified {verified} of {total} applicable items · Model advice {model} · Pending verification {pending}',
    rangeNote: 'Model advice is not scored; pending items widen the range.',
    rangeEmpty: 'Rule-anchored part: nothing applies yet, so there is no range.',
    rangeVersion: 'No range for this rubric version.',
    rangeUnrecorded: 'No range was recorded with this feedback.',
    rangeWithheld: 'Range withheld: some evidence can’t be checked with your current access.',
    weightAnchored: 'Weight {weight} of {full} · Rule-anchored: {points} points',
    weightBounded:
      'Weight {weight} of {full} · Rule-bounded: {lower}–{upper} points; the rest is pending',
    weightPending: 'Weight {weight} of {full} · Pending: not scored; widens the range by {weight}',
    weightUndetermined:
      'Weight {weight} of {full} · Applicability undetermined: not scored; widens the range by {weight}',
    weightNotApplicable: 'Weight {weight} of {full} · Not applicable: left out of the denominator',
    delivery: 'Submission {n}',
    deliverySnapshot: 'View the snapshot of submission {n}',
    deliverySnapshotUnnumbered: 'View submission snapshot',
  },
};
export const feedbackCopy = (
  language: FeedbackLanguage,
  key: FeedbackCopyKey,
  values?: Readonly<Record<string, string | number>>,
) => copyText(FEEDBACK_COPY, language, key, values);
