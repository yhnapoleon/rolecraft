/** The feedback page item by item (195, 2026-10-24, approved): one row per criterion that first
 * answers "does it hold up, on what, and what next", grouped not met → not known yet → holds up,
 * with whatever does not apply folded at the end. Each row opens its basis: what the item checks
 * (the rubric's own sentence), what the rules found (stored sentences, never rewritten), the
 * sources, the weight, and the ways to add evidence or disagree. Nothing here scores or totals:
 * counts and the range are read from the record. */
import type { SubmissionRuleCheck } from '../../contracts-v2';
import { copyText } from '../results-native/localization';
import { modelWaitNode } from '../../app/model-status';
import { splitRecognitionPrefix } from '../recognition-native/prefix';
import { criterionChecks, criterionLabels, criterionQuestions, criterionScopes } from './criteria';
import type { Report } from './index';
import {
  feedbackCopy,
  feedbackCount,
  feedbackText,
  type FeedbackCopyKey,
  type FeedbackLanguage,
} from './localization';
import { ruleFact, submissionFactLine } from './presubmit';
import { PRESUBMIT_COPY } from './presubmit-copy';
import { itemDetail, ruleLines } from './rule-lines';
import { criterionWeightText, scoreRangeLine, type ScoreRangeKind } from './score-range';
import { feedbackClass, ruleItems } from './short-summary';
import './feedback-items.css';

type Item = Report['items'][number];
export type ItemMark = 'met' | 'unmet' | 'unknown' | 'na';
/** Unmet rows: red for a limit exceeded, amber for retesting after a change, else ink — the rule
 * the results cover and the pre-submission card use. */
export type ItemTone = 'bad' | 'warn' | 'ink';
/** Existing workbench tools, by the shell's action names (as on the pre-submission card). */
export type ItemTool = 'open-bench' | 'config' | 'resources';
export interface ItemRow {
  criterion: string;
  name: string;
  mark: ItemMark;
  tone?: ItemTone;
  /** The row's one sentence: a rule fact, a short question, or what the model said. */
  line: string;
  /** Red only for a contradiction the model reported. */
  lineTone?: 'bad';
  /** The line waits for a model: the grey mark follows it. */
  lineWaits?: boolean;
  /** The rubric's own sentence for this criterion. */
  checks?: string;
  /** The rules' scope sentence when the stored explanation carries it: it says what is checked,
   * so it sits under "what this item checks", not among the findings. */
  scope?: string;
  /** The stored explanation, line by line, without a premise already stated for the list. */
  found: string[];
  /** "At submission: …", the versions behind an unmet item (164 F17). */
  fact?: string;
  /** The rules' finding or range, in words. */
  bound?: string;
  weight?: string;
  /** A direct way to the step that would change an unmet item. */
  action?: { tool: ItemTool; label: string };
  item: Item;
}
export interface ItemsView {
  count: string;
  range?: { kind: ScoreRangeKind; text: string; note?: string };
  /** "Checked against what you committed: …", from the delivery's decision. */
  scope: string;
  /** Stored notes several criteria share (the backend's premise), kept for the scope basis. */
  premises: string[];
  unmet: ItemRow[];
  unknown: ItemRow[];
  met: ItemRow[];
  na: ItemRow[];
}

const LIMITS = new Set(['R3.capacity', 'R3.resources']);
const CHANGES = new Set(['R4.staleness_test', 'R5.impact', 'R5.adjustment']);
/** When the saved check names no tool, the step that changes each unmet item. */
const FALLBACK_TOOL: Readonly<Record<string, [ItemTool, 'runTest' | 'retest' | 'settings' | 'resources']>> = {
  'R3.capacity': ['config', 'settings'],
  'R3.resources': ['resources', 'resources'],
  'R4.functional_tests': ['open-bench', 'runTest'],
  'R4.staleness_test': ['open-bench', 'retest'],
  'R5.adjustment': ['config', 'settings'],
};
const SCOPES: Readonly<Record<string, FeedbackCopyKey>> = {
  launch: 'scopeLaunch',
  launch_narrow: 'scopeNarrow',
  defer_with_conditions: 'scopeDefer',
  no_go: 'scopeNoGo',
};

/** Where a criterion sits: green when the rules found it met, the unmet marks when they found it
 * not met, grey for everything still open (a range, a pending check, an open applicability). */
export function itemMark(item: Item): ItemMark {
  const kind = feedbackClass(item);
  if (kind === 'notApplicable') return 'na';
  if (kind !== 'verified') return 'unknown';
  const bound = item.rule_bound ?? { lower: item.label, upper: item.label };
  if (bound.lower === bound.upper && bound.lower === 'MET') return 'met';
  if (bound.lower === bound.upper && bound.lower === 'NOT_MET') return 'unmet';
  return 'unknown';
}

/** The rules' default sentence for an item still pending (`rubrics/v4/rules_v2.py` `pending`),
 * both languages. Frozen there by the evaluation version, so the basis replaces it with a
 * plain finding rather than rewording it. */
const PENDING_DEFAULT = new Set([
  '证据或语义尚未核实；保留未知，不按作品形式或未见记录判错。',
  'Evidence or semantics remain unverified; neither format nor absent observations imply failure.',
]);

const lines = (text: string) =>
  text
    .split('\n')
    .map((line) => splitRecognitionPrefix(line.trim()).text.trim())
    .filter(Boolean);

export interface ItemsViewInput {
  readonly language: FeedbackLanguage;
  /** The delivery's decision code, when the report is a delivery's. */
  readonly decision?: string | null;
  readonly kind: 'submission' | 'review' | string;
  /** The saved submission checked again at its own point, for the "at submission" facts. */
  readonly atSubmission?: SubmissionRuleCheck | null;
  /** The R2.support row's line when the model said something (model-advice.ts). */
  readonly adviceLine?: {
    text: string;
    tone: 'bad' | 'ink';
    waiting?: true;
    kind?: 'abstained' | 'advised';
  };
  /** Model advice items of the older protocol that are shown (none while waiting for a model). */
  readonly legacyAdvice?: readonly Item[];
}

export function feedbackItemsView(report: Report, input: ItemsViewInput): ItemsView {
  const { language } = input;
  const T = (key: FeedbackCopyKey, values?: Readonly<Record<string, string | number>>) =>
    feedbackCopy(language, key, values);
  const items = ruleItems(report);
  const names = criterionLabels(language);
  const questions = criterionQuestions(language);
  const checks = criterionChecks(language);
  const scopes = criterionScopes(language);
  const name = (item: Item) =>
    names[item.criterion] ?? feedbackText(language, '具体反馈项', 'Feedback criterion');
  // The rules' one-line finding per criterion, without the shared premise.
  const ruled = ruleLines(items, names, language);
  const findingOf = new Map(ruled.lines.map((line) => [line.criterion, line]));
  const labels: Record<string, string> = {
    NOT_MET: feedbackText(language, '未满足', 'not met'),
    PARTIAL: feedbackText(language, '部分满足', 'partially met'),
    MET: feedbackText(language, '满足', 'met'),
  };
  const presubmit = (key: 'runTest' | 'retest' | 'settings' | 'resources') =>
    copyText(PRESUBMIT_COPY, language, key);
  const view: ItemsView = {
    count: '',
    scope: '',
    premises: ruled.premises,
    unmet: [],
    unknown: [],
    met: [],
    na: [],
  };
  let verified = 0;
  let applicable = 0;
  // Items the model advised on, counted the way the coverage line counts them (2026-10-12 item 3).
  let advised = 0;
  for (const item of items) {
    const kind = feedbackClass(item);
    if (kind === 'verified') verified++;
    if (kind === 'verified' || kind === 'pending') applicable++;
    if (kind === 'pending') {
      const registered = report.model_advice?.filter((entry) => entry.criterion === item.criterion);
      if (
        registered?.length
          ? registered.every((entry) => entry.status === 'completed' && entry.label !== 'INSUFFICIENT')
          : (input.legacyAdvice ?? []).some(
              (entry) => entry.criterion === item.criterion && entry.label !== 'INSUFFICIENT',
            )
      )
        advised++;
    }
    const mark = itemMark(item);
    // Findings only: the rules' scope sentence moves under "what this item checks", and the
    // rules' default pending sentence gives way to one plain finding below.
    const stored = lines(itemDetail(item, ruled.premises));
    const scope = scopes[item.criterion];
    const found = stored.filter((text) => text !== scope && !PENDING_DEFAULT.has(text));
    const bound = item.rule_bound;
    const row: ItemRow = {
      criterion: item.criterion,
      name: name(item),
      mark,
      line: '',
      found,
      item,
      ...(checks[item.criterion] ? { checks: checks[item.criterion] } : {}),
      ...(scope && stored.includes(scope) ? { scope } : {}),
    };
    if (bound)
      row.bound =
        bound.lower === bound.upper
          ? T('ruleFinding', { label: labels[bound.lower] ?? bound.lower })
          : T('ruleRange', {
              range: feedbackText(
                language,
                `介于${labels[bound.lower] ?? bound.lower}和${labels[bound.upper] ?? bound.upper}之间`,
                `between ${labels[bound.lower] ?? bound.lower} and ${labels[bound.upper] ?? bound.upper}`,
              ),
            });
    const weight = criterionWeightText(report, item.criterion, language);
    if (weight) row.weight = weight;
    const fact = submissionFactLine(item, input.atSubmission ?? null, report.rule_items, language);
    if (fact) row.fact = fact;
    if (mark === 'met') {
      row.line = findingOf.get(item.criterion)?.fact || found[0] || '';
      view.met.push(row);
    } else if (mark === 'unmet') {
      row.tone = LIMITS.has(item.criterion) ? 'bad' : CHANGES.has(item.criterion) ? 'warn' : 'ink';
      row.line = fact ?? (findingOf.get(item.criterion)?.fact || found[0] || '');
      const saved =
        fact && input.atSubmission ? ruleFact(item, input.atSubmission.facts ?? {}, language) : null;
      if (saved?.tool && saved.label)
        row.action = { tool: saved.tool, label: copyText(PRESUBMIT_COPY, language, saved.label) };
      else if (FALLBACK_TOOL[item.criterion]) {
        const [tool, label] = FALLBACK_TOOL[item.criterion];
        row.action = { tool, label: presubmit(label) };
      }
      view.unmet.push(row);
    } else if (mark === 'unknown') {
      const advice = item.criterion === 'R2.support' ? input.adviceLine : undefined;
      row.line = advice?.text ?? questions[item.criterion] ?? found[0] ?? '';
      if (!found.length)
        found.push(
          T(
            advice?.kind === 'abstained'
              ? 'foundSupportNone'
              : advice?.kind === 'advised'
                ? 'foundSupportAdvice'
                : 'foundPending',
          ),
        );
      if (advice?.tone === 'bad') row.lineTone = 'bad';
      if (advice?.waiting) row.lineWaits = true;
      view.unknown.push(row);
    } else {
      // Why it does not apply, in the stored words.
      row.line = found[0] ?? '';
      view.na.push(row);
    }
  }
  view.count =
    T('itemsCount', { verified, total: applicable, pending: view.unknown.length }) +
    (advised ? T('itemsCountModel', { model: advised }) : '');
  const range = scoreRangeLine(report, language);
  if (range) view.range = range;
  const scope = input.decision ? SCOPES[input.decision] : undefined;
  view.scope = scope
    ? T(scope)
    : T(input.kind === 'review' ? 'scopeReviewed' : 'scopeDelivered');
  return view;
}

/** One delivery's feedback in one line, for the list of earlier deliveries. */
export function earlierSummary(view: ItemsView, language: FeedbackLanguage): string {
  const parts: string[] = [];
  if (view.unmet.length) parts.push(feedbackCount(language, 'earlierUnmet', view.unmet.length));
  parts.push(feedbackCount(language, 'earlierMet', view.met.length));
  parts.push(feedbackCount(language, 'earlierUnknown', view.unknown.length));
  return parts.join(' · ');
}

const GLYPH: Record<ItemMark, string> = { met: '✓', unmet: '✗', unknown: '?', na: '—' };
const SR: Record<ItemMark, FeedbackCopyKey> = {
  met: 'markMet',
  unmet: 'markUnmet',
  unknown: 'markUnknown',
  na: 'markNotApplicable',
};

export interface ItemsRenderHooks {
  /** Stable, unique prefix for element ids within the page. */
  readonly id: string;
  readonly isOpen: (key: string) => boolean;
  readonly onToggle: (key: string, open: boolean) => void;
  /** Nodes the host appends to a row's basis: sources, signals, model advice, responses. */
  readonly basis?: (row: ItemRow) => Node[];
  /** The direct button of an unmet row. */
  readonly action?: (row: ItemRow) => Node | null;
  /** Nodes shown with the scope line's basis: stored premises and next steps. */
  readonly scopeBasis?: Node[];
  /** Placed at the end of the list, before what does not apply (the lens's sentence reading). */
  readonly after?: Node[];
  /** The delivery or review the list belongs to, as a reference chip (first on the meta line). */
  readonly subject?: Node;
  /** "Can't tell yet" shows this many rows first, the rest behind "Show n more" (result page). */
  readonly unknownShown?: number;
  /** The view switch (By status · By colleague), placed on the meta line (result page). */
  readonly switcher?: Node;
  /** When given, the groups by status give way to this view of the same rows. */
  readonly regrouped?: () => Node;
}

type El = HTMLElement;

/** A disclosure: the head button and its body, opened in place; the body leaves the page and the
 * accessibility tree while closed. Opening plays one short fade (never on a redraw). */
export function disclosure(
  doc: Document,
  head: El,
  body: El,
  key: string,
  hooks: Pick<ItemsRenderHooks, 'isOpen' | 'onToggle'>,
  host?: El,
) {
  const set = (open: boolean, animate: boolean) => {
    head.setAttribute('aria-expanded', String(open));
    body.hidden = !open;
    if (host) host.dataset.open = String(open);
    if (open && animate) {
      body.dataset.opening = '';
      body.addEventListener('animationend', () => delete body.dataset.opening);
    }
  };
  head.addEventListener('click', () => {
    const open = head.getAttribute('aria-expanded') !== 'true';
    set(open, true);
    hooks.onToggle(key, open);
  });
  set(hooks.isOpen(key), false);
  void doc;
}

export function renderFeedbackItems(
  doc: Document,
  view: ItemsView,
  language: FeedbackLanguage,
  hooks: ItemsRenderHooks,
): El {
  const T = (key: FeedbackCopyKey, values?: Readonly<Record<string, string | number>>) =>
    feedbackCopy(language, key, values);
  const el = <K extends keyof HTMLElementTagNameMap>(tag: K, text = '', cls = '') => {
    const node = doc.createElement(tag);
    if (text) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  };
  const safe = (text: string) => text.replace(/[^A-Za-z0-9_-]+/g, '-');
  const root = el('section', '', 'fb-items');
  root.dataset.feedbackItems = '';
  // Kept for the tools that read the rule-checked list by this mark.
  root.dataset.ruleLines = '';
  root.setAttribute('aria-label', T('itemsTitle'));

  // The counts and the recorded range; the range's caveat behind ⓘ.
  const meta = el('p', '', 'fb-meta');
  if (hooks.subject) meta.append(hooks.subject);
  meta.append(el('span', view.count, 'fb-meta__count'));
  if (hooks.switcher) {
    const bar = el('div', '', 'fb-detail-bar');
    bar.append(meta, hooks.switcher);
    root.append(bar);
  } else root.append(meta);
  let tip: El | undefined;
  if (view.range) {
    const line = el('p', '', 'fb-range');
    const range = el('span', view.range.text, 'fb-meta__range');
    range.dataset.scoreRange = view.range.kind;
    line.append(range);
    root.append(line);
    if (view.range.note) {
      const info = el('button', 'ⓘ', 'fb-info');
      info.type = 'button';
      info.setAttribute('aria-label', T('itemsRangeInfo'));
      info.id = `${safe(hooks.id)}-range`;
      tip = el('p', view.range.note, 'fb-tip');
      tip.id = `${safe(hooks.id)}-range-note`;
      info.setAttribute('aria-controls', tip.id);
      line.append(info);
      disclosure(doc, info, tip, `${hooks.id}:range`, hooks);
    }
  }
  if (tip) root.append(tip);

  // "Checked against what you committed": the stored premise and next steps are its basis.
  const scope = el('div', '', 'fb-scope');
  const scopeLine = el('p', '', 'fb-scope__line');
  scopeLine.append(el('span', view.scope, 'fb-scope__text'));
  if (hooks.scopeBasis?.length) {
    const toggle = el('button', '', 'fb-scope__toggle');
    toggle.type = 'button';
    toggle.append(el('span', T('scopeBasis')), chevron(doc));
    const body = el('div', '', 'fb-scope__basis');
    body.id = `${safe(hooks.id)}-scope`;
    toggle.setAttribute('aria-controls', body.id);
    body.append(...hooks.scopeBasis);
    scopeLine.append(toggle);
    scope.append(scopeLine, body);
    disclosure(doc, toggle, body, `${hooks.id}:scope`, hooks, scope);
  } else scope.append(scopeLine);
  root.append(scope);

  const row = (item: ItemRow) => renderItemRow(doc, item, language, hooks);

  const group = (
    kind: 'unmet' | 'unknown' | 'met',
    title: FeedbackCopyKey,
    note: FeedbackCopyKey,
    rows: ItemRow[],
  ) => {
    if (!rows.length) return;
    const box = el('section', '', 'fb-group');
    box.dataset.group = kind;
    const heading = el('h3', '', 'fb-group__head');
    heading.append(
      el('span', T('groupCount', { name: T(title), n: rows.length }), 'fb-group__title'),
      el('span', T(note), 'fb-group__note'),
    );
    const list = el('ul', '', 'fb-list');
    const shown = kind === 'unknown' && hooks.unknownShown ? hooks.unknownShown : rows.length;
    list.append(...rows.slice(0, shown).map(row));
    box.append(heading, list);
    // The rest of a long group behind one quiet line; opened, it stays open across redraws.
    if (rows.length > shown) {
      const more = el('ul', '', 'fb-list fb-list--more');
      more.id = `${safe(hooks.id)}-${kind}-more`;
      more.append(...rows.slice(shown).map(row));
      const toggle = el('button', '', 'fb-more__toggle');
      toggle.type = 'button';
      toggle.setAttribute('aria-controls', more.id);
      const label = el('span', '');
      toggle.append(label, chevron(doc));
      const words = () =>
        (label.textContent =
          toggle.getAttribute('aria-expanded') === 'true'
            ? T('groupFewer')
            : T('groupMore', { n: rows.length - shown }));
      box.append(more, toggle);
      disclosure(doc, toggle, more, `${hooks.id}:${kind}:more`, hooks, box);
      toggle.addEventListener('click', words);
      words();
    }
    detail.append(box);
  };
  // The detail: by status, or the same rows regrouped (result page).
  const detail = el('div', '', 'fb-detail');
  detail.dataset.resultDetail = hooks.regrouped ? 'colleague' : 'status';
  root.append(detail);
  if (hooks.regrouped) detail.append(hooks.regrouped());
  else {
    group('unmet', 'groupUnmet', 'groupUnmetNote', view.unmet);
    group('unknown', 'groupUnknown', 'groupUnknownNote', view.unknown);
    group('met', 'groupMet', 'groupMetNote', view.met);
  }
  root.append(...(hooks.after ?? []));
  if (view.na.length) {
    const box = el('section', '', 'fb-group fb-group--na');
    box.dataset.group = 'na';
    const toggle = el('button', '', 'fb-na__toggle');
    toggle.type = 'button';
    toggle.append(
      el('span', feedbackCount(language, 'groupNotApplicable', view.na.length)),
      chevron(doc),
    );
    const list = el('ul', '', 'fb-list');
    list.id = `${safe(hooks.id)}-na`;
    toggle.setAttribute('aria-controls', list.id);
    list.append(...view.na.map(row));
    box.append(toggle, list);
    disclosure(doc, toggle, list, `${hooks.id}:na`, hooks, box);
    root.append(box);
  }
  return root;
}

/** One criterion as a row: its shape, name and one sentence; it opens its basis in place. */
export function renderItemRow(
  doc: Document,
  item: ItemRow,
  language: FeedbackLanguage,
  hooks: Pick<ItemsRenderHooks, 'id' | 'isOpen' | 'onToggle' | 'basis' | 'action'>,
): El {
  const T = (key: FeedbackCopyKey) => feedbackCopy(language, key);
  const el = <K extends keyof HTMLElementTagNameMap>(tag: K, text = '', cls = '') => {
    const node = doc.createElement(tag);
    if (text) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  };
  const safe = (text: string) => text.replace(/[^A-Za-z0-9_-]+/g, '-');
  const li = el('li', '', 'fb-item');
  li.dataset.feedbackItem = item.criterion;
  li.dataset.mark = item.mark;
  if (item.tone) li.dataset.tone = item.tone;
  const line = el('div', '', 'fb-item__row');
  const head = el('button', '', 'fb-item__head');
  head.type = 'button';
  const mark = el('span', GLYPH[item.mark], 'fb-mark');
  mark.setAttribute('aria-hidden', 'true');
  const words = el('span', '', 'fb-item__words');
  const title = el('span', '', 'fb-item__name');
  title.append(el('span', T(SR[item.mark]), 'sr-only'), item.name);
  const sub = el('span', item.line, 'fb-item__line');
  if (item.lineTone) sub.dataset.tone = item.lineTone;
  if (item.lineWaits) sub.append(modelWaitNode(doc, '', language));
  words.append(title, sub);
  head.append(mark, words, chevron(doc));
  line.append(head);
  const go = hooks.action?.(item);
  if (go) line.append(go);
  const body = el('div', '', 'fb-item__body');
  body.id = `${safe(hooks.id)}-${safe(item.criterion)}`;
  head.setAttribute('aria-controls', body.id);
  const basis = el('div', '', 'fb-basis');
  const block = (label: FeedbackCopyKey, ...nodes: (Node | string)[]) => {
    const box = el('div', '', 'fb-basis__block');
    box.append(el('p', T(label), 'fb-basis__label'), ...nodes);
    return box;
  };
  if (item.checks || item.scope)
    basis.append(
      block(
        'basisChecks',
        ...(item.checks ? [el('p', item.checks, 'fb-basis__text')] : []),
        ...(item.scope ? [el('p', item.scope, 'fb-basis__note')] : []),
      ),
    );
  const found: Node[] = item.found.map((text) => el('p', text, 'fb-basis__text rule-detail'));
  if (item.fact) {
    const fact = el('p', item.fact, 'fb-basis__text');
    fact.dataset.ruleFact = item.criterion;
    found.push(fact);
  }
  if (item.bound) found.push(el('p', item.bound, 'fb-basis__note'));
  if (found.length) basis.append(block('basisFound', ...found));
  basis.append(...(hooks.basis?.(item) ?? []));
  body.append(basis);
  li.append(line, body);
  disclosure(doc, head, body, `${hooks.id}:${item.criterion}`, hooks, li);
  return li;
}

function chevron(doc: Document) {
  const node = doc.createElement('span');
  node.className = 'fb-chev';
  node.setAttribute('aria-hidden', 'true');
  node.textContent = '›';
  return node;
}
