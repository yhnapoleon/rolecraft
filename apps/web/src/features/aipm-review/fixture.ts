/** FIXTURE ONLY — fake data shaped like spec §9.2, for component tests and screenshots until
 * L4's `section-review.json` fixture lands. Not evidence that any server path works. */
import type { PreviewRecognition } from '../recognition-native/chain';
import type { Language } from './model';
import type { SectionReview, StepId } from './types';

const ref = (kind: string, id: string, version: number) => ({
  session_id: 'fixture',
  kind,
  object_id: id,
  version,
});

export const FIXTURE_PRD: Record<Language, Record<StepId, string>> = {
  zh: {
    business: '公司做企业差旅与费用管理软件。这次的知识助手给公司内部员工用。',
    stakeholders: '新员工每天会用。Grace 拍板试点资源。',
    need: '新员工反复来问报销和请假怎么办。按平均 429 分钟一单，助手每单能为同事省下约 7 小时人工。这 429 分钟取自 SD-120 的 elapsed_minutes。首批 20 位新同事都会愿意先用助手再找人。下一步请 Chen 抽 10 单看实际处理时间。',
    boundary: '解释报销规则交给助手回答。审批由经理负责。',
    solution: '先用检索加回答的方案。',
    assurance: '用政策变化回归题复测。',
    decision: '有条件试点。',
  },
  en: {
    business:
      'The company sells travel and expense software. This assistant is for internal employees.',
    stakeholders: 'New hires use it daily. Grace approves the pilot resources.',
    need: 'New hires keep asking how expenses and leave work. At an average of 429 minutes a ticket, the assistant saves about 7 staff hours per ticket. The 429 minutes come from elapsed_minutes in SD-120. All 20 new hires in the first group will use the assistant before asking a person. Next, Chen samples 10 tickets for actual handling time.',
    boundary: 'The assistant explains expense rules. Managers approve.',
    solution: 'Start with retrieval and answer.',
    assurance: 'Retest with the policy-change regression case.',
    decision: 'Conditional pilot.',
  },
};

const unit = (index: number, quote: string, label: string, evidence: string | null = null) => ({
  index,
  quote,
  label,
  confidence: 0.9,
  decision: 'decide',
  evidence,
  source: evidence ? { kind: 'material', object_id: 'sd-120', version: 1, title: 'SD-120' } : null,
});

/** Sentences as the recognizer returns them for the whole PRD: section keys included. */
export function fixturePreview(language: Language): PreviewRecognition {
  const zh = language === 'zh';
  const need = FIXTURE_PRD[language].need.split(zh ? /(?<=。)/ : /(?<=\.)\s+/).filter(Boolean);
  return {
    recognizer: 'relation@fixture',
    fallback: false,
    units: [
      unit(
        0,
        `business\n${FIXTURE_PRD[language].business.split(zh ? '。' : '.')[0]}${zh ? '。' : '.'}`,
        'supported',
      ),
      unit(1, `need\n${need[0]}`, 'supported'),
      unit(
        2,
        need[1],
        'contradicted',
        zh
          ? 'elapsed_minutes = 从建单到结单的分钟数'
          : 'elapsed_minutes = minutes from opening to closing a ticket',
      ),
      unit(3, need[2], 'supported'),
      unit(4, need[3], 'insufficient'),
      unit(5, need[4], 'insufficient'),
      // Spans two sections: never guessed into one.
      unit(
        6,
        zh ? '有条件试点。新员工每天会用。' : 'Conditional pilot. New hires use it daily.',
        'insufficient',
      ),
    ],
  };
}

export function fixtureReview(language: Language): SectionReview {
  const zh = language === 'zh';
  const t = (a: string, b: string) => (zh ? a : b);
  return {
    schema_version: 1,
    id: `fixture-review-${language}`,
    session_id: 'fixture',
    step_id: 'need',
    prd_ref: ref('product', 'prd', 4),
    design_ref: ref('aipm_design', 'design', 6),
    as_of: {
      business_seq: 12,
      workspace_revision: 30,
      storage_revision: 41,
    } as SectionReview['as_of'],
    created_at: '2026-10-26T10:58:00+08:00',
    status: 'draft',
    stale: null,
    previous_review_ref: ref('aipm_section_review', 'r3', 1),
    delta: { citations: [0, 2], gaps: [3, 2], wrong: [0, 1] },
    misconceptions: [
      {
        id: 'metric_scope',
        input_ref: ref('product', 'prd', 4),
        step_id: 'need',
        source: 'rule',
        finding: 'violation',
        message: t(
          '把结单时长当成了人工工时（第 2 句）',
          'Ticket elapsed time taken as staff hours (sentence 2)',
        ),
        basis_refs: [
          {
            session_id: 'fixture',
            kind: 'material',
            object_id: 'sd-120',
            version: 1,
            observed_at_seq: 3,
            quote: t(
              'elapsed_minutes = 从建单到结单的分钟数',
              'elapsed_minutes = minutes from opening to closing a ticket',
            ),
          },
        ],
        checked_scope: t(
          '只核对指标的来源字段与单位。',
          'Only the metric’s source field and unit.',
        ),
        next_action: {
          action: 'open_material',
          label: t(
            '同一份字段说明里，有没有记录「处理时长」的字段？',
            'In the same field guide, is any field a handling time?',
          ),
        },
        affects_formal_score: false,
      },
    ],
    coverage: [
      {
        id: 'counter',
        label: t('一个会让我们不做的事实或反证', 'A fact that would stop us, or counter-evidence'),
        check: 'model',
        severity: 'high',
        mark: 'missing',
        pointer: {
          text: t(
            '再看看：INT-03 访谈里新同事怎么找答案',
            'Look again: how new hires find answers in INT-03',
          ),
          refs: [],
        },
        owner: 'business',
        source: 'rule',
      },
      {
        id: 'metric',
        label: t('指标口径：数字的单位和统计范围', 'Metric definition: unit and scope'),
        check: 'rule',
        severity: 'high',
        mark: 'wrong',
        pointer: { text: t('见上一条', 'See above'), refs: [] },
        owner: 'business',
        source: 'rule',
      },
      {
        id: 'willing',
        label: t(
          '首批用户愿不愿意先用助手（第 4 句）',
          'Whether the first users will try the assistant (sentence 4)',
        ),
        check: 'model',
        severity: 'medium',
        mark: 'to_check',
        owner: 'manager',
        source: 'rule',
      },
      {
        id: 'cited',
        label: t(
          '原始证据有出处（2 处引用）· 写了下一步验证办法',
          'Raw evidence is cited (2) · next validation stated',
        ),
        check: 'citation',
        severity: 'medium',
        mark: 'covered',
        owner: 'business',
        source: 'citation',
      },
    ],
    rubric: [
      {
        criterion: 'R1.metrics',
        label: 'NOT_MET',
        source: 'verified_rule',
        explanation: t(
          '指标与验收口径\n来源字段是结单时长，不是处理时长。',
          'Metrics\nThe source field is elapsed time, not handling time.',
        ),
      },
      { criterion: 'R2.support', label: 'INSUFFICIENT', source: 'pending', explanation: '' },
    ],
    mentor_prompts: [
      {
        colleague: 'manager',
        question: t(
          '这个收益能不能写进试点目标？写之前你想先确认什么？',
          'Could this benefit go into the pilot goal? What would you confirm first?',
        ),
        trigger_id: 'metric_scope',
      },
      {
        colleague: 'business',
        question: t(
          '429 分钟里，同事真正在处理这一单的有多少？',
          'Of those 429 minutes, how many is someone actually working the ticket?',
        ),
        trigger_id: 'metric_scope',
      },
      {
        colleague: 'tech',
        question: t(
          '这条假设，评测里哪一题能推翻它？',
          'Which evaluation case could overturn this assumption?',
        ),
        trigger_id: 'counter',
      },
    ],
    sentence_labels: null,
    affects_formal_score: false,
  };
}
