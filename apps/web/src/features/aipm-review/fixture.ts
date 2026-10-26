/** FIXTURE ONLY — fake data for component tests and screenshots: L4's shared synthetic review,
 * plus a PRD text and sentence preview written to match it. Not evidence that any server path
 * works. */
import type { PreviewRecognition } from '../recognition-native/chain';
import type { Language } from './model';
import shared from '../../../../../tests/fixtures/aipm-phase1/section-review.json';
import type { SectionReview, SectionReviewPage, StepId } from './types';

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

/** L4's shared fixture (`tests/fixtures/aipm-phase1/section-review.json`), read as is. */
export function fixtureReview(language: Language): SectionReview {
  return structuredClone(
    shared[language === 'zh' ? 'review_zh' : 'review_en'],
  ) as unknown as SectionReview;
}
export const fixturePage = () => structuredClone(shared.page) as unknown as SectionReviewPage;

/** FIXTURE ONLY — the same review as the model's look runs (revision 1) and after it finished
 * (revision 2), or failed. The model items say where to look again, never the answer. */
export function fixtureModelReview(
  language: Language,
  status: 'not_configured' | 'running' | 'done' | 'failed',
): SectionReview {
  const zh = language === 'zh';
  const t = (a: string, b: string) => (zh ? a : b);
  const review = fixtureReview(language);
  if (status !== 'done')
    return {
      ...review,
      revision: 1,
      model_status: status,
      model_items: [],
      model_reason: status === 'failed' ? t('模型超时', 'The model timed out') : null,
    };
  return {
    ...review,
    revision: 2,
    model_status: 'done',
    model_reason: null,
    model_items: [
      {
        target: 'coverage',
        id: 'need.counterfact',
        label: t('会让我们不做的事实', 'A fact that would make us stop'),
        mark: 'missing',
        note: t(
          '没写出会让试点停下的事实；再看需求访谈里的反对意见。',
          'No fact that would stop the pilot; look again at the objections in the demand interviews.',
        ),
        source: 'model_suggestion',
      },
      {
        target: 'rubric',
        id: 'R2.support',
        label: t('判断的证据支持', 'Evidence supporting judgments'),
        mark: 'missing',
        note: t('只引用了一次访谈，还没有反证。', 'One interview cited; no counter-evidence yet.'),
        source: 'model_suggestion',
      },
    ],
  };
}
