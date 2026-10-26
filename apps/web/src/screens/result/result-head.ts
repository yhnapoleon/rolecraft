/** The result page's first screen: one stamped sheet of paper that answers "did this delivery
 * fail anywhere?" before anything else. The decision as a stamp with its time; the delivery and
 * its attached versions; three large readings in the page's order (didn't hold up, can't tell
 * yet, holds up), each a way to its group below; and one line against the previous delivery.
 * While the review is written (15–100 s) the stamp is already on and the real steps stand in
 * for the readings, with the real time spent. Counts come from the stored review as it is; no
 * total score is formed. */
import { attachmentSlip } from '../../features/feedback-native/delivery';
import { createStamp } from '../../shared/stamp/stamp';
import { feedbackText, type FeedbackLanguage } from '../../features/feedback-native/localization';
import type {
  CoverActions,
  CoverChange,
  CoverMark,
  CoverView,
} from '../../features/feedback-native/result-cover';
import type { FeedbackNativeState } from '../../features/feedback-native';
import './result.css';

export type ResultGroup = 'unmet' | 'unknown' | 'met';
export interface ResultHeadActions extends CoverActions {
  /** Show one group of the detail below (switching to "By status" when needed). */
  locate?: (group: ResultGroup) => void;
}
export interface ResultWait {
  phase?: FeedbackNativeState['feedbackPhase'];
  seconds?: number;
  reading?: boolean;
  freshStamp?: boolean;
  pressElapsed?: number;
}

/** "0:42", "1:05": the real time spent, as a clock (never a percentage). */
export function clockWords(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/** The three readings' words, in the page's order. */
export function readingWords(language: FeedbackLanguage) {
  const T = (zh: string, en: string) => feedbackText(language, zh, en);
  return {
    unmet: {
      label: T('没站住', 'Didn’t hold up'),
      note: T('先处理这些', 'Deal with these first'),
      none: T('规则没有判出不成立的项', 'Nothing failed the rules'),
    },
    unknown: {
      label: T('还不知道', 'Can’t tell yet'),
      note: T('可以补充依据', 'You can add evidence'),
    },
    met: { label: T('站得住', 'Holds up'), note: T('规则核实过', 'Checked by the rules') },
  } as const;
}

/** One line against the previous delivery: the same, or what moved. */
export function compareWords(
  compare: NonNullable<CoverView['compare']>,
  language: FeedbackLanguage,
): string {
  const T = (zh: string, en: string) => feedbackText(language, zh, en);
  const n = compare.previous;
  const which = Number.isFinite(n)
    ? T(`第 ${n} 次交付`, `delivery ${n}`)
    : T('上次交付', 'the previous delivery');
  if (!compare.changes.length)
    return Number.isFinite(n)
      ? T(`和第 ${n} 次交付结果相同`, `Same as delivery ${n}`)
      : T('和上次交付结果相同', 'Same as the previous delivery');
  const k = compare.changes.length;
  return T(
    `和${which}相比，${k} 项有变化`,
    `${k} ${k === 1 ? 'item' : 'items'} changed since ${which}`,
  );
}

const GLYPH: Record<CoverMark, string> = { met: '✓', unmet: '✕', unknown: '?', na: '—' };

export function renderResultHead(
  doc: Document,
  view: CoverView,
  language: FeedbackLanguage,
  actions: ResultHeadActions,
  wait: ResultWait = {},
): HTMLElement {
  const T = (zh: string, en: string) => feedbackText(language, zh, en);
  const el = <K extends keyof HTMLElementTagNameMap>(tag: K, text = '', cls = '') => {
    const node = doc.createElement(tag);
    if (text) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  };
  const paper = el('section', '', 'result-paper');
  // Kept for the tools and tests that find the cover by this mark.
  paper.dataset.resultCover = '';
  paper.dataset.state = view.waiting ? (view.failed ? 'failed' : 'waiting') : 'ready';
  paper.setAttribute('aria-label', T('这次交付的结果', 'Result of this delivery'));

  // The stamp, the delivery and what was attached.
  const top = el('div', '', 'result-paper__top');
  const stamp = createStamp(doc, {
    kicker: T('已交付', 'Submitted'),
    text: view.decision,
    when: view.when || undefined,
    tone: 'good',
    size: 'lg',
    hidden: !!wait.freshStamp,
  });
  // Kept so a redraw finds the stamp already on the page and never restarts its press.
  stamp.dataset.deliveryStamp = '';
  stamp.classList.add('result-paper__stamp');
  const facts = el('div', '', 'result-paper__facts');
  const title = el(
    'h2',
    Number.isFinite(view.delivery)
      ? T(`第 ${view.delivery} 次交付`, `Delivery ${view.delivery}`)
      : T('这次交付', 'This delivery'),
    'result-paper__title',
  );
  // The cover's old title class stays for focus handling across redraws.
  title.classList.add('result-cover__title');
  facts.append(title);
  if (view.attachments.length) {
    const list = el('ul', '', 'result-paper__attachments');
    list.setAttribute('aria-label', T('附上的作品', 'Attached work'));
    for (const item of view.attachments) {
      const row = el('li', '', 'result-paper__attachment');
      const parts = attachmentSlip(doc, item.product, language, 'button');
      parts.slip.addEventListener('click', () => actions.openReference(item.ref));
      parts.slip.dataset.referenceKind = item.ref.kind;
      parts.slip.setAttribute('aria-label', T('打开附件：', 'Open attachment: ') + item.line);
      row.append(parts);
      list.append(row);
    }
    facts.append(list);
  }
  top.append(stamp, facts);
  paper.append(top);

  if (view.waiting) {
    paper.append(waitingPart(doc, view, language, wait));
    return paper;
  }

  // Three readings, a way to each group below.
  const words = readingWords(language);
  const readings = el('div', '', 'result-readings');
  readings.setAttribute('role', 'group');
  readings.setAttribute('aria-label', T('结果计数', 'Result counts'));
  const counts: Record<ResultGroup, number> = {
    unmet: view.unmet.length,
    unknown: view.unknown.length,
    met: view.met.length,
  };
  for (const group of ['unmet', 'unknown', 'met'] as const) {
    const n = counts[group];
    const reading = el('button', '', 'result-reading');
    reading.type = 'button';
    reading.dataset.group = group;
    reading.dataset.zero = String(n === 0);
    reading.setAttribute('aria-label', `${words[group].label} ${n}`);
    const num = el('span', String(n), 'result-reading__n');
    num.dataset.value = String(n);
    num.setAttribute('aria-hidden', 'true');
    const label = el('span', words[group].label, 'result-reading__label');
    label.setAttribute('aria-hidden', 'true');
    const zero = group === 'unmet' ? words.unmet.none : '';
    const note = el('span', n ? words[group].note : zero, 'result-reading__note');
    note.setAttribute('aria-hidden', 'true');
    reading.append(num, label, note);
    if (actions.locate && n) reading.addEventListener('click', () => actions.locate?.(group));
    else reading.disabled = true;
    readings.append(reading);
  }
  paper.append(readings);

  // Against the previous delivery: one line; what moved opens under it.
  if (view.compare) {
    const foot = el('div', '', 'result-paper__compare');
    foot.dataset.changed = String(view.compare.changes.length);
    const line = el('p', '', 'result-paper__compare-line');
    const mark = el('span', view.compare.changes.length ? '↻' : '=', 'result-paper__compare-mark');
    mark.setAttribute('aria-hidden', 'true');
    line.append(mark, el('span', compareWords(view.compare, language)));
    foot.append(line);
    if (view.compare.changes.length) foot.append(changeList(doc, view.compare.changes, language));
    paper.append(foot);
  }
  return paper;
}

function changeList(doc: Document, changes: CoverChange[], language: FeedbackLanguage) {
  const T = (zh: string, en: string) => feedbackText(language, zh, en);
  const said: Record<CoverMark, string> = {
    met: T('站得住', 'holds up'),
    unmet: T('没站住', 'didn’t hold up'),
    unknown: T('还不知道', 'can’t tell yet'),
    na: T('不适用', 'doesn’t apply'),
  };
  const ul = doc.createElement('ul');
  ul.className = 'result-paper__changes';
  for (const change of changes) {
    const li = doc.createElement('li');
    li.dataset.criterion = change.criterion;
    li.dataset.to = change.to;
    const pair = doc.createElement('span');
    pair.className = 'result-paper__pair';
    pair.setAttribute('aria-hidden', 'true');
    for (const [mark, cls] of [
      [change.from, 'is-from'],
      ['→', 'is-arrow'],
      [change.to, 'is-to'],
    ] as const) {
      const span = doc.createElement('span');
      span.textContent = mark === '→' ? '→' : GLYPH[mark as CoverMark];
      span.className = `result-mark ${cls}`;
      if (mark !== '→') span.dataset.mark = mark;
      pair.append(span);
    }
    const name = doc.createElement('span');
    name.textContent = change.name;
    const sr = doc.createElement('span');
    sr.className = 'sr-only';
    sr.textContent = T(
      `：${said[change.from]}变为${said[change.to]}`,
      `: ${said[change.from]} to ${said[change.to]}`,
    );
    li.append(pair, name, sr);
    ul.append(li);
  }
  return ul;
}

/** Only name stages actually reported by the server; a slow read is a separate wait. */
export function resultWaitWords(language: FeedbackLanguage, wait: ResultWait): string {
  const T = (zh: string, en: string) => feedbackText(language, zh, en);
  if (wait.phase === 'running') return T('评审正在生成反馈。', 'The reviewer is writing the feedback.');
  if (wait.phase === 'queued') return T('交付已记录，正在等待评审。', 'The delivery is recorded and waiting for the reviewer.');
  return wait.reading
    ? T('交付已记录，正在读取反馈。', 'The delivery is recorded. Reading the feedback.')
    : T('交付已记录，反馈尚未就绪。', 'The delivery is recorded; feedback is not ready yet.');
}

/** The wait, told by what really happened: recorded, then the queue and the reviewer as the
 * server reports them. Only the current step glows; the clock counts real seconds. */
function waitingPart(doc: Document, view: CoverView, language: FeedbackLanguage, wait: ResultWait) {
  const T = (zh: string, en: string) => feedbackText(language, zh, en);
  const box = doc.createElement('div');
  box.className = 'result-wait';
  box.dataset.feedbackWait = wait.phase ?? '';
  if (view.failed) {
    const p = doc.createElement('p');
    p.className = 'result-wait__failed';
    p.textContent = T(
      '反馈这次没有生成，交付仍保留。',
      'The feedback did not complete; the delivery is kept.',
    );
    box.append(p);
    return box;
  }
  type Step = { id: string; label: string; state: 'done' | 'now' | 'next' };
  const running = wait.phase === 'running';
  const queued = wait.phase === 'queued';
  const steps: Step[] = [
    {
      id: 'recorded',
      label: view.confirming
        ? T('正在记录交付', 'Recording the delivery')
        : T('已记录', 'Recorded'),
      state: view.confirming ? 'now' : 'done',
    },
    {
      id: 'queued',
      label: running ? T('已排上', 'Queued') : T('排队等评审', 'Waiting for the reviewer'),
      state: view.confirming ? 'next' : running ? 'done' : queued ? 'now' : 'next',
    },
    {
      id: 'reviewer',
      label: T('评审在写', 'Reviewer writing'),
      state: running ? 'now' : 'next',
    },
  ];
  const list = doc.createElement('ol');
  list.className = 'result-wait__steps';
  list.setAttribute('aria-label', T('反馈的进展', 'Feedback progress'));
  for (const step of steps) {
    const li = doc.createElement('li');
    li.className = 'result-wait__step';
    li.dataset.state = step.state;
    li.dataset.step = step.id;
    if (step.state === 'now') li.setAttribute('aria-current', 'step');
    const dot = doc.createElement('span');
    dot.className = 'result-wait__dot';
    dot.setAttribute('aria-hidden', 'true');
    dot.textContent = step.state === 'done' ? '✓' : '';
    const label = doc.createElement('span');
    label.className = 'result-wait__label';
    label.textContent =
      step.state === 'now' && step.id !== 'recorded' ? `${step.label}…` : step.label;
    li.append(dot, label);
    list.append(li);
  }
  const row = doc.createElement('div');
  row.className = 'result-wait__row';
  row.append(list);
  if (Number.isFinite(wait.seconds)) {
    const clock = doc.createElement('span');
    clock.className = 'result-wait__clock';
    clock.dataset.elapsed = '';
    clock.textContent = clockWords(wait.seconds ?? 0);
    clock.setAttribute('aria-label', T('已用时间', 'Time spent'));
    row.append(clock);
  }
  const hint = doc.createElement('p');
  hint.className = 'result-wait__hint';
  hint.textContent = resultWaitWords(language, wait) + T(
    '可以先回工作板，结果到了会告诉你。',
    ' You can go back to the board; you’ll be told when it’s ready.',
  );
  const back = doc.createElement('button');
  back.type = 'button';
  back.className = 'btn small';
  back.dataset.action = 'to-board';
  back.textContent = T('回工作板', 'Back to the board');
  const tail = doc.createElement('div');
  tail.className = 'result-wait__tail';
  tail.append(hint, back);
  box.append(row, tail);
  return box;
}

/** Before the records are read: the sheet's shape, quiet, so the page does not jump when the
 * result arrives. No words are guessed. */
export function renderResultSkeleton(doc: Document, language: FeedbackLanguage): HTMLElement {
  const paper = doc.createElement('section');
  paper.className = 'result-paper is-skeleton';
  paper.setAttribute('aria-busy', 'true');
  paper.setAttribute('aria-label', feedbackText(language, '正在读取结果', 'Reading the result'));
  const top = doc.createElement('div');
  top.className = 'result-paper__top';
  for (const cls of ['result-skel result-skel--stamp', 'result-skel result-skel--title']) {
    const block = doc.createElement('span');
    block.className = cls;
    top.append(block);
  }
  const readings = doc.createElement('div');
  readings.className = 'result-readings';
  for (let i = 0; i < 3; i++) {
    const cell = doc.createElement('div');
    cell.className = 'result-reading';
    const n = doc.createElement('span');
    n.className = 'result-skel result-skel--n';
    const label = doc.createElement('span');
    label.className = 'result-skel result-skel--label';
    cell.append(n, label);
    readings.append(cell);
  }
  paper.append(top, readings);
  return paper;
}
