/** UI copy only. Route labels and starter needs mirror public/design.{zh,en}.json (checked in
 * copy.test.ts). Server grading data is never imported into the web bundle. */
import type { ProcessFeedback, StepId, TriageRow } from '../../aipm/types';
import type { Language } from './model';

type Pair = readonly [zh: string, en: string];
const pick = (language: Language, pair: Pair) => (language === 'zh' ? pair[0] : pair[1]);

export const ROUTES: Record<TriageRow['route'], { label: Pair; description: Pair }> = {
  deterministic: {
    label: ['确定性规则', 'Deterministic rules'],
    description: [
      '按确认的输入和规则计算或校验。',
      'Calculate or validate using confirmed inputs and rules.',
    ],
  },
  retrieval_generation: {
    label: ['检索与回答', 'Retrieval and answers'],
    description: [
      '找资料、解释流程，并说明出处与未知。',
      'Find sources and explain processes, with citations and gaps.',
    ],
  },
  agent_confirmation: {
    label: ['Agent 加确认', 'Agent with confirmation'],
    description: [
      '组织多步工作，重要动作前由本人或指定角色确认。',
      'Organize multiple steps with human confirmation before consequential actions.',
    ],
  },
  human: {
    label: ['必须人工', 'Human responsibility'],
    description: [
      '将批准、例外裁量或未授权动作交给有权限的人。',
      'Assign approvals, exceptions and unauthorized actions to the responsible person.',
    ],
  },
};
export const ROUTE_IDS = Object.keys(ROUTES) as TriageRow['route'][];

export const ACTIONS: Record<TriageRow['target_action'], Pair> = {
  explain: ['解释或回答', 'Explain or answer'],
  calculate: ['计算或校验', 'Calculate or check'],
  prepare_draft: ['整理草稿', 'Prepare a draft'],
  execute_change: ['执行变更', 'Execute a change'],
  approve: ['作出最终批准', 'Give final approval'],
  unknown: ['尚未确定', 'Not decided'],
};
export const AUTHORITIES: Record<TriageRow['final_authority'], Pair> = {
  learner: ['我本人', 'Me'],
  named_human_role: ['指定的人工角色', 'A named human role'],
  ai: ['AI 自主完成', 'The AI, on its own'],
  unknown: ['尚未确定', 'Not decided'],
};
export const STARTER_NEEDS: readonly { id: string; scope: string; request: Pair }[] = [
  { id: 'expenses', scope: 'expense', request: ['解释报销流程', 'Explain the expense process'] },
  {
    id: 'access',
    scope: 'access',
    request: ['准备权限申请草稿', 'Prepare an access request draft'],
  },
];
export const SOURCES: Record<ProcessFeedback['source'], Pair> = {
  rule: ['规则核实', 'Rule check'],
  authored_guidance: ['场景引导', 'Authored guidance'],
  colleague_opinion: ['同事意见', 'Colleague opinion'],
  model_suggestion: ['模型建议', 'Model suggestion'],
  learner_assessment: ['本人判断', 'Your assessment'],
};
export const FINDINGS: Record<ProcessFeedback['finding'], Pair> = {
  violation: ['越过当前权限', 'Beyond current authority'],
  improve: ['可以改进', 'Can improve'],
  supported_for_scope: ['在核对范围内成立', 'Holds within checked scope'],
  unknown: ['待核对', 'Needs checking'],
};
/** PRD section headings; ids equal the seven step ids. */
export const SECTIONS: Record<StepId, { title: Pair; prompt: Pair }> = {
  business: {
    title: ['看懂业务', 'Business'],
    prompt: [
      '公司业务、本次内部任务、问题与价值假设。',
      'Company business, this internal task, the problem and value hypothesis.',
    ],
  },
  stakeholders: {
    title: ['用户与相关方', 'Users and stakeholders'],
    prompt: [
      '服务用户、批准者、使用者、受影响者及各自责任。',
      'Served users, approvers, operators, those affected, and their responsibilities.',
    ],
  },
  need: {
    title: ['验证真需求', 'Validated need'],
    prompt: [
      '原始证据、需求假设、反证和成功指标口径。',
      'Original evidence, need hypothesis, counterevidence and success metric definition.',
    ],
  },
  boundary: {
    title: ['AI 边界', 'AI boundary'],
    prompt: [
      '每类请求的处理方式、允许动作与人工责任。',
      'How each request type is handled, permitted actions and human responsibility.',
    ],
  },
  solution: {
    title: ['系统方案', 'System design'],
    prompt: [
      '方案比较、组件策略、依赖与资源。',
      'Options compared, component strategy, dependencies and resources.',
    ],
  },
  assurance: {
    title: ['评测、监控与回退', 'Evaluation, monitoring and rollback'],
    prompt: [
      '验收测试、观察窗口、负责人、告警与回退安排。',
      'Acceptance tests, observation window, owners, alerts and rollback.',
    ],
  },
  decision: {
    title: ['上线决策', 'Launch decision'],
    prompt: [
      '明确决定与条件、交付版本和后续修订。',
      'The decision and its conditions, delivered version and follow-up revisions.',
    ],
  },
};

export function copy(language: Language) {
  const t = (zh: string, en: string) => (language === 'zh' ? zh : en);
  return {
    t,
    route: (id: TriageRow['route']) => pick(language, ROUTES[id].label),
    routeHelp: (id: TriageRow['route']) => pick(language, ROUTES[id].description),
    action: (id: TriageRow['target_action']) => pick(language, ACTIONS[id]),
    authority: (id: TriageRow['final_authority']) => pick(language, AUTHORITIES[id]),
    source: (id: ProcessFeedback['source']) => pick(language, SOURCES[id]),
    finding: (id: ProcessFeedback['finding']) => pick(language, FINDINGS[id]),
    section: (id: StepId) => pick(language, SECTIONS[id].title),
    sectionPrompt: (id: StepId) => pick(language, SECTIONS[id].prompt),
    starter: (need: (typeof STARTER_NEEDS)[number]) => pick(language, need.request),
  };
}
