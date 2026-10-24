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

/** The question each criterion asks, in a few words; a "not known yet" row reads it. Written
 * from the first sentence of the rubric description (2026-10-24 decision 3); the rubric's own
 * sentence stays word for word in the row's basis (`criterionChecks`). */
export function criterionQuestions(
  language: FeedbackLanguage = document.documentElement.lang?.startsWith('en') ? 'en' : 'zh',
): Record<string, string> {
  const T = (zh: string, en: string) => feedbackText(language, zh, en);
  return {
    'R1.target': T(
      '服务谁、解决什么问题，和需求证据对得上吗',
      'Who does it serve, and does the demand evidence back it?',
    ),
    'R1.metrics': T(
      '怎样算成功：指标有定义、目标和观察口径吗',
      'How will you know it works: measures, targets, how they are observed?',
    ),
    'R2.support': T(
      '关键判断有当时可知的证据支撑吗',
      'Are your key judgments backed by evidence you had at the time?',
    ),
    'R2.unknowns': T(
      '事实、假设与待确认资源分开了吗',
      'Are facts kept apart from assumptions and unconfirmed resources?',
    ),
    'R2.failure_analysis': T(
      '引用或复现了失败案例，并讲清原因吗',
      'Did you cite or reproduce a failure and explain why it happens?',
    ),
    'R3.capacity': T(
      '承诺开放的人数在当时容量之内吗',
      'Do the committed participants fit the capacity at the time?',
    ),
    'R3.resources': T(
      '承诺的人日和日期有有效依据吗',
      'Do the committed person-days and date have valid backing?',
    ),
    'R4.functional_tests': T(
      '在这套配置上实际测了，覆盖所需类别吗',
      'Did you really test this configuration, across the categories it needs?',
    ),
    'R4.staleness_test': T(
      '政策更新后复测了，用的是有效版本吗',
      'Did you retest after the policy update, on current versions?',
    ),
    'R5.impact': T(
      '讲清了变化影响方案的哪些部分吗',
      'Did you explain what the change affects in your plan?',
    ),
    'R5.adjustment': T(
      '实际调整并复测了，而不只是计划吗',
      'Did you actually adjust and retest, beyond saying you would?',
    ),
    'R6.consistency': T('文字、配置、结果和决定一致吗', 'Do your text, configuration, results and decision agree?'),
    'R6.operations': T(
      '负责人、观察期、退出条件和后续动作齐吗',
      'Is there an owner, an observation window, exit conditions and next steps?',
    ),
    'R6.alternatives': T(
      '比较了可行的替代方案并说明取舍吗',
      'Did you compare real alternatives and explain the trade-offs?',
    ),
  };
}

/** What each criterion checks: the first sentence of its description in the final rubric
 * (`rubrics/v4/definitions/rubric-v2-final-20261009.json`), word for word. Frozen: a test
 * compares every sentence with the rubric file. */
export function criterionChecks(
  language: FeedbackLanguage = document.documentElement.lang?.startsWith('en') ? 'en' : 'zh',
): Record<string, string> {
  const T = (zh: string, en: string) => feedbackText(language, zh, en);
  return {
    'R1.target': T(
      '目标用户、业务目标与需求证据是否对应。',
      'Whether target users and business goals match the demand evidence.',
    ),
    'R1.metrics': T(
      '成功指标是否有定义、目标与可观察口径。',
      'Whether success metrics have definitions, targets and observable measures.',
    ),
    'R2.support': T(
      '关键判断是否由当时可知的证据支持。',
      'Whether key judgments are supported by evidence available at the time.',
    ),
    'R2.unknowns': T(
      '是否区分事实、假设与待确认资源。',
      'Whether facts, assumptions and unconfirmed resources are distinguished.',
    ),
    'R2.failure_analysis': T(
      '是否引用或复现失败案例，并正确解释失败模式。',
      'Whether failure cases are cited or reproduced and their failure modes explained.',
    ),
    'R3.capacity': T(
      '正式开放人数是否符合当时有效容量。',
      'Whether committed launch participants fit the effective capacity.',
    ),
    'R3.resources': T(
      '正式承诺的资源和时限是否有有效依据。',
      'Whether committed launch resources and timing have valid support.',
    ),
    'R4.functional_tests': T(
      '相关配置的实际测试是否覆盖已核验类别与验收标准。',
      'Whether actual tests on the relevant configuration cover verified categories and acceptance criteria.',
    ),
    'R4.staleness_test': T(
      '政策更新后是否复测，最新相关动态测试是否使用有效版本。',
      'Whether testing followed a policy update and the latest relevant dynamic test used current versions.',
    ),
    'R5.impact': T(
      '是否说明已知变更对当前方案的影响范围。',
      'Whether the effects of a known change on the current proposal are explained.',
    ),
    'R5.adjustment': T(
      '受影响后是否实际调整并复测，而非只有计划声明。',
      'Whether an affected proposal was actually adjusted and retested, beyond a stated intention.',
    ),
    'R6.consistency': T(
      '文本、配置、实际结果与决定是否相互一致。',
      'Whether text, configuration, actual results and the decision are consistent.',
    ),
    'R6.operations': T(
      '负责人、观察窗口、退出条件和后续动作是否完整可执行。',
      'Whether owner, observation window, exit conditions and follow-up actions are complete and executable.',
    ),
    'R6.alternatives': T(
      '是否比较可行替代方案，并说明取舍依据。',
      'Whether viable alternatives are compared and trade-offs explained.',
    ),
  };
}
