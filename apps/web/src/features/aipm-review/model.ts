/** Section review logic without the DOM: sentences grouped by section, coverage order, staleness,
 * the comparison line and the colleague summary. Nothing here calls a server or a model. */
import type { ChainUnit, PreviewRecognition } from '../recognition-native/chain';
import type { ItemRow } from '../feedback-native/feedback-items';
import type { Colleague } from '../../screens/result/colleagues';
import type { CoverageItem, ReviewColleague, ReviewStatus, SectionReview, StepId } from './types';

export type Language = 'zh' | 'en';
export const text = (language: Language, zh: string, en: string) => (language === 'zh' ? zh : en);

export const STEPS: readonly StepId[] = [
  'business',
  'stakeholders',
  'need',
  'boundary',
  'solution',
  'assurance',
  'decision',
];
const STEP_NAMES: Record<StepId, [string, string]> = {
  business: ['看懂业务', 'Understand the business'],
  stakeholders: ['用户与相关方', 'Users and stakeholders'],
  need: ['验证真需求', 'Validate the need'],
  boundary: ['划定 AI 边界', 'Set AI boundaries'],
  solution: ['系统方案与市场做法', 'Solution and reference patterns'],
  assurance: ['评测、监控与回退', 'Evaluation, monitoring and rollback'],
  decision: ['上线决策', 'Launch decision'],
};
const CIRCLED = ['①', '②', '③', '④', '⑤', '⑥', '⑦'];
export const stepName = (step: StepId, language: Language) =>
  STEP_NAMES[step][language === 'zh' ? 0 : 1];
/** "③ 验证真需求" */
export const sheetName = (step: StepId, language: Language) =>
  `${CIRCLED[STEPS.indexOf(step)]} ${stepName(step, language)}`;

/** The review's colleague key is `tech`; the result page's is `technical`. */
export const colleagueKey = (who: ReviewColleague): Colleague =>
  who === 'tech' ? 'technical' : who;

// ---- Sentences into sections -------------------------------------------------------------

const squash = (value: string) => value.replace(/\s+/g, '').trim();
/** Section texts reach the recognizer as "key\ntext"; a sentence may start with its key. */
const KEY_PREFIX = new RegExp(`^(?:${STEPS.join('|')})\\s+`);

export type SentenceGroups = {
  bySection: Partial<Record<StepId, ChainUnit[]>>;
  /** Sentences that fall in no section, or in more than one, shown as they are. */
  unassigned: ChainUnit[];
};

/** Places each recognized sentence in the one section whose text contains it. A sentence found in
 * two sections, or across a boundary, is not guessed: it goes to "not in a section". */
export function groupSentences(
  units: readonly ChainUnit[],
  sections: Partial<Record<StepId, string>>,
): SentenceGroups {
  const texts = STEPS.map((step) => [step, squash(sections[step] ?? '')] as const).filter(
    ([, t]) => t,
  );
  const groups: SentenceGroups = { bySection: {}, unassigned: [] };
  for (const unit of units) {
    const quote = squash(unit.quote.replace(KEY_PREFIX, ''));
    // A bare section key is the heading the assembler added, not something the learner wrote.
    if (!quote || (STEPS as readonly string[]).includes(unit.quote.trim())) continue;
    const hits = texts.filter(([, body]) => body.includes(quote));
    if (hits.length !== 1) {
      groups.unassigned.push(unit);
      continue;
    }
    const step = hits[0][0];
    groups.bySection[step] = [...(groups.bySection[step] ?? []), unit];
  }
  return groups;
}

/** The preview body narrowed to one section's sentences, numbered from 1 as the learner sees them. */
export function sectionPreview(
  preview: PreviewRecognition,
  units: readonly ChainUnit[],
): PreviewRecognition {
  const counts = { supported: 0, contradicted: 0, insufficient: 0, deferred: 0 };
  for (const unit of units) {
    if (unit.decision === 'defer') counts.deferred++;
    else if (unit.label in counts) counts[unit.label as keyof typeof counts]++;
  }
  // The assembler's section key is not part of what the learner wrote; drop it from the quote.
  return {
    ...preview,
    counts,
    units: units.map((unit, index) => ({
      ...unit,
      index,
      quote: unit.quote.replace(KEY_PREFIX, ''),
    })),
  };
}

// ---- Status, comparison, staleness ------------------------------------------------------

export const STATUSES: readonly ReviewStatus[] = ['draft', 'based', 'solid'];
export function statusName(status: ReviewStatus, language: Language) {
  return {
    draft: text(language, '草稿', 'Draft'),
    based: text(language, '有依据', 'Grounded'),
    solid: text(language, '站得住', 'Holds up'),
  }[status];
}
/** What would move the review one step up, from its own marks (spec §6.3). */
export function nextStatusHint(review: SectionReview, language: Language) {
  const wrong =
    (review.coverage ?? []).some((c) => c.mark === 'wrong') ||
    (review.misconceptions ?? []).some((m) => m.finding === 'violation');
  if (review.status === 'draft' && wrong)
    return text(language, '改掉「有误」后可到「有依据」', 'Fix what is wrong to reach Grounded');
  if (review.status === 'draft')
    return text(language, '引用一份资料后可到「有依据」', 'Cite a source to reach Grounded');
  if (review.status === 'based')
    return text(
      language,
      '补上缺的要点后可到「站得住」',
      'Fill the missing points to reach Holds up',
    );
  return text(language, '在可核对的范围内站得住', 'Holds up within what can be checked');
}

export function deltaLine(
  review: SectionReview,
  language: Language,
  previousVersion?: number | null,
) {
  const d = review.delta;
  if (!d) return null;
  const head =
    previousVersion != null
      ? text(
          language,
          `和第 ${previousVersion} 版比：`,
          `Compared with version ${previousVersion}: `,
        )
      : text(language, '和上一次批改比：', 'Compared with the last review: ');
  const parts = [
    text(
      language,
      `引用 ${d.citations[0]} → ${d.citations[1]}`,
      `citations ${d.citations[0]} → ${d.citations[1]}`,
    ),
    text(language, `缺口 ${d.gaps[0]} → ${d.gaps[1]}`, `gaps ${d.gaps[0]} → ${d.gaps[1]}`),
    text(language, `有误 ${d.wrong[0]} → ${d.wrong[1]}`, `wrong ${d.wrong[0]} → ${d.wrong[1]}`),
  ];
  return head + parts.join(' · ');
}

/** The server's staleness, or the learner's own edit since this version. */
export function staleNote(
  review: SectionReview,
  language: Language,
  currentPrdVersion?: number | null,
  /** The progress sheet's `edited_since_review`. */
  edited = false,
) {
  const v = review.prd_ref.version;
  if (review.stale?.reason === 'source_changed' || review.stale?.reason === 'policy_changed')
    return {
      kind: 'recheck' as const,
      text: text(
        language,
        `这份批改在资料或政策更新之前（${review.stale.detail}），需要重新核对。`,
        `This review predates a source or policy update (${review.stale.detail}); check it again.`,
      ),
    };
  if (
    edited ||
    review.stale?.reason === 'edited' ||
    (currentPrdVersion != null && currentPrdVersion !== v)
  )
    return {
      kind: 'edited' as const,
      text: text(
        language,
        `这份批改对应第 ${v} 版，你已改动。`,
        `This review is for version ${v}; you have edited since.`,
      ),
    };
  return null;
}

// ---- Coverage rows ----------------------------------------------------------------------

const MARK_ORDER: Record<CoverageItem['mark'], number> = {
  wrong: 0,
  missing: 1,
  to_check: 2,
  covered: 3,
};
const SEVERITY_ORDER: Record<CoverageItem['severity'], number> = { high: 0, medium: 1, low: 2 };
/** Wrong, missing, to check, covered; within each, high severity first. */
export const orderCoverage = (items: readonly CoverageItem[]) =>
  [...items].sort(
    (a, b) =>
      MARK_ORDER[a.mark] - MARK_ORDER[b.mark] ||
      SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity],
  );

export function coverageMarkName(mark: CoverageItem['mark'], language: Language) {
  return {
    wrong: text(language, '有误', 'Wrong'),
    missing: text(language, '缺了', 'Missing'),
    to_check: text(language, '待核对', 'To check'),
    covered: text(language, '覆盖了', 'Covered'),
  }[mark];
}

/** A coverage point as the result page's row: the same marks, tones and disclosure. A `model`
 * point is always "to check" in this release (no model look), with a way to ask a colleague. */
export function coverageRow(item: CoverageItem, language: Language): ItemRow {
  const mark = item.check === 'model' && item.mark !== 'covered' ? 'to_check' : item.mark;
  const line =
    (item.pointer?.text
      ? text(language, `再看看：${item.pointer.text}`, `Look again: ${item.pointer.text}`)
      : null) ??
    (mark === 'to_check'
      ? text(
          language,
          '需要同事判断，或交付后由正式反馈判断。',
          'Needs a colleague’s judgement, or the formal feedback after delivery.',
        )
      : '');
  return {
    criterion: item.id,
    name: item.label,
    mark: mark === 'covered' ? 'met' : mark === 'to_check' ? 'unknown' : 'unmet',
    tone: mark === 'wrong' ? 'bad' : mark === 'missing' ? 'warn' : undefined,
    // The mark is shown as its own word pill, so the line says only where to look.
    line,
    found: (item.pointer?.refs ?? []).map((ref) => ref.quote).filter((q): q is string => !!q) ?? [],
    // The view shows these rows only; the formal item is not consulted.
    item: { criterion: item.id, label: '', explanation: '' } as unknown as ItemRow['item'],
  };
}

// ---- What to tell a colleague -----------------------------------------------------------

/** The text placed in the colleague's message box: which sheet and version, and the review's
 * most important findings as questions to discuss, never as answers. Visible and editable. */
export function reviewSummaryForColleague(
  review: SectionReview,
  colleague: ReviewColleague | Colleague,
  options: { language?: Language } = {},
) {
  const language = options.language ?? 'zh';
  const who: ReviewColleague = colleague === 'technical' ? 'tech' : colleague;
  const sheet = stepName(review.step_id, language);
  const version = review.prd_ref.version;
  const points: string[] = (review.misconceptions ?? [])
    .slice(0, 1)
    .map((m) => m.message.replace(/[。.！!]+$/, ''));
  const ordered = orderCoverage(review.coverage ?? []).filter((c) => c.mark !== 'covered');
  // This colleague's own points first, then the rest; at most two lines in all.
  for (const item of [
    ...ordered.filter((c) => c.owner === who),
    ...ordered.filter((c) => c.owner !== who),
  ]) {
    if (points.length >= 2) break;
    points.push(
      `${coverageMarkName(item.mark, language)}${text(language, '：', ': ')}${item.label}`,
    );
  }
  const status = statusName(review.status, language);
  if (language === 'zh') {
    const said = points.length ? `批改说：${points.join('；')}。` : `批改结果是「${status}」。`;
    return `我在写「${sheet}」第 ${version} 版。${said}你怎么看？`;
  }
  const said = points.length
    ? `The review says: ${points.join('; ')}.`
    : `The review marks it “${status}”.`;
  return `I’m writing “${sheet}”, version ${version}. ${said} What do you think?`;
}

// ---- Result page: back to a sheet -------------------------------------------------------

/** Which sheet each formal criterion is reviewed on (spec §5.2); ⑦ reviews all of them. */
const CRITERION_SHEET: Readonly<Record<string, StepId>> = {
  'R1.target': 'business',
  'R2.unknowns': 'business',
  'R6.operations': 'assurance',
  'R1.metrics': 'need',
  'R2.support': 'need',
  'R3.capacity': 'solution',
  'R3.resources': 'solution',
  'R6.alternatives': 'solution',
  'R6.consistency': 'solution',
  'R4.functional_tests': 'assurance',
  'R4.staleness_test': 'assurance',
  'R2.failure_analysis': 'assurance',
  'R5.impact': 'assurance',
  'R5.adjustment': 'assurance',
};
export const sheetOfCriterion = (criterion: string): StepId | null =>
  CRITERION_SHEET[criterion] ?? null;

/** The material a pointer or finding names, to open beside the sheet. */
export const materialOf = (refs?: readonly { kind: string; object_id: string }[] | null) =>
  refs?.find((ref) => ref.kind === 'material')?.object_id ?? null;
