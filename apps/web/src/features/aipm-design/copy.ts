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
/** One PRD section per step. Examples come from another company on purpose: they show the
 * shape of an answer without handing over this practice's answer. */
type Section = { title: Pair; question: Pair; why: Pair; example: readonly Pair[] };
export const SECTIONS: Record<StepId, Section> = {
  business: {
    title: ['业务理解', 'Business understanding'],
    question: [
      '这家公司靠什么服务客户，这次要帮谁？',
      'How does the company serve customers, and who is this pilot for?',
    ],
    why: [
      '先分清公司的经营业务和这次的内部工具任务。后面判断谁受益、哪些事能交给 AI，都从这里出发。',
      'Separate the company’s business from this internal tool task. Every later call about who benefits and what AI may do starts here.',
    ],
    example: [
      ['服务对象：公司内部员工', 'Who it serves: internal staff'],
      [
        '公司业务：连锁咖啡店，向顾客卖饮品和简餐',
        'Business: a coffee chain selling drinks and light meals',
      ],
      [
        '这次任务：帮店长回答排班规则问题，减少每周来回确认',
        'This task: answer shift-rule questions for store managers, cutting weekly back-and-forth',
      ],
    ],
  },
  stakeholders: {
    title: ['用户与相关方', 'Users and stakeholders'],
    question: [
      '谁会用它，谁批准，谁承担后果？',
      'Who uses it, who approves, and who lives with the outcome?',
    ],
    why: [
      '用的人、批准的人和承担后果的人往往不是同一批。写清楚，后面才知道谁来确认、谁会多出工作。',
      'Users, approvers and those affected are often different people. Naming them tells you later who confirms and who gets extra work.',
    ],
    example: [
      [
        '店员 · 使用者 · 有原文依据：查自己的班次',
        'Baristas · users · documented: check their own shifts',
      ],
      [
        '区域经理 · 批准者 · 有原文依据：批准加班',
        'Area manager · approver · documented: approves overtime',
      ],
      [
        'HR · 受影响者 · 我的推测：处理排班投诉',
        'HR · affected · my guess: handles scheduling complaints',
      ],
    ],
  },
  need: {
    title: ['真需求', 'The real need'],
    question: [
      '要解决的问题是什么，什么事实会推翻它？',
      'What problem are you solving, and what fact would disprove it?',
    ],
    why: [
      '需求先当成假设。写下会推翻它的事实，才知道接下来该先核对什么。',
      'Treat the need as a hypothesis. Writing down what would disprove it tells you what to check first.',
    ],
    example: [
      [
        '问题：店长每周花不少时间回答排班规则',
        'Problem: managers spend hours each week answering shift rules',
      ],
      ['状态：假设', 'Status: hypothesis'],
      [
        '会推翻它的事实：大多数问题其实是请假审批，不是规则咨询',
        'Would disprove it: most questions are leave approvals, not rule questions',
      ],
      ['下一步：抽查 20 条店长聊天记录', 'Next: sample 20 manager chat threads'],
    ],
  },
  boundary: {
    title: ['AI 边界', 'AI boundary'],
    question: [
      '每项请求要回答还是要行动，最后谁说了算？',
      'Does each request need an answer or an action, and who has the final say?',
    ],
    why: [
      '一项请求可能只是要回答，也可能要真的去做事。先拆清动作，再定谁有最后决定权；越权的地方规则会直接指出。',
      'A request may need an answer or a real action. Separate the action first, then who decides; rules flag anything beyond current authority.',
    ],
    example: [
      ['「帮我把下周加班批了」', '“Approve my overtime next week”'],
      [
        '动作：作出最终批准 → 必须人工，由区域经理批准',
        'Action: final approval → human responsibility, the area manager approves',
      ],
      [
        '助手可以另拆一项：整理加班理由草稿，交经理确认',
        'Split out for the assistant: draft the overtime reason for the manager to confirm',
      ],
    ],
  },
  solution: {
    title: ['系统方案', 'System design'],
    question: ['选哪种做法，为什么不选另一种？', 'Which approach, and why not the alternative?'],
    why: [
      '方案图按你保存的分拣自动生成。这里写选定做法、理由，以及至少一个认真考虑过的替代做法。',
      'The diagram is drawn from your saved triage. Write the chosen approach, why, and at least one alternative you seriously weighed.',
    ],
    example: [
      [
        '选定：先做排班规则问答，加班申请只拟稿交经理确认',
        'Chosen: start with shift-rule answers; overtime requests are drafted for the manager',
      ],
      [
        '替代：接入排班系统自动改班——依赖系统接口，本期不做',
        'Alternative: change shifts automatically via the rota system — needs its API, not this phase',
      ],
    ],
  },
  assurance: {
    title: ['评测、监控与回退', 'Evaluation, monitoring and rollback'],
    question: [
      '用什么证明方案可行，出错怎么退？',
      'What proves the design works, and how do you roll back?',
    ],
    why: ['这一节在评测台完成。', 'This section is done in the evaluation desk.'],
    example: [],
  },
  decision: {
    title: ['上线决策', 'Launch decision'],
    question: ['在什么条件下上线？', 'Under what conditions do you launch?'],
    why: ['这一节在交付时完成。', 'This section is completed when you deliver.'],
    example: [],
  },
};
export const AUDIENCES = {
  internal: ['公司内部员工', 'Internal staff'],
  external: ['外部客户', 'External customers'],
  both: ['两者都有', 'Both'],
  unknown: ['还不确定', 'Not sure yet'],
} as const satisfies Record<string, Pair>;
export const RELATIONSHIPS = {
  user: ['使用者', 'User'],
  buyer: ['出资方', 'Sponsor'],
  approver: ['批准者', 'Approver'],
  operator: ['操作者', 'Operator'],
  affected: ['受影响者', 'Affected'],
} as const satisfies Record<string, Pair>;
export const BASIS = {
  fact: ['有原文依据', 'Documented'],
  hypothesis: ['我的推测', 'My guess'],
  unknown: ['不确定', 'Unsure'],
} as const satisfies Record<string, Pair>;
export const CLAIMS = {
  hypothesis: ['假设', 'Hypothesis'],
  supported: ['有证据支持', 'Supported by evidence'],
  unresolved: ['还没定', 'Unresolved'],
} as const satisfies Record<string, Pair>;
export const METRICS = {
  elapsed_time: ['结单历时', 'Elapsed time'],
  labor_time: ['人工处理工时', 'Hands-on labor time'],
  case_count: ['工单数量', 'Case count'],
  other: ['其他', 'Other'],
} as const satisfies Record<string, Pair>;

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
    question: (id: StepId) => pick(language, SECTIONS[id].question),
    why: (id: StepId) => pick(language, SECTIONS[id].why),
    example: (id: StepId) => SECTIONS[id].example.map((line) => pick(language, line)),
    label: (pair: Pair) => pick(language, pair),
    starter: (need: (typeof STARTER_NEEDS)[number]) => pick(language, need.request),
  };
}
