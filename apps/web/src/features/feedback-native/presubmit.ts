/** Pre-submission preview: what submitting the chosen versions with this decision would give,
 * read from the read-only rule check. Recorded rule texts are shown as saved; this module only
 * phrases the verified facts behind them. presubmitView and createPresubmitSchedule are pure;
 * mountPresubmitCard draws them. Nothing here saves, submits or runs a model. */
import type { SubmissionRuleCheck, _ConfigTestRuns, _RuleCheckFacts } from '../../contracts-v2';
import { copyText } from '../results-native/localization';
import { criterionLabels } from './criteria';
import { exactRefKey } from './exact-ref';
import type { SubmitChoice } from './index';
import type { FeedbackLanguage } from './localization';
import { PRESUBMIT_COPY, type PresubmitKey } from './presubmit-copy';
import { type Counted, feedbackClass, feedbackCounts } from './short-summary';
import type { PreviewRecognition } from '../recognition-native/chain';
import { LENS_COPY } from '../recognition-native/lens-copy';
import { lensOn, onLensChange } from '../recognition-native/lens';
import { previewQuiet, renderSentenceLens } from '../recognition-native/sentences';

type Facts = _RuleCheckFacts;
type Tone = 'good' | 'bad' | 'warn' | 'ink';
/** Existing workbench tools a line can open; buttons carry them as the shell's action names. */
type Tool = 'open-bench' | 'config' | 'resources';
type Fact = { text: string; tone: Tone; tool?: Tool; label?: PresubmitKey };
type Values = Readonly<Record<string, string | number>>;
/** A criterion and the rules' finding for it. */
type Judged = { criterion: string; label: string };

export type PresubmitLine = {
  criterion: string;
  met: boolean;
  /** The rule's finding in words, for screen readers beside the mark. */
  finding: string;
  text: string;
  tone: Tone;
  action: { action: Tool; label: string } | null;
};
/** The second, slower step of the preview: C2 + C1 + C6 sentence labels of the work, computed by
 * the server only when the recognition layer is on. The rule check marks it `{status:
 * 'pending'}`; `recognize` then returns the labels. Older servers carry them inline. */
export type SentenceResult = { enabled: boolean; recognition: PreviewRecognition | null };
export type SentencePass =
  | { kind: 'idle' }
  | { kind: 'running'; startedAt: number }
  | { kind: 'ready'; preview: PreviewRecognition }
  | { kind: 'failed' };

export type PresubmitView = {
  title: string;
  count: { met: number; total: number; text: string } | null;
  empty: string | null;
  lines: PresubmitLine[];
  waiting: string | null;
  details: {
    label: string;
    note: string;
    basis: { name: string; text: string; chineseSource: boolean }[];
    waiting: string | null;
    inapplicable: string | null;
    chineseSource: string;
  };
};

const say = (language: FeedbackLanguage, key: PresubmitKey, values?: Values) =>
  copyText(PRESUBMIT_COPY, language, key, values);
const plural = (n: number, many: PresubmitKey, one: PresubmitKey) => (n === 1 ? one : many);
const sentence = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/** The latest configuration, other than the checked one, with actual runs (or retests). */
function elsewhere(facts: Facts, field: 'runs' | 'retests'): _ConfigTestRuns | undefined {
  return (facts.test_runs ?? [])
    .filter((row) => row.config_version !== facts.config_version && row[field] > 0)
    .reduce<_ConfigTestRuns | undefined>(
      (latest, row) => (!latest || row.config_version > latest.config_version ? row : latest),
      undefined,
    );
}
const onChecked = (facts: Facts, field: 'runs' | 'retests') =>
  facts.test_runs?.find((row) => row.config_version === facts.config_version)?.[field] ?? 0;

/** One sentence of verified fact for a criterion the rules decided. Each criterion words only the
 * findings its rule names; anything else (not applicable, awaiting a model) gets null. */
export function ruleFact(item: Judged, facts: Facts, language: FeedbackLanguage): Fact | null {
  const t = (key: PresubmitKey, values?: Values) => say(language, key, values);
  const met = item.label === 'MET';
  const c = facts.config_version;
  switch (item.criterion) {
    case 'R2.unknowns':
      return item.label === 'NOT_MET' && facts.unapproved_resource_excess === true
        ? { text: t('excess'), tone: 'bad', tool: 'resources', label: 'resources' }
        : null;
    case 'R3.capacity': {
      const p = facts.participants;
      const cap = facts.capacity;
      if (typeof p !== 'number' || typeof cap !== 'number') return null;
      if (met) return { text: t('capacityWithin', { p, c: cap }), tone: 'good' };
      if (item.label !== 'NOT_MET') return null;
      const over = { tone: 'bad' as const, tool: 'config' as const, label: 'settings' as const };
      if (p === 0) return { text: t('capacityNone'), ...over };
      return p > cap ? { text: t('capacityOver', { p, c: cap }), ...over } : null;
    }
    case 'R3.resources': {
      const r = facts.required_dev_days;
      const a = facts.available_dev_days;
      const l = facts.requested_launch_day;
      const d = facts.deadline_day;
      if (![r, a, l, d].every((value) => typeof value === 'number')) return null;
      const days = { r: r as number, a: a as number, l: l as number, d: d as number };
      if (met) return { text: t('resourcesWithin', days), tone: 'good' };
      if (item.label !== 'NOT_MET') return null;
      const short = days.r > days.a;
      const parts = [
        ...(short ? [t('resourcesDays', days)] : []),
        ...(days.l > days.d ? [t('resourcesDeadline', days)] : []),
      ];
      if (!parts.length) return null;
      return {
        text: sentence(parts.join(t('join'))),
        tone: 'bad',
        ...(short
          ? { tool: 'resources' as const, label: 'resources' as const }
          : { tool: 'config' as const, label: 'settings' as const }),
      };
    }
    case 'R4.functional_tests': {
      if (typeof c !== 'number') return null;
      if (item.label === 'NOT_MET') {
        const other = elsewhere(facts, 'runs');
        const text = other
          ? t(plural(other.runs, 'untestedElsewhere', 'untestedElsewhereOne'), {
              c,
              o: other.config_version,
              k: other.runs,
            })
          : t('untested', { c });
        return { text, tone: 'ink', tool: 'open-bench', label: 'runTest' };
      }
      if (!met && item.label !== 'PARTIAL') return null;
      const k = onChecked(facts, 'runs');
      if (!k) return null;
      const text = t(plural(k, 'tested', 'testedOne'), { c, k });
      return met
        ? { text, tone: 'good' }
        : { text, tone: 'ink', tool: 'open-bench', label: 'runTest' };
    }
    case 'R4.staleness_test': {
      if (typeof c !== 'number') return null;
      if (met) {
        const p = facts.policy_version;
        return {
          text: typeof p === 'number' ? t('retestCurrent', { c, p }) : t('retestCurrentAny', { c }),
          tone: 'good',
        };
      }
      if (item.label === 'PARTIAL')
        return { text: t('retestStale', { c }), tone: 'warn', tool: 'open-bench', label: 'retest' };
      if (item.label !== 'NOT_MET') return null;
      const other = elsewhere(facts, 'retests');
      const text = other
        ? t(plural(other.retests, 'notRetestedElsewhere', 'notRetestedElsewhereOne'), {
            c,
            o: other.config_version,
            k: other.retests,
          })
        : t('notRetested', { c });
      return { text, tone: 'warn', tool: 'open-bench', label: 'retest' };
    }
    case 'R5.adjustment': {
      if (typeof c !== 'number') return null;
      if (met) return { text: t('retestPassed', { c }), tone: 'good' };
      const n = facts.adjustment_actions;
      if (item.label === 'NOT_MET' || (item.label === 'PARTIAL' && n === 0)) {
        // A retest on an earlier configuration does not count for this one; say so.
        const other = elsewhere(facts, 'retests');
        return other
          ? {
              text: t(plural(other.retests, 'noAdjustmentElsewhere', 'noAdjustmentElsewhereOne'), {
                c,
                o: other.config_version,
                k: other.retests,
              }),
              tone: 'warn',
              tool: 'open-bench',
              label: 'retest',
            }
          : { text: t('noAdjustment'), tone: 'warn', tool: 'config', label: 'settings' };
      }
      if (item.label !== 'PARTIAL' || typeof n !== 'number') return null;
      const text =
        onChecked(facts, 'retests') === 0
          ? t(plural(n, 'adjustedNotRetested', 'adjustedNotRetestedOne'), { n, c })
          : t('retestNotPassed', { c });
      return { text, tone: 'warn', tool: 'open-bench', label: 'retest' };
    }
    default:
      return null;
  }
}

const FINDINGS: Readonly<Record<string, PresubmitKey>> = {
  MET: 'met',
  PARTIAL: 'partial',
  NOT_MET: 'notMet',
};

/** The card's content: rule-decided items counted and phrased; the rest summarised by count. */
export function presubmitView(
  check: SubmissionRuleCheck,
  language: FeedbackLanguage,
): PresubmitView {
  const t = (key: PresubmitKey, values?: Values) => say(language, key, values);
  const names = criterionLabels(language);
  const name = (criterion: string) => names[criterion] ?? t('item');
  const facts = check.facts ?? {};
  const decided = check.rule_items.filter((item) => feedbackClass(item) === 'verified');
  const lines = decided.map((item): PresubmitLine => {
    const met = item.label === 'MET';
    const finding = t(FINDINGS[item.label] ?? 'notMet');
    const fact = ruleFact(item, facts, language);
    return {
      criterion: item.criterion,
      met,
      finding,
      text: fact?.text ?? t('generic', { name: name(item.criterion), finding }),
      tone: fact?.tone ?? (met ? 'good' : 'ink'),
      action: !met && fact?.tool && fact.label ? { action: fact.tool, label: t(fact.label) } : null,
    };
  });
  const counts = feedbackCounts(check.rule_items);
  const listed = (kind: ReturnType<typeof feedbackClass>) =>
    check.rule_items
      .filter((item) => feedbackClass(item) === kind)
      .map((item) => name(item.criterion))
      .join(t('list'));
  const met = lines.filter((line) => line.met).length;
  const total = lines.length;
  return {
    title: t('title'),
    count: total ? { met, total, text: t('count', { met, total }) } : null,
    empty: total
      ? null
      : counts.notApplicable
        ? t('empty', { n: counts.notApplicable })
        : t('emptyNone'),
    lines,
    waiting: counts.pending ? t('waiting', { n: counts.pending }) : null,
    details: {
      label: t('basis'),
      note: t('readOnly'),
      basis: decided.map((item) => ({
        name: name(item.criterion),
        text: item.explanation,
        chineseSource: language === 'en' && check.work_language === 'zh',
      })),
      waiting: counts.pending ? t('waitingNames', { names: listed('pending') }) : null,
      inapplicable: counts.notApplicable
        ? t('inapplicableNames', { names: listed('notApplicable') })
        : null,
      chineseSource: t('chineseSource'),
    },
  };
}

/** Key order never matters: two JSON values are the same record when their content is. */
const sameRecord = (a: unknown, b: unknown) => {
  const sorted = (_key: string, value: unknown) =>
    value && typeof value === 'object' && !Array.isArray(value)
      ? Object.fromEntries(Object.entries(value).sort(([x], [y]) => (x < y ? -1 : x > y ? 1 : 0)))
      : value;
  return JSON.stringify(a, sorted) === JSON.stringify(b, sorted);
};

/** On the feedback page: "At submission: ..." for an item the rules decided and did not find
 * met; never for an item that did not apply or still awaits a model. Shown only when the saved
 * submission, checked again at its own point, gives exactly the recorded rule items; otherwise
 * nothing is added and the recorded feedback stands as it is. */
export function submissionFactLine(
  item: Judged & Counted,
  check: SubmissionRuleCheck | null,
  recorded: readonly unknown[] | null | undefined,
  language: FeedbackLanguage,
): string | null {
  if (feedbackClass(item) !== 'verified' || item.label === 'MET') return null;
  if (!check || !recorded || !sameRecord(check.rule_items, recorded)) return null;
  const fact = ruleFact(item, check.facts ?? {}, language);
  return fact ? say(language, 'atSubmission', { fact: fact.text }) : null;
}

/** A choice to preview, with the records point it was made at. */
export type PresubmitChoice = SubmitChoice & { point?: string };
export type PresubmitState =
  | { kind: 'idle' }
  | { kind: 'loading'; check: SubmissionRuleCheck | null }
  | { kind: 'ready'; check: SubmissionRuleCheck }
  | { kind: 'failed' };

/** Load the check once a choice settles; one request at a time, and only the latest is shown. */
export function createPresubmitSchedule(options: {
  load: (choice: SubmitChoice) => Promise<SubmissionRuleCheck>;
  show: (state: PresubmitState) => void;
  delay?: number;
}) {
  const delay = options.delay ?? 300;
  let wanted: PresubmitChoice | null = null;
  let wantedKey: string | null = null;
  let shownKey: string | null = null;
  let shown: SubmissionRuleCheck | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let inFlight = false;
  let again = false;
  let closed = false;
  const keyOf = (choice: PresubmitChoice) =>
    JSON.stringify([
      choice.decision,
      choice.products.map(exactRefKey).sort(),
      choice.point ?? null,
    ]);

  async function flush() {
    if (closed || !wanted) return;
    if (inFlight) {
      again = true;
      return;
    }
    const choice = wanted;
    const key = wantedKey;
    inFlight = true;
    try {
      const check = await options.load({ decision: choice.decision, products: choice.products });
      if (!closed && key === wantedKey) {
        shown = check;
        shownKey = key;
        options.show({ kind: 'ready', check });
      }
    } catch {
      if (!closed && key === wantedKey) {
        shown = null;
        shownKey = key;
        options.show({ kind: 'failed' });
      }
    } finally {
      inFlight = false;
      if (again) {
        again = false;
        if (wantedKey !== shownKey) void flush();
      }
    }
  }

  return {
    request(choice: PresubmitChoice | null) {
      if (closed) return;
      const key = choice ? keyOf(choice) : null;
      if (key === wantedKey) return;
      wanted = choice;
      wantedKey = key;
      clearTimeout(timer);
      if (!choice) {
        shown = null;
        shownKey = null;
        options.show({ kind: 'idle' });
        return;
      }
      if (key === shownKey && shown) {
        options.show({ kind: 'ready', check: shown });
        return;
      }
      options.show({ kind: 'loading', check: shown });
      timer = setTimeout(() => void flush(), delay);
    },
    destroy() {
      closed = true;
      clearTimeout(timer);
    },
  };
}

const carried = (check: SubmissionRuleCheck) =>
  (check as SubmissionRuleCheck & { recognition?: (PreviewRecognition & { status?: string }) | null })
    .recognition ?? null;

/** Runs the sentence step for the check on screen: nothing when the recognition layer is off,
 * otherwise one request per check, a running state with its start time, and only the answer for
 * the check still shown. */
export function createSentencePass(options: {
  recognize?: (choice: SubmitChoice) => Promise<SentenceResult>;
  show: (pass: SentencePass) => void;
  now?: () => number;
}) {
  const now = options.now ?? (() => Date.now());
  const results = new WeakMap<SubmissionRuleCheck, SentencePass>();
  let current: SubmissionRuleCheck | null = null;
  const settle = (check: SubmissionRuleCheck, pass: SentencePass) => {
    results.set(check, pass);
    if (check === current) options.show(pass);
  };
  return {
    start(check: SubmissionRuleCheck | null, choice: SubmitChoice | null) {
      current = check;
      const body = check ? carried(check) : null;
      if (!check || !body) return options.show({ kind: 'idle' });
      if (Array.isArray(body.units) && body.units.length) return options.show({ kind: 'ready', preview: body });
      if (body.status !== 'pending' || !options.recognize || !choice) return options.show({ kind: 'idle' });
      const known = results.get(check);
      if (known) return options.show(known);
      const running: SentencePass = { kind: 'running', startedAt: now() };
      results.set(check, running);
      options.show(running);
      options.recognize(choice).then(
        (found) =>
          settle(
            check,
            found.enabled && found.recognition?.units?.length
              ? { kind: 'ready', preview: found.recognition }
              : { kind: 'idle' },
          ),
        () => {
          results.delete(check);
          if (check === current) options.show({ kind: 'failed' });
        },
      );
    },
  };
}

export const PRESUBMIT_STYLE =
  '.presubmit{margin:14px 0;padding:14px 16px;border:1px solid var(--line-2);border-radius:var(--r-md,12px);background:var(--surface-2);display:grid;gap:8px}.presubmit p,.presubmit ul{margin:0}.presubmit__title{margin:0;font-size:15px;font-weight:600}.presubmit[aria-busy="true"] .presubmit__result{opacity:.55}.presubmit__meter{display:flex;align-items:center;gap:10px}.presubmit__bar{flex:1;max-width:220px;height:6px;border-radius:999px;background:var(--line-2);overflow:hidden}.presubmit__fill{display:block;height:100%;background:var(--good)}.presubmit__count{font-size:13.5px;font-weight:600;font-variant-numeric:tabular-nums}.presubmit__items{list-style:none;padding:0;display:grid;gap:6px}.presubmit__items li{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}.presubmit__mark{flex:none;width:1.1em;font-weight:700;color:var(--ink-2)}.presubmit__items [data-tone="good"] .presubmit__mark{color:var(--good)}.presubmit__items [data-tone="bad"] .presubmit__mark{color:var(--bad)}.presubmit__items [data-tone="warn"] .presubmit__mark{color:var(--warn)}.presubmit__text{flex:1 1 14em;min-width:0}.presubmit .btn.small{min-height:28px;margin:0}.presubmit__muted,.presubmit__waiting{color:var(--ink-3);font-size:13px}.presubmit details{font-size:13px;color:var(--ink-2)}.presubmit details p{margin-block:6px}' +
  '.presubmit[data-frame="flat"]{padding:0;border:0;border-radius:0;background:none}@media (max-width:560px){.presubmit:not([data-frame="flat"]){padding:12px 10px}}.presubmit__rec{display:grid;gap:4px;padding-top:8px;border-top:1px dashed var(--line-2)}.presubmit__rec:empty{display:none}.presubmit__stage{display:flex;flex-wrap:wrap;align-items:baseline;gap:2px 8px;font-size:13px;color:var(--ink-2)}.presubmit__stage-done{color:var(--ink-3)}.presubmit__stage-done b{color:var(--good);font-weight:600;margin-inline-end:3px}.presubmit__elapsed{color:var(--ink-3);font-variant-numeric:tabular-nums}';

/** The card above the submit button. update() takes the current choice, or null when the person
 * has not chosen both a decision and at least one version. */
export function mountPresubmitCard(
  doc: Document,
  language: FeedbackLanguage,
  load: (choice: SubmitChoice) => Promise<SubmissionRuleCheck>,
  options: {
    recognize?: (choice: SubmitChoice) => Promise<SentenceResult>;
    /** 'panel' (default): the grey preview panel. 'flat': no panel frame, so the work's
     * sentences sit as paper directly in the host (spec 197 §8, submission dialog). */
    frame?: 'panel' | 'flat';
    /** The sentence reading is placed by the host (`reading`), not under the rules (the
     * three-column submission dialog, 206). */
    split?: boolean;
    /** Told the sentence step's state each time it is drawn. */
    onReading?: (kind: 'idle' | 'running' | 'ready' | 'failed') => void;
  } = {},
) {
  const t = (key: PresubmitKey, values?: Values) => say(language, key, values);
  const root = doc.createElement('section');
  root.className = 'presubmit';
  root.dataset.presubmit = '';
  root.dataset.frame = options.frame ?? 'panel';
  const title = doc.createElement('h3');
  title.className = 'presubmit__title';
  title.id = `presubmit-${Math.random().toString(36).slice(2)}`;
  title.textContent = t('title');
  root.setAttribute('aria-labelledby', title.id);
  const body = doc.createElement('div');
  body.className = 'presubmit__result';
  // Announce only the outcome line, not the whole list, on each recompute.
  const status = doc.createElement('p');
  status.className = 'sr-only';
  status.setAttribute('role', 'status');
  root.append(title, status, body);
  const el = <K extends keyof HTMLElementTagNameMap>(tag: K, text = '', cls = '') => {
    const node = doc.createElement(tag);
    node.textContent = text;
    if (cls) node.className = cls;
    return node;
  };
  function draw(view: PresubmitView): Node[] {
    const nodes: Node[] = [];
    if (view.count) {
      const meter = el('div', '', 'presubmit__meter');
      const bar = el('span', '', 'presubmit__bar');
      bar.setAttribute('role', 'meter');
      bar.setAttribute('aria-valuemin', '0');
      bar.setAttribute('aria-valuemax', String(view.count.total));
      bar.setAttribute('aria-valuenow', String(view.count.met));
      bar.setAttribute('aria-valuetext', view.count.text);
      const fill = el('span', '', 'presubmit__fill');
      fill.style.inlineSize = `${(view.count.met / view.count.total) * 100}%`;
      bar.append(fill);
      const count = el('span', view.count.text, 'presubmit__count');
      count.setAttribute('aria-hidden', 'true');
      meter.append(bar, count);
      nodes.push(meter);
    } else if (view.empty) nodes.push(el('p', view.empty));
    if (view.lines.length) {
      const list = el('ul', '', 'presubmit__items');
      for (const line of view.lines) {
        const row = el('li');
        row.dataset.criterion = line.criterion;
        row.dataset.met = String(line.met);
        row.dataset.tone = line.tone;
        const mark = el('span', line.met ? '✓' : '✗', 'presubmit__mark');
        mark.setAttribute('aria-hidden', 'true');
        row.append(
          mark,
          el('span', t('markLabel', { finding: line.finding }), 'sr-only'),
          el('span', line.text, 'presubmit__text'),
        );
        if (line.action) {
          const go = el('button', line.action.label, 'btn quiet small');
          go.type = 'button';
          go.dataset.action = line.action.action;
          row.append(go);
        }
        list.append(row);
      }
      nodes.push(list);
    }
    if (view.waiting) nodes.push(el('p', view.waiting, 'presubmit__waiting'));
    if (!options.split) nodes.push(rec);
    const details = el('details');
    details.append(el('summary', view.details.label));
    for (const row of view.details.basis) {
      const p = el('p');
      p.append(el('b', row.name), doc.createTextNode(` ${row.text}`));
      if (row.chineseSource)
        p.append(el('small', ` ${view.details.chineseSource}`, 'presubmit__muted'));
      details.append(p);
    }
    for (const text of [view.details.waiting, view.details.inapplicable, view.details.note])
      if (text) details.append(el('p', text, 'presubmit__muted'));
    nodes.push(details);
    return nodes;
  }
  // The sentence step under the rules: a real stage name and seconds while it runs, then one
  // quiet line, or the work sentence by sentence when the recognition lens is open.
  const rec = el('div', '', 'presubmit__rec');
  rec.dataset.presubmitRecognition = '';
  const lens = (key: keyof typeof LENS_COPY.zh, values?: Values) =>
    copyText(LENS_COPY, language, key, values);
  const chains = new Set<number>();
  let sentences: SentencePass = { kind: 'idle' };
  let ticker: ReturnType<typeof setInterval> | undefined;
  // The reading plays when the sentences arrive with the lens open, or when the lens opens.
  let playNext = false;
  function drawSentences() {
    clearInterval(ticker);
    ticker = undefined;
    const pass = sentences;
    if (pass.kind === 'running') {
      const stage = el('p', '', 'presubmit__stage');
      const done = el('span', '', 'presubmit__stage-done');
      done.append(el('b', '✓'), doc.createTextNode(lens('stage_rules')));
      const elapsed = el('span', '', 'presubmit__elapsed');
      elapsed.setAttribute('aria-hidden', 'true');
      const tick = () => {
        elapsed.textContent = lens('stage_elapsed', { s: Math.max(0, Math.floor((Date.now() - pass.startedAt) / 1000)) });
      };
      tick();
      ticker = setInterval(tick, 1000);
      stage.append(done, el('span', '→', 'presubmit__muted'), el('span', `${lens('stage_sentences')}…`), elapsed);
      rec.replaceChildren(stage, el('p', lens('stage_keepWriting'), 'presubmit__muted'));
    } else if (pass.kind === 'ready') {
      const quiet = previewQuiet(pass.preview, language);
      rec.replaceChildren(
        lensOn()
          ? renderSentenceLens(doc, {
              preview: pass.preview,
              language,
              open: chains,
              play: playNext,
              // The submission dialog shows Replay in its header, beside the lens switch.
              replay: false,
            })
          : el('p', quiet ?? '', 'presubmit__muted'),
      );
      playNext = false;
    } else if (pass.kind === 'failed') rec.replaceChildren(el('p', lens('stage_failed'), 'presubmit__muted'));
    else rec.replaceChildren();
    options.onReading?.(pass.kind);
  }
  const pass = createSentencePass({
    recognize: options.recognize,
    show: (next) => {
      if (next.kind === 'ready' && sentences.kind !== 'ready') playNext = true;
      sentences = next;
      if (next.kind !== 'ready') chains.clear();
      drawSentences();
    },
  });
  const unlens = onLensChange((on) => {
    playNext = on;
    drawSentences();
  });
  // Which choice produced each check, so the sentence step asks about the same one.
  const asked = new WeakMap<SubmissionRuleCheck, SubmitChoice>();
  const loadChoice = async (choice: SubmitChoice) => {
    const check = await load(choice);
    if (check && typeof check === 'object') asked.set(check, choice);
    return check;
  };
  let open = false;
  root.addEventListener(
    'toggle',
    (event) => {
      if (event.target instanceof HTMLDetailsElement) open = event.target.open;
    },
    true,
  );
  function show(state: PresubmitState) {
    root.setAttribute('aria-busy', String(state.kind === 'loading'));
    if (state.kind === 'loading' && state.check) return;
    const view = state.kind === 'ready' ? presubmitView(state.check, language) : null;
    const note = t(
      state.kind === 'idle' ? 'choose' : state.kind === 'loading' ? 'loading' : 'failed',
    );
    body.replaceChildren(...(view ? draw(view) : [el('p', note, 'presubmit__muted')]));
    status.textContent = view ? (view.count?.text ?? view.empty ?? '') : note;
    const details = body.querySelector('details');
    if (details) details.open = open;
    pass.start(state.kind === 'ready' ? state.check : null, state.kind === 'ready' ? (asked.get(state.check) ?? null) : null);
  }
  const schedule = createPresubmitSchedule({ load: loadChoice, show });
  show({ kind: 'idle' });
  return {
    element: root,
    /** The work sentence by sentence (or the stage while it runs); placed by a split host. */
    reading: rec,
    update: schedule.request,
    destroy: () => {
      schedule.destroy();
      clearInterval(ticker);
      unlens();
    },
  };
}
