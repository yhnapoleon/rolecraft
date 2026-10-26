/** Section review logic without the DOM: sentences grouped by section, coverage order, staleness,
 * the comparison line and the colleague summary. Nothing here calls a server or a model. */
import type { ChainUnit, PreviewRecognition } from '../recognition-native/chain';
import type { ItemRow } from '../feedback-native/feedback-items';
import type { Colleague } from '../../screens/result/colleagues';
import type { ModelJudgement, ModelStatus } from '../../aipm/types';
import type {
  CoverageItem,
  ReviewColleague,
  ReviewStatus,
  RubricLine,
  SectionReview,
  StepId,
} from './types';

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
    mergedCoverage(review).some((c) => c.mark === 'wrong') ||
    (review.misconceptions ?? []).some((m) => m.finding === 'violation');
  const status = shownStatus(review);
  if (modelPart(review).status === 'running')
    return text(
      language,
      '模型细看中，结果回来后再定档',
      'The model is looking; the status settles when it returns',
    );
  if (status === 'draft' && wrong)
    return text(language, '改掉「有误」后可到「有依据」', 'Fix what is wrong to reach Grounded');
  if (status === 'draft')
    return text(language, '引用一份资料后可到「有依据」', 'Cite a source to reach Grounded');
  if (status === 'based')
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
  const d = shownDelta(review);
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
export const orderCoverage = <T extends CoverageItem>(items: readonly T[]): T[] =>
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
// ---- The model's look (user 10-26: on whenever a model is connected) --------------------

export type { ModelStatus } from '../../aipm/types';
export type ModelPart = {
  status: ModelStatus;
  error: string | null;
  /** Coverage points the model judged, shaped as coverage rows. */
  coverage: CoverageItem[];
  /** Criteria the model judged, shaped as rule lines (MET / PARTIAL / NOT_MET). */
  rubric: RubricLine[];
};
const RUBRIC_LABEL: Record<ModelJudgement['mark'], string | null> = {
  covered: 'MET',
  missing: 'PARTIAL',
  wrong: 'NOT_MET',
  to_check: null,
};
/** The model part of a review (revision 2 when a model is connected): its items split into
 * coverage points and criteria. Only items of a finished look are used. */
export function modelPart(review: SectionReview): ModelPart {
  const status = review.model_status ?? 'not_configured';
  const items = status === 'done' ? (review.model_items ?? []) : [];
  const rules = new Map((review.coverage ?? []).map((c) => [c.id, c]));
  return {
    status,
    error: review.model_reason ?? null,
    coverage: items
      .filter((item) => item.target === 'coverage')
      .map((item) => {
        const rule = rules.get(item.id);
        return {
          id: item.id,
          label: item.label || rule?.label || item.id,
          check: rule?.check ?? 'model',
          severity: rule?.severity ?? 'medium',
          owner: rule?.owner ?? 'manager',
          mark: item.mark,
          pointer: { text: item.note, refs: item.citations ?? [] },
          source: 'model_suggestion' as const,
        };
      }),
    rubric: items.flatMap((item) => {
      const label = item.target === 'rubric' ? RUBRIC_LABEL[item.mark] : null;
      return label
        ? [
            {
              criterion: item.id,
              label,
              source: 'pending' as const,
              explanation: `${item.label}\n${item.note}`,
              citations: item.citations ?? [],
            },
          ]
        : [];
    }),
  };
}
export type ShownCoverage = CoverageItem & { byModel?: boolean };
/** Rule coverage, with the model's finished verdicts in place of the points it judged. */
export function mergedCoverage(review: SectionReview): ShownCoverage[] {
  const judged = new Map(modelPart(review).coverage.map((c) => [c.id, c]));
  const base = review.coverage ?? [];
  const shown: ShownCoverage[] = base.map((c) => {
    const verdict = judged.get(c.id);
    return verdict ? { ...verdict, byModel: true } : c;
  });
  for (const verdict of judged.values())
    if (!base.some((c) => c.id === verdict.id)) shown.push({ ...verdict, byModel: true });
  return shown;
}

/** The status to show. Revision 2 carries the server's status with the model's verdicts
 * counted; while the model is still looking, "Holds up" is never shown early (it may drop). */
export function shownStatus(review: SectionReview): ReviewStatus {
  if (modelPart(review).status === 'running' && review.status === 'solid') return 'based';
  return review.status;
}
/** The comparison's "after" counts again with the model's verdicts (`review.py::counts`). */
export function shownDelta(review: SectionReview): SectionReview['delta'] {
  const d = review.delta;
  if (!d || modelPart(review).status !== 'done') return d ?? null;
  const coverage = mergedCoverage(review);
  return {
    citations: [
      d.citations[0],
      coverage.filter((m) => m.check === 'citation' && m.mark === 'covered').length,
    ],
    gaps: [d.gaps[0], coverage.filter((m) => m.mark === 'missing').length],
    wrong: [
      d.wrong[0],
      coverage.filter((m) => m.mark === 'wrong').length + (review.misconceptions ?? []).length,
    ],
  };
}

/** What a point only a model can judge says while it has no verdict. */
function waitingLine(status: ModelStatus, language: Language) {
  return {
    not_configured: text(language, '未接入模型', 'No model connected'),
    running: text(language, '模型细看中…', 'The model is looking…'),
    failed: text(language, '模型细看没有完成', 'The model look did not finish'),
    done: text(language, '需要同事判断', 'Needs a colleague’s judgement'),
  }[status];
}

export function coverageRow(
  item: ShownCoverage,
  language: Language,
  model: ModelStatus = 'not_configured',
): ItemRow {
  const waits = !item.byModel && item.check === 'model' && item.mark !== 'covered';
  const mark = waits ? 'to_check' : item.mark;
  const pointer = item.pointer?.text
    ? text(language, `再看看：${item.pointer.text}`, `Look again: ${item.pointer.text}`)
    : null;
  const line =
    (waits ? [waitingLine(model, language), pointer].filter(Boolean).join(' · ') : pointer) ??
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
  // Point names with their marks, this colleague's first; two at most so it fits the box.
  // The model's own words go in the separate review summary the learner may attach.
  const ordered = orderCoverage(mergedCoverage(review)).filter((c) => c.mark !== 'covered');
  const points = [
    ...ordered.filter((c) => c.owner === who),
    ...ordered.filter((c) => c.owner !== who),
  ]
    .slice(0, 2)
    .map((c) =>
      text(
        language,
        `${c.label}（${coverageMarkName(c.mark, language)}）`,
        `${c.label} (${coverageMarkName(c.mark, language).toLowerCase()})`,
      ),
    );
  const status = statusName(shownStatus(review), language);
  const ask = ASK_DIRECTION[who][language === 'zh' ? 0 : 1];
  if (language === 'zh') {
    const said = points.length ? `批改标出：${points.join('、')}。` : `批改结果是「${status}」。`;
    return `我在写「${sheet}」第 ${version} 版。${said}${ask}`;
  }
  const said = points.length
    ? `The review marks ${points.join(', ')}.`
    : `The review marks it “${status}”.`;
  return `I’m writing “${sheet}”, version ${version}. ${said} ${ask}`;
}

/** The longer text behind “Attach the review summary”: each finding in its own words, where to
 * look again, and whether a rule or the model said it. The learner decides whether to insert it. */
export function reviewDetailForColleague(
  review: SectionReview,
  options: { language?: Language } = {},
) {
  const language = options.language ?? 'zh';
  const t = (zh: string, en: string) => text(language, zh, en);
  const paren = (words: string) => t(`（${words}）`, ` (${words})`);
  const sep = t('：', ': ');
  const lines = (review.misconceptions ?? []).map((m) => {
    const model = m.source === 'model_suggestion';
    const name = model && m.checked_scope ? `${m.checked_scope}${sep}` : '';
    return `· ${name}${m.message.trim()}${paren(model ? t('模型建议', 'model advice') : t('规则判定', 'rule check'))}`;
  });
  for (const c of orderCoverage(mergedCoverage(review)))
    if (c.mark !== 'covered' && c.pointer?.text)
      lines.push(`· ${c.label}${paren(coverageMarkName(c.mark, language))}${sep}${c.pointer.text}`);
  return lines.join('\n');
}

/** The closing question asks each colleague, from their own remit, where to look first — never
 * for the fix, which the reply check would rightly stop (L4's audit on 18810). */
const ASK_DIRECTION: Record<ReviewColleague, [string, string]> = {
  manager: [
    '从目标和资源看，你觉得我最该先核对哪一处？',
    'Looking at goals and resources, which part do you think I should check first?',
  ],
  business: [
    '从业务口径看，你觉得我最该先核对哪一处？',
    'From the business side, which part do you think I should check first?',
  ],
  tech: [
    '从系统和测试证据看，你觉得我最该先核对哪一处？',
    'From the system and test evidence, which part do you think I should check first?',
  ],
};

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

// ---- What each colleague looks at on a sheet, when no preset question fired -------------

const DEFAULT_ANGLE: Record<StepId, Record<ReviewColleague, [string, string]>> = {
  business: {
    manager: ['这次试点要达成什么目标', 'What this pilot is meant to achieve'],
    business: ['助手到底给谁用', 'Who the assistant is really for'],
    tech: ['现有系统能接住什么', 'What the current systems can support'],
  },
  stakeholders: {
    manager: ['谁拍板试点资源', 'Who approves the pilot resources'],
    business: ['谁每天会用、谁会多干活', 'Who uses it daily, and who gets more work'],
    tech: ['出了错谁来接', 'Who picks it up when it goes wrong'],
  },
  need: {
    manager: ['这个收益值不值得做', 'Whether the benefit is worth it'],
    business: ['数字的口径和来源', 'How the numbers are defined and sourced'],
    tech: ['哪条证据能推翻这个假设', 'Which evidence could overturn the assumption'],
  },
  boundary: {
    manager: ['谁有最后批准权', 'Who has the final approval'],
    business: ['哪些请求必须人来处理', 'Which requests a person must handle'],
    tech: ['助手现在做得到什么', 'What the assistant can do today'],
  },
  solution: {
    manager: ['资源和取舍', 'Resources and trade-offs'],
    business: ['首批用户能不能用起来', 'Whether the first users can adopt it'],
    tech: ['方案和实际配置差在哪', 'Where the plan and the real settings differ'],
  },
  assurance: {
    manager: ['上线后看什么信号', 'Which signals to watch after launch'],
    business: ['出错后业务谁来接', 'Who in the business picks up a failure'],
    tech: ['哪一题能推翻这个方案', 'Which case could overturn the plan'],
  },
  decision: {
    manager: ['在什么条件下承诺', 'Under which conditions to commit'],
    business: ['还没解决的业务问题', 'Business questions still open'],
    tech: ['复测和回退是否到位', 'Whether retests and rollback are in place'],
  },
};
/** The angle a colleague would take on this sheet, for the column with no preset question. */
export const defaultAngle = (step: StepId, who: ReviewColleague | Colleague, language: Language) =>
  DEFAULT_ANGLE[step][who === 'technical' ? 'tech' : who][language === 'zh' ? 0 : 1];

// ---- What was written, as blocks ---------------------------------------------------------

export type WrittenBlock =
  | { type: 'h'; text: string }
  | { type: 'quote'; text: string; source: string | null }
  | { type: 'p'; text: string };
/** The sheet's saved text read back as blocks: `### ` headings, `> ` quotes (with a closing
 * `> — source` line) and the learner's own paragraphs, as L2's worksheet writes them. */
export function writtenBlocks(written: string): WrittenBlock[] {
  const blocks: WrittenBlock[] = [];
  for (const chunk of written.split(/\n{2,}/)) {
    const body = chunk.trim();
    if (!body) continue;
    const lines = body.split('\n');
    if (body.startsWith('#')) blocks.push({ type: 'h', text: body.replace(/^#+\s*/, '') });
    else if (lines.every((line) => line.startsWith('>'))) {
      const clean = lines.map((line) => line.replace(/^>\s?/, ''));
      const last = clean[clean.length - 1];
      const cited = /^[—-]\s*/.test(last) && clean.length > 1;
      blocks.push({
        type: 'quote',
        text: (cited ? clean.slice(0, -1) : clean).join('\n'),
        source: cited ? last.replace(/^[—-]\s*/, '') : null,
      });
    } else blocks.push({ type: 'p', text: body });
  }
  return blocks;
}
/** Marks the recognizer added to a sentence taken from a heading or quote line. */
const MARKUP = /^(?:#+\s*|>\s*(?:[—-]\s*)?)/;
/** Only the learner's own sentences: sentences from headings and quotes are dropped. */
export function ownSentences<T extends { quote: string }>(
  units: readonly T[],
  blocks: readonly WrittenBlock[],
) {
  const quoted = blocks
    .filter((b) => b.type !== 'p')
    .map((b) => squash(b.type === 'quote' ? `${b.text}${b.source ?? ''}` : b.text));
  const own = blocks.filter((b) => b.type === 'p').map((b) => squash(b.text));
  return units.filter((unit) => {
    const q = squash(unit.quote.replace(MARKUP, ''));
    if (!q) return false;
    if (unit.quote.trim().match(/^(#|>)/)) return false;
    return !quoted.some((t) => t.includes(q)) || own.some((t) => t.includes(q));
  });
}
