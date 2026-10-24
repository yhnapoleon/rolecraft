/** The results cover at the top of the feedback page: what this delivery did. The decision as
 * a stamp with its time and attachments; what holds up by the rules (green); what is not known
 * yet and why, in plain words (grey); what is still unmet and the next steps; and from the
 * second delivery on, only the items that changed since the previous one. It reads the stored
 * feedback and submission records as they are and never totals them into one score. */
import { feedbackText, type FeedbackLanguage } from './localization';
import { feedbackClass, ruleItems } from './short-summary';
import { criterionLabels } from './criteria';
import { decisionName } from './decision-cards';
import { attachmentLine, attachmentText, deliveryStamp, stampTime } from './delivery';
import type { FeedbackNativeState, Report } from './index';
import type { ObjectRef } from '../workspace/contract-types';
import './result-cover.css';

type Item = Report['items'][number];
export type CoverMark = 'met' | 'unmet' | 'unknown' | 'na';
export type CoverTone = 'bad' | 'warn' | 'ink';
export interface CoverRow {
  criterion: string;
  name: string;
  mark: CoverMark;
  /** Why it is not known yet, in plain words (unknown rows only). */
  reason?: string;
  /** Unmet rows: red for a limit exceeded, amber for retesting after a change, else ink. */
  tone?: CoverTone;
}
export interface CoverChange {
  criterion: string;
  name: string;
  from: CoverMark;
  to: CoverMark;
}
export interface CoverView {
  decision: string;
  /** "第 2 次交付" / "Delivery 2", when the timeline numbers it. */
  delivery?: number;
  when: string;
  attachments: {
    ref: ObjectRef;
    line: string;
    product: { title: string; version: number; purpose?: string };
  }[];
  /** No feedback for this delivery yet. */
  waiting: boolean;
  failed: boolean;
  met: CoverRow[];
  unknown: CoverRow[];
  unmet: CoverRow[];
  /** From the second delivery on: the previous delivery's number and the rows that changed.
   * Null on a first delivery or when the previous delivery has no feedback to compare. */
  compare: { previous?: number; changes: CoverChange[] } | null;
}

const LIMITS = new Set(['R3.capacity', 'R3.resources']);
const CHANGES = new Set(['R4.staleness_test', 'R5.impact', 'R5.adjustment']);

/** One criterion's place on the cover, with the plain reason when it is not known yet. */
export function coverMark(
  item: Item,
  semantic: FeedbackNativeState['semanticStatus'],
  language: FeedbackLanguage,
): { mark: CoverMark; reason?: string } {
  const T = (zh: string, en: string) => feedbackText(language, zh, en);
  const kind = feedbackClass(item);
  if (kind === 'notApplicable') return { mark: 'na' };
  if (kind === 'undetermined')
    return { mark: 'unknown', reason: T('还不确定这项是否适用', 'Not yet known whether it applies') };
  if (kind === 'verified') {
    const bound = item.rule_bound ?? { lower: item.label, upper: item.label };
    if (bound.lower === bound.upper && bound.lower === 'MET') return { mark: 'met' };
    if (bound.lower === bound.upper && bound.lower === 'NOT_MET') return { mark: 'unmet' };
    return {
      mark: 'unknown',
      reason: T(
        '规则只核实到一个范围，具体判断还要核验',
        'The rules narrow it to a range; the exact finding still needs checking',
      ),
    };
  }
  if (item.source === 'verified_rule' && item.label === 'INSUFFICIENT')
    return {
      mark: 'unknown',
      reason: T('材料里没有找到依据', 'No supporting evidence was found in the materials'),
    };
  if (item.source === 'model_advice')
    return {
      mark: 'unknown',
      reason: T('模型给了建议，仍待核验', 'The model gave advice; it still needs checking'),
    };
  if (semantic === 'waiting_for_model')
    return {
      mark: 'unknown',
      reason: T('需要模型核验，暂未接入', 'Needs model verification, not connected yet'),
    };
  if (semantic === 'failed')
    return {
      mark: 'unknown',
      reason: T('模型核验这次没有完成', 'Model verification did not complete this time'),
    };
  return { mark: 'unknown', reason: T('等待核验', 'Awaiting verification') };
}

const reportFor = (state: FeedbackNativeState, submission: ObjectRef | undefined) =>
  submission
    ? state.reports.find(
        (r) =>
          r.subject.kind === 'submission' &&
          r.subject.object_id === submission.object_id &&
          r.subject.version === submission.version,
      )
    : undefined;

function rows(report: Report, state: FeedbackNativeState, language: FeedbackLanguage) {
  const names = criterionLabels(language);
  const semantic = report.semantic_status ?? state.semanticStatus;
  return ruleItems(report).map((item): CoverRow => {
    const { mark, reason } = coverMark(item, semantic, language);
    return {
      criterion: item.criterion,
      name: names[item.criterion] ?? feedbackText(language, '具体反馈项', 'Feedback criterion'),
      mark,
      ...(reason ? { reason } : {}),
      ...(mark === 'unmet'
        ? {
            tone: LIMITS.has(item.criterion)
              ? ('bad' as const)
              : CHANGES.has(item.criterion)
                ? ('warn' as const)
                : ('ink' as const),
          }
        : {}),
    };
  });
}

/** The cover for the latest delivery, or null before anything was delivered. */
export function coverView(state: FeedbackNativeState, language: FeedbackLanguage): CoverView | null {
  const latest = state.submission;
  if (!latest) return null;
  const deliveries = state.references?.deliveries ?? {};
  const number = (ref: ObjectRef | undefined) =>
    ref && Number.isFinite(deliveries[ref.object_id]) ? deliveries[ref.object_id] : undefined;
  const products = state.products ?? [];
  const attachments = latest.products.map((ref) => {
    const product = products.find(
      (p) => p.product_id === ref.object_id && p.version === ref.version,
    );
    const title =
      product?.title ?? state.references?.products?.[`${ref.object_id}:${ref.version}`] ?? '';
    const shown = { title, version: ref.version, purpose: product?.purpose };
    return { ref, line: attachmentLine(shown, language), product: shown };
  });
  const report = reportFor(state, latest.ref);
  const mine = report ? rows(report, state, language) : [];
  // The delivery just before this one, by the timeline's numbering, else the listed order.
  const listed = state.submissions ?? [];
  const at = listed.findIndex((s) => s.ref.object_id === latest.ref.object_id);
  const ordered = [...listed].sort(
    (a, b) => (number(a.ref) ?? listed.indexOf(a)) - (number(b.ref) ?? listed.indexOf(b)),
  );
  const index = ordered.findIndex((s) => s.ref.object_id === latest.ref.object_id);
  const previous = index > 0 ? ordered[index - 1] : at > 0 ? listed[at - 1] : undefined;
  const before = previous ? reportFor(state, previous.ref) : undefined;
  let compare: CoverView['compare'] = null;
  if (report && before) {
    const then = new Map(rows(before, state, language).map((row) => [row.criterion, row]));
    const changes: CoverChange[] = [];
    for (const row of mine) {
      const old = then.get(row.criterion);
      const from = old?.mark ?? 'na';
      if (from !== row.mark)
        changes.push({ criterion: row.criterion, name: row.name, from, to: row.mark });
      then.delete(row.criterion);
    }
    for (const old of then.values())
      if (old.mark !== 'na')
        changes.push({ criterion: old.criterion, name: old.name, from: old.mark, to: 'na' });
    compare = { previous: number(previous?.ref), changes };
  }
  return {
    decision: decisionName(latest.decision, language),
    delivery: number(latest.ref),
    when: stampTime(state.submittedAt?.[latest.ref.object_id], language),
    attachments,
    waiting: !report,
    failed: !report && !!state.failedFeedback,
    met: mine.filter((row) => row.mark === 'met'),
    unknown: mine.filter((row) => row.mark === 'unknown'),
    unmet: mine.filter((row) => row.mark === 'unmet'),
    compare,
  };
}

const GLYPH: Record<CoverMark, string> = { met: '✓', unmet: '✗', unknown: '?', na: '—' };

export interface CoverActions {
  openReference(ref: ObjectRef): void;
  /** Next steps, each to an existing control; absent when it cannot be taken now. */
  supplement?: () => void;
  revise?: () => void;
  backToBoard?: boolean;
  practise?: boolean;
}

/** "已用 23 秒" / "23 s so far": a count of real seconds, never a percentage. */
export function elapsedWords(seconds: number, language: FeedbackLanguage): string {
  const s = Math.max(0, Math.floor(seconds));
  if (language === 'en') return s < 60 ? `${s} s so far` : `${Math.floor(s / 60)} min ${s % 60} s so far`;
  return s < 60 ? `已用 ${s} 秒` : `已用 ${Math.floor(s / 60)} 分 ${s % 60} 秒`;
}

/** The stage the server reports for the feedback job; nothing is shown for a stage it does not
 * report. */
export function phaseWords(
  phase: FeedbackNativeState['feedbackPhase'],
  language: FeedbackLanguage,
): string {
  const T = (zh: string, en: string) => feedbackText(language, zh, en);
  return phase === 'queued' ? T('排队', 'Queued') : phase === 'running' ? T('生成', 'Writing') : '';
}

export function renderCover(
  doc: Document,
  view: CoverView,
  language: FeedbackLanguage,
  actions: CoverActions,
  wait: { phase?: FeedbackNativeState['feedbackPhase']; seconds?: number } = {},
): HTMLElement {
  const T = (zh: string, en: string) => feedbackText(language, zh, en);
  const el = <K extends keyof HTMLElementTagNameMap>(tag: K, text = '', cls = '') => {
    const node = doc.createElement(tag);
    node.textContent = text;
    if (cls) node.className = cls;
    return node;
  };
  const button = (text: string, run: (() => void) | null, cls = 'btn small', action = '') => {
    const node = el('button', text, cls);
    node.type = 'button';
    if (action) node.dataset.action = action;
    if (run) node.addEventListener('click', run);
    return node;
  };
  const cover = el('section', '', 'result-cover');
  cover.dataset.resultCover = '';
  cover.setAttribute('aria-label', T('这次交付', 'This delivery'));

  // 1. Your decision: the stamp, when and what was attached.
  const head = el('div', '', 'result-cover__head');
  head.append(
    deliveryStamp(doc, {
      decision: view.decision,
      when: view.when || undefined,
      language,
    }),
  );
  const facts = el('div', '', 'result-cover__facts');
  facts.append(
    el(
      'h2',
      Number.isFinite(view.delivery)
        ? T(`第 ${view.delivery} 次交付`, `Delivery ${view.delivery}`)
        : T('这次交付', 'This delivery'),
      'result-cover__title',
    ),
  );
  if (view.attachments.length) {
    const list = el('ul', '', 'result-cover__attachments');
    list.setAttribute('aria-label', T('附上的作品', 'Attached work'));
    for (const item of view.attachments) {
      const row = el('li');
      const open = button('', () => actions.openReference(item.ref), 'result-cover__slip');
      open.append(attachmentText(doc, item.product, language));
      open.dataset.referenceKind = item.ref.kind;
      open.setAttribute('aria-label', T('打开附件：', 'Open attachment: ') + item.line);
      row.append(open);
      list.append(row);
    }
    facts.append(list);
  }
  head.append(facts);
  cover.append(head);

  if (view.waiting) {
    // The wait, told by what the server reports: its stage and the real seconds so far.
    const waitBox = el('div', '', 'result-cover__wait');
    waitBox.dataset.feedbackWait = wait.phase ?? '';
    const line = el('p', '', 'result-cover__wait-line');
    const dot = el('span', '', 'result-cover__pulse');
    dot.setAttribute('aria-hidden', 'true');
    line.append(
      dot,
      el(
        'span',
        view.failed
          ? T('反馈这次没有生成，交付仍保留。', 'The feedback did not complete; the delivery is kept.')
          : wait.phase === 'queued'
            ? T('反馈在排队', 'Your feedback is queued')
            : wait.phase === 'running'
              ? T('反馈正在生成', 'Your feedback is being written')
              : T('反馈还没好', 'Your feedback is not ready yet'),
        'result-cover__wait-what',
      ),
    );
    if (!view.failed && Number.isFinite(wait.seconds)) {
      const clock = el('span', elapsedWords(wait.seconds ?? 0, language), 'result-cover__elapsed');
      clock.dataset.elapsed = '';
      line.append(clock);
    }
    waitBox.append(line);
    // The two stages the server reports, in order; the current one is marked, none is invented.
    if (!view.failed && wait.phase) {
      const stages = el('ol', '', 'result-cover__stages');
      stages.setAttribute('aria-label', T('反馈的进展', 'Feedback stages'));
      (['queued', 'running'] as const).forEach((stage, i) => {
        const now = wait.phase === stage;
        const done = wait.phase === 'running' && stage === 'queued';
        const li = el('li', phaseWords(stage, language), 'result-cover__stage');
        li.dataset.state = now ? 'now' : done ? 'done' : 'next';
        if (now) li.setAttribute('aria-current', 'step');
        stages.append(li);
        if (i === 0) {
          const arrow = el('li', '›', 'result-cover__stage-sep');
          arrow.setAttribute('aria-hidden', 'true');
          stages.append(arrow);
        }
      });
      waitBox.append(stages);
    }
    if (!view.failed) {
      const hint = el('p', '', 'result-cover__wait-hint');
      hint.append(
        el(
          'span',
          T(
            '通常要十几秒到两分钟。可以先回工作板看资料和测试，反馈好了会出现在这里。',
            'It usually takes 15 seconds to two minutes. Look over your documents and tests on the board meanwhile; the feedback appears here when it is ready.',
          ),
        ),
      );
      waitBox.append(hint, button(T('回工作板', 'Back to the board'), null, 'btn small', 'to-board'));
    }
    cover.append(waitBox);
    return cover;
  }

  // 2 and 3. What holds up, and what is not known yet (with why).
  const columns = el('div', '', 'result-cover__columns');
  const list = (...nodes: Node[]) => {
    const ul = el('ul', '', 'result-cover__rows');
    ul.append(...nodes);
    return ul;
  };
  const row = (mark: CoverMark, primary: string, secondary = '', criteria: string[] = []) => {
    const li = el('li', '', 'result-cover__row');
    li.dataset.mark = mark;
    if (criteria.length) li.dataset.criterion = criteria.join(' ');
    const glyph = el('span', GLYPH[mark], 'result-cover__mark');
    glyph.setAttribute('aria-hidden', 'true');
    const words = el('span', '', 'result-cover__words');
    words.append(el('span', primary, 'result-cover__name'));
    if (secondary) words.append(el('span', secondary, 'result-cover__reason'));
    li.append(glyph, words);
    return li;
  };
  const column = (title: string, cls: string, body: Node | null, empty: string) => {
    const box = el('section', '', `result-cover__col ${cls}`);
    box.append(el('h3', title, 'result-cover__col-title'));
    box.append(body ?? el('p', empty, 'result-cover__empty'));
    return box;
  };
  // Not known yet, one line per reason: several criteria waiting for the same thing are named
  // together under it rather than repeated.
  const reasons = new Map<string, CoverRow[]>();
  for (const item of view.unknown) {
    const key = item.reason ?? '';
    reasons.set(key, [...(reasons.get(key) ?? []), item]);
  }
  const unknownRows = [...reasons].map(([reason, items]) =>
    items.length === 1
      ? row('unknown', items[0].name, reason, [items[0].criterion])
      : row(
          'unknown',
          reason,
          T(`${items.length} 项：`, `${items.length} items: `) +
            items.map((item) => item.name).join(T('、', ', ')),
          items.map((item) => item.criterion),
        ),
  );
  columns.append(
    column(
      T('站得住的', 'Holds up'),
      'is-met',
      view.met.length
        ? list(...view.met.map((item) => row('met', item.name, '', [item.criterion])))
        : null,
      T('这次还没有规则核实为满足的项。', 'No item was verified as met by the rules this time.'),
    ),
    column(
      T('还不知道的', 'Not known yet'),
      'is-unknown',
      unknownRows.length ? list(...unknownRows) : null,
      T('没有待核验的项。', 'Nothing is waiting to be checked.'),
    ),
  );
  // 4. Next: the unmet items and one way to each existing step.
  const next = el('section', '', 'result-cover__col result-cover__next');
  next.append(el('h3', T('下一步', 'Next'), 'result-cover__col-title'));
  if (view.unmet.length) {
    next.append(el('p', T('这几项还没满足：', 'Not met yet:'), 'result-cover__lead'));
    const ul = el('ul', '', 'result-cover__rows is-unmet');
    for (const row of view.unmet) {
      const li = el('li', '', 'result-cover__row');
      li.dataset.mark = 'unmet';
      li.dataset.tone = row.tone ?? 'ink';
      li.dataset.criterion = row.criterion;
      const mark = el('span', GLYPH.unmet, 'result-cover__mark');
      mark.setAttribute('aria-hidden', 'true');
      li.append(mark, el('span', T('未满足：', 'Not met: '), 'sr-only'), el('span', row.name, 'result-cover__name'));
      ul.append(li);
    }
    next.append(ul);
  }
  const steps = el('div', '', 'result-cover__steps');
  // With items still unmet, revising is the likely next step: the one primary button, first.
  if (actions.revise)
    steps.append(
      button(T('去修订', 'Revise'), actions.revise, view.unmet.length ? 'btn small primary' : 'btn small'),
    );
  else if (actions.backToBoard)
    steps.append(button(T('回工作板接着改', 'Back to the board'), null, 'btn small', 'to-board'));
  if (actions.supplement) steps.append(button(T('补证', 'Add evidence'), actions.supplement));
  if (actions.practise)
    steps.append(button(T('补练', 'Practise'), null, 'btn small quiet', 'review-practice'));
  if (steps.childElementCount) next.append(steps);
  // Holds up, not known yet and next read side by side (one column on a phone).
  columns.append(next);
  cover.append(columns);

  // From the second delivery: only what changed since the previous one.
  if (view.compare) {
    const box = el('section', '', 'result-cover__compare');
    box.append(
      el(
        'h3',
        Number.isFinite(view.compare.previous)
          ? T(`和第 ${view.compare.previous} 次交付相比`, `Since delivery ${view.compare.previous}`)
          : T('和上次交付相比', 'Since the previous delivery'),
        'result-cover__col-title',
      ),
    );
    if (!view.compare.changes.length)
      box.append(
        el(
          'p',
          T('规则核实的结果和上次一样，没有变化。', 'The rule-checked results are the same as last time.'),
          'result-cover__empty',
        ),
      );
    else {
      const ul = el('ul', '', 'result-cover__changes');
      for (const change of view.compare.changes) {
        const li = el('li', '', 'result-cover__change');
        li.dataset.from = change.from;
        li.dataset.to = change.to;
        li.dataset.criterion = change.criterion;
        const pair = el('span', '', 'result-cover__pair');
        pair.setAttribute('aria-hidden', 'true');
        pair.append(
          el('span', GLYPH[change.from], `result-cover__mark is-${change.from}`),
          el('span', '→', 'result-cover__arrow'),
          el('span', GLYPH[change.to], `result-cover__mark is-${change.to}`),
        );
        const said = {
          met: T('满足', 'met'),
          unmet: T('未满足', 'not met'),
          unknown: T('还不知道', 'not known'),
          na: T('不适用', 'not applicable'),
        };
        li.append(
          pair,
          el('span', change.name, 'result-cover__name'),
          el('span', T(`：${said[change.from]}变为${said[change.to]}`, `: ${said[change.from]} to ${said[change.to]}`), 'sr-only'),
        );
        ul.append(li);
      }
      box.append(ul);
    }
    cover.append(box);
  }

  return cover;
}
