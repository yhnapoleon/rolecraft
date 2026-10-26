/** The seven sheets as the compass and the work stack show them: state, words, order of
 * importance. All from the server's guide and progress; nothing here decides a state. */
import type { StackItem } from '../../shell/work-stack/model';
import type { GuideView, Language, ProgressView, Segment, SheetStatus, StepId } from './model';

const WORDS = {
  zh: {
    status: {
      not_started: '未开始',
      draft: '草稿',
      based: '有依据',
      solid: '站得住（按可核对范围）',
      recheck: '需重新核对',
    },
    segment: { clarify: '弄清问题', design: '设计方案', verify: '验证与决定' },
    agent: '你的 Agent 交来草稿，待你确认',
    agentShort: 'Agent 草稿待确认',
    missing: '还差：',
    missingLong: '批改单里还有要补的要点',
    seeReview: (label: string) => `先看「${label}」的批改 ›`,
    short: {
      business: '看懂业务',
      stakeholders: '相关方',
      need: '真需求',
      boundary: 'AI 边界',
      solution: '方案',
      assurance: '评测与回退',
      decision: '上线决策',
    },
    pinned: '已固定 · Esc 收起',
    title: '我的工作纸',
    sheets: (n: number) => `试点 PRD · ${n} 张纸`,
    openPrd: '打开整份 PRD',
    newFree: '新建自由纸',
    recheckLine: (n: number) => `${n} 张需重新核对`,
    agentLine: (n: number) => `${n} 份 Agent 草稿待确认`,
    basedLine: (k: number, n: number) => `${k}/${n} 有依据`,
    aria: (n: number, k: number, r: number, d: number) =>
      [
        `我的工作纸，${n} 张`,
        `${k} 张有依据`,
        r ? `${r} 张需重新核对` : '',
        d ? `${d} 份 Agent 草稿待确认` : '',
      ]
        .filter(Boolean)
        .join('，'),
    capsule: (k: number, n: number) => `工作纸 ${k}/${n}`,
    suggested: '建议',
    close: '收起',
    hint: '你的工作纸在这里',
    next: '建议下一步',
  },
  en: {
    status: {
      not_started: 'Not started',
      draft: 'Draft',
      based: 'Supported',
      solid: 'Holds up (within what can be checked)',
      recheck: 'Recheck',
    },
    segment: {
      clarify: 'Clarify the problem',
      design: 'Design the solution',
      verify: 'Verify and decide',
    },
    agent: 'Your agent sent a draft for you to review',
    agentShort: 'agent draft to review',
    missing: 'Still missing: ',
    missingLong: 'The review lists points to fill in',
    seeReview: (label: string) => `See the review of “${label}” ›`,
    short: {
      business: 'Business',
      stakeholders: 'Stakeholders',
      need: 'Real need',
      boundary: 'AI boundary',
      solution: 'Solution',
      assurance: 'Evals & rollback',
      decision: 'Launch call',
    },
    pinned: 'Pinned · Esc to close',
    title: 'My sheets',
    sheets: (n: number) => `Pilot PRD · ${n} sheets`,
    openPrd: 'Open the whole PRD',
    newFree: 'New free sheet',
    recheckLine: (n: number) => `${n} to recheck`,
    agentLine: (n: number) => `${n} agent draft${n > 1 ? 's' : ''} to review`,
    basedLine: (k: number, n: number) => `${k}/${n} supported`,
    aria: (n: number, k: number, r: number, d: number) =>
      [
        `My sheets, ${n} sheets`,
        `${k} supported`,
        r ? `${r} to recheck` : '',
        d ? `${d} agent draft${d > 1 ? 's' : ''} to review` : '',
      ]
        .filter(Boolean)
        .join(', '),
    capsule: (k: number, n: number) => `Sheets ${k}/${n}`,
    suggested: 'Suggested',
    close: 'Close',
    hint: 'Your sheets are here',
    next: 'Suggested next',
  },
} as const;
export const sheetWords = (language: Language) => WORDS[language];
/** A review's open point reads as a phrase only when the server gives a short label; a longer
 * one is the model's own sentence and stays on the review. */
const shortGap = (gap?: string) => !!gap && [...gap].length <= 16;
const ORDER = ['①', '②', '③', '④', '⑤', '⑥', '⑦'];
export const orderGlyph = (n: number) => ORDER[n - 1] ?? '';

export type SheetRow = {
  id: StepId;
  order: number;
  segment: Segment;
  icon: string;
  label: string;
  goal: string;
  status: SheetStatus;
  statusText: string;
  recheckReason?: string;
  gapHint?: string;
  agentDraft: boolean;
  suggested: boolean;
};

export function sheetRows(guide: GuideView, progress: ProgressView): SheetRow[] {
  const w = sheetWords(guide.language);
  return guide.steps.map((g, i) => {
    const sheet = progress.steps[i].sheet;
    const base = w.status[sheet.status];
    const statusText = sheet.agentDraft
      ? sheet.status === 'not_started'
        ? w.agent
        : `${base} · ${w.agentShort}`
      : base;
    return {
      id: g.id,
      order: g.order,
      segment: g.segment,
      icon: g.icon,
      label: g.label,
      goal: g.goal,
      status: sheet.status,
      statusText,
      ...(sheet.recheckReason ? { recheckReason: sheet.recheckReason } : {}),
      ...(sheet.gapHint ? { gapHint: sheet.gapHint } : {}),
      agentDraft: sheet.agentDraft,
      suggested: progress.suggested === g.id,
    };
  });
}

export function stackItems(rows: SheetRow[], language: Language): StackItem[] {
  const w = sheetWords(language);
  return rows.map((r) => ({
    id: r.id,
    order: r.order,
    segment: r.segment,
    icon: r.icon,
    name: r.label,
    short: w.short[r.id] ?? r.label,
    purpose: r.goal,
    status: r.status,
    statusText: r.statusText,
    ...(r.recheckReason ? { recheckReason: r.recheckReason } : {}),
    ...(r.gapHint
      ? { gapHint: shortGap(r.gapHint) ? `${w.missing}${r.gapHint}` : w.missingLong }
      : {}),
    agentDraft: r.agentDraft,
    suggested: r.suggested,
  }));
}

/** The pile's one line and its spoken label. */
export function stackSummary(rows: SheetRow[], language: Language) {
  const w = sheetWords(language);
  const n = rows.length;
  const held = rows.filter((r) => r.status === 'based' || r.status === 'solid').length;
  const recheck = rows.filter((r) => r.status === 'recheck').length;
  const drafts = rows.filter((r) => r.agentDraft).length;
  const status = recheck
    ? w.recheckLine(recheck)
    : drafts
      ? w.agentLine(drafts)
      : w.basedLine(held, n);
  return {
    status,
    aria: w.aria(n, held, recheck, drafts),
    // The capsule's only number besides the count is the amber badge for what waits.
    capsule: w.capsule(held, n),
  };
}

/** "Suggested next": the server's suggested step, with its most serious open point. */
export function suggestionLine(rows: SheetRow[], progress: ProgressView, language: Language) {
  const row = rows.find((r) => r.suggested);
  if (!row) return null;
  const step = progress.steps.find((s) => s.id === row.id);
  const q = language === 'en' ? ['“', '”'] : ['「', '」'];
  if (row.gapHint && !shortGap(row.gapHint))
    return { step: row.id, text: sheetWords(language).seeReview(row.label), review: true };
  const detail = row.gapHint
    ? `${language === 'en' ? 'still missing ' : '还缺'}${row.gapHint}`
    : (step?.nextAction ?? row.goal);
  return { step: row.id, text: `${q[0]}${row.label}${q[1]} ${detail}` };
}
