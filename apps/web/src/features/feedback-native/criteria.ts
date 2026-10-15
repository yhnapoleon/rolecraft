import { feedbackText, type FeedbackLanguage } from './localization';

/** Display names of rubric criteria; shared by the feedback panel, the optional-practice basis
 * and the pre-submission preview. */
export function criterionLabels(
  language: FeedbackLanguage = document.documentElement.lang?.startsWith('en') ? 'en' : 'zh',
): Record<string, string> {
  const T = (zh: string, en: string) => feedbackText(language, zh, en);
  return {
    'R1.target': T('目标用户与业务目标', 'Target users and business goals'),
    'R1.metrics': T('指标与验收口径', 'Metrics and acceptance criteria'),
    'R2.support': T('判断的证据支持', 'Evidence supporting judgments'),
    'R2.unknowns': T('事实与待确认事项', 'Facts and unresolved questions'),
    'R2.failure_analysis': T('失败案例与原因分析', 'Failure cases and analysis'),
    'R4.staleness_test': T('政策更新后的复测', 'Retesting after policy changes'),
    'R5.impact': T('变更影响', 'Impact of changes'),
    'R5.adjustment': T('实际调整与复测', 'Actual adjustments and retesting'),
    'R6.consistency': T('作品与配置一致性', 'Consistency of artifacts and configuration'),
    'R6.operations': T('后续运行安排', 'Operational follow-up'),
    'R6.alternatives': T('替代方案与取舍', 'Alternatives and trade-offs'),
    'R3.capacity': T('人数与容量', 'Participants and capacity'),
    'R3.resources': T('资源与时间', 'Resources and timing'),
    'R4.functional_tests': T('实际测试', 'Actual tests'),
    'R6.comparison': T('方案比较', 'Option comparison'),
    'decision.rationale': T('决定依据', 'Basis for the decision'),
    'decision.follow_up': T('后续安排', 'Follow-up'),
    'result.claims': T('已完成事项的声明', 'Completion claims'),
  };
}
