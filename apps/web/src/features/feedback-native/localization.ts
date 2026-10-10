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
  purposeChosen: '已按“{purpose}”重新评审，新的反馈另列。',
  exploration: '探索笔记',
  option: '方案比较',
  test_plan: '测试计划',
  commitment: '试点决定',
  result: '结果报告',
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
    exploration: 'Exploration note',
    option: 'Option comparison',
    test_plan: 'Test plan',
    commitment: 'Pilot decision',
    result: 'Result report',
  },
};
export const feedbackCopy = (
  language: FeedbackLanguage,
  key: FeedbackCopyKey,
  values?: Readonly<Record<string, string | number>>,
) => copyText(FEEDBACK_COPY, language, key, values);
