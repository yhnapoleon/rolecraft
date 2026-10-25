/** Draws an EngineerReportView as one paper sheet. Text only (textContent), no markup parsing,
 * no buttons of its own except the native "查看依据" disclosure. */
import type { EngineerReportView, EngineerTone } from './view';
import './engineer-report.css';

export interface EngineerReportRenderOptions {
  /** Heading level of the verdict; sections use the next level. Default 2. */
  readonly headingLevel?: 2 | 3 | 4;
  /** Keeps "查看依据" open across re-renders (host-owned state). */
  readonly basisOpen?: boolean;
  readonly onBasisToggle?: (open: boolean) => void;
}

/** One shape per meaning: ✓ holds, ✕ contradicts (red) or did not pass (ink), ↓ newly failing,
 * ◐ partly, an open circle still to do, a dashed circle not known yet (drawn in CSS). */
const MARK: Record<EngineerTone, string> = {
  good: '✓',
  bad: '✕',
  warn: '↓',
  unknown: '',
  ink: '◐',
};
/** An empty mark that CSS draws as an open (solid-outline) progress circle. */
const OPEN = 'open';
const SR_SEPARATOR: Record<'zh' | 'en', string> = { zh: '：', en: ': ' };

export function renderEngineerReport(
  doc: Document,
  view: EngineerReportView,
  options: EngineerReportRenderOptions = {},
): HTMLElement {
  const el = <K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text?: string) => {
    const node = doc.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const level = options.headingLevel ?? 2;
  const heading = (offset: number, className: string, text?: string) =>
    el(`h${Math.min(level + offset, 6)}` as 'h2', className, text);
  const mark = (tone: EngineerTone, className: string, glyph = MARK[tone]) => {
    const node = el('span', className, glyph === OPEN ? '' : glyph);
    node.dataset.tone = tone;
    if (glyph === OPEN) node.dataset.shape = OPEN;
    node.setAttribute('aria-hidden', 'true');
    return node;
  };
  const srOnly = (text: string) => el('span', 'sr-only', text + SR_SEPARATOR[view.language]);
  const base = `er-${view.id.replace(/[^a-z0-9-]/gi, '').slice(0, 24)}`;

  const root = el('article', 'er-report');
  root.dataset.engineerReport = view.id;
  root.lang = view.language === 'zh' ? 'zh-CN' : 'en';
  root.setAttribute('aria-labelledby', `${base}-${view.verdict ? 'verdict' : 'kind'}`);
  const queryLang = view.queryLanguage === 'zh' ? 'zh-CN' : 'en';

  // Head: what this document is, then the one conclusion that matters most (when there is one).
  const head = el('header', 'er-report__head');
  const eyebrow = el('p', 'er-report__eyebrow');
  const kind = el('span', 'er-report__kind', view.eyebrow);
  kind.setAttribute('id', `${base}-kind`);
  eyebrow.append(kind);
  for (const item of view.meta) eyebrow.append(el('span', 'er-report__meta', item));
  head.append(eyebrow);
  if (view.verdict) {
    const verdict = el('div', 'er-verdict');
    verdict.dataset.tone = view.verdict.tone;
    verdict.dataset.state = view.verdict.state;
    verdict.dataset.source = view.verdict.source;
    const verdictBody = el('div', 'er-verdict__body');
    const { title: titleText, turn } = view.verdict;
    const title = heading(0, 'er-verdict__title');
    title.setAttribute('id', `${base}-verdict`);
    // A split headline keeps one heading; only its turn ("but 1 new failure") takes the amber.
    if (turn && titleText.endsWith(turn)) {
      const turnNode = el('span', 'er-verdict__turn', turn);
      turnNode.dataset.tone = 'warn';
      title.append(titleText.slice(0, titleText.length - turn.length), turnNode);
    } else title.textContent = titleText;
    verdictBody.append(title);
    for (const query of view.verdict.targets) {
      const target = el('p', 'er-verdict__target', query);
      target.lang = queryLang;
      verdictBody.append(target);
    }
    if (view.verdict.detail) verdictBody.append(el('p', 'er-verdict__detail', view.verdict.detail));
    if (view.verdict.lines?.length) {
      const lines = el('ul', 'er-verdict__lines');
      for (const line of view.verdict.lines) {
        const item = el('li', 'er-verdict__line');
        item.dataset.tone = line.tone;
        item.append(
          // A target still failing is a known result: the ink ✕ a failed probe row uses, never
          // the open circle (which elsewhere means not known yet).
          mark(line.tone, 'er-verdict__line-mark', line.tone === 'ink' ? '✕' : MARK[line.tone]),
          el('span', 'er-verdict__line-text', line.text),
        );
        lines.append(item);
      }
      verdictBody.append(lines);
    }
    const state = view.verdict.state;
    const verdictGlyph =
      view.verdict.tone === 'warn'
        ? MARK.warn
        : state === 'not_fixed'
          ? OPEN
          : state === 'partial'
            ? '◐'
            : MARK[view.verdict.tone];
    verdict.append(mark(view.verdict.tone, 'er-verdict__mark', verdictGlyph), verdictBody);
    head.append(verdict);
  }
  root.append(head);

  const section = (name: string, titleText: string, aside?: string) => {
    const node = el('section', `er-section er-section--${name}`);
    const top = el('div', 'er-section__head');
    const h = heading(1, 'er-section__title', titleText);
    h.setAttribute('id', `${base}-${name}`);
    node.setAttribute('aria-labelledby', `${base}-${name}`);
    top.append(h);
    if (aside) top.append(el('span', 'er-section__aside', aside));
    node.append(top);
    return node;
  };

  // Public probes: one row each; failing rows say expected vs actual.
  const pub = section('public', view.publicSection.title, view.publicSection.tally);
  if (view.publicSection.sourceNote)
    pub.append(el('p', 'er-note er-note--source', view.publicSection.sourceNote));
  if (view.publicSection.empty) pub.append(el('p', 'er-note', view.publicSection.empty));
  else {
    const list = el('ol', 'er-probes');
    for (const row of view.publicSection.rows) {
      const item = el('li', 'er-probe');
      item.dataset.result = row.result;
      item.dataset.tone = row.tone;
      if (row.target) item.dataset.target = '';
      const id = el('span', 'er-probe__id');
      id.append(srOnly(row.resultText), row.id);
      const body = el('div', 'er-probe__body');
      const query = el('p', 'er-probe__query', row.query);
      query.lang = queryLang;
      body.append(query);
      if (row.tags.length) {
        const tags = el('p', 'er-probe__tags');
        for (const tag of row.tags) {
          const chip = el('span', 'er-tag', tag.text);
          chip.dataset.tone = tag.tone;
          if (tag.quiet) chip.dataset.quiet = '';
          tags.append(chip);
        }
        body.append(tags);
      }
      if (row.diff) body.append(el('p', 'er-probe__diff', row.diff));
      const rowGlyph = row.result === 'fail' ? '✕' : MARK[row.tone];
      item.append(mark(row.tone, 'er-probe__mark', rowGlyph), id, body);
      list.append(item);
    }
    pub.append(list);
  }
  root.append(pub);

  // Hidden probes: counts only.
  const hidden = section('hidden', view.hiddenSection.title);
  const counts = (rows: EngineerReportView['hiddenSection']['counts'], variant: string) => {
    const dl = el('dl', `er-counts er-counts--${variant}`);
    for (const row of rows) {
      const cell = el('div', 'er-count');
      cell.dataset.tone = row.tone;
      cell.dataset.key = row.key;
      cell.append(
        el('dt', 'er-count__label', row.label),
        el('dd', 'er-count__value', String(row.value)),
      );
      dl.append(cell);
    }
    return dl;
  };
  hidden.append(counts(view.hiddenSection.counts, 'result'));
  if (view.hiddenSection.comparison)
    hidden.append(counts(view.hiddenSection.comparison, 'comparison'));
  hidden.append(el('p', 'er-note', view.hiddenSection.note));
  root.append(hidden);

  // Rule checks: the reviewer's status, then the authored rule it applied.
  const checks = section('checks', view.checks.title);
  const checkList = el('ul', 'er-checks');
  for (const line of view.checks.lines) {
    const item = el('li', 'er-check');
    item.dataset.tone = line.tone;
    item.dataset.kind = line.kind;
    const words = el('div', 'er-check__words');
    words.append(el('p', 'er-check__status', line.status), el('p', 'er-check__rule', line.rule));
    item.append(mark(line.tone, 'er-check__mark'), words);
    checkList.append(item);
  }
  checks.append(checkList);
  root.append(checks);

  if (view.evaluation) {
    const evaluation = section('evaluation', view.evaluation.title, view.evaluation.aside);
    const list = el('ul', 'er-checks er-evaluation');
    for (const row of view.evaluation.rows) {
      const item = el('li', 'er-check er-criterion');
      item.dataset.tone = row.tone;
      item.dataset.mark = row.mark;
      item.dataset.criterion = row.id;
      const glyph =
        row.mark === 'not_applicable'
          ? '–'
          : row.mark === 'partial'
            ? '◐'
            : row.mark === 'not_met' && row.tone === 'ink'
              ? OPEN
              : MARK[row.tone];
      const body = el('div', 'er-criterion__body');
      const words = el('p', 'er-check__status');
      words.append(
        el('span', 'er-evaluation__title', row.title),
        el('span', 'er-evaluation__label', row.labelText),
      );
      body.append(words);
      if (row.reason) body.append(el('p', 'er-check__rule', row.reason));
      if (row.precheck) body.append(el('p', 'er-check__rule', row.precheck));
      if (row.probeIds.length || row.hidden) {
        const refs = el('p', 'er-criterion__refs');
        for (const id of row.probeIds) refs.append(el('span', 'er-probe__id', id));
        if (row.hidden) refs.append(el('span', 'er-criterion__hidden', row.hidden));
        body.append(refs);
      }
      if (row.fieldChecks) {
        const fields = el('details', 'er-criterion__fields');
        fields.append(el('summary', '', row.fieldChecks.label));
        const checks = el('ul', 'er-fields');
        for (const check of row.fieldChecks.rows) {
          const line = el('li', 'er-field');
          line.dataset.tone = check.tone;
          line.append(
            mark(check.tone, 'er-check__mark'),
            el(
              'span',
              check.code ? 'er-field__name er-field__name--code' : 'er-field__name',
              check.field,
            ),
            el('span', 'er-field__status', check.status),
          );
          checks.append(line);
        }
        fields.append(checks);
        body.append(fields);
      }
      item.append(mark(row.tone, 'er-check__mark', glyph), body);
      list.append(item);
    }
    evaluation.append(list);
    root.append(evaluation);
  }

  // Foot: quiet advice bar, the retrieval wording, and the identities behind the result.
  const foot = el('footer', 'er-report__foot');
  const advice = el('div', 'er-advice');
  advice.dataset.tone = view.advice.tone;
  const adviceLine = el('p', 'er-advice__line');
  adviceLine.append(
    el('span', 'er-advice__text', view.advice.text),
    el('span', 'er-advice__score', view.advice.scoreNote),
  );
  advice.append(mark(view.advice.tone, 'er-advice__mark', ''), adviceLine);
  if (view.advice.body) advice.append(el('p', 'er-advice__body', view.advice.body));
  foot.append(advice);
  // The retrieval wording sits on the same line as "查看依据", beside the identities it qualifies.
  const basisRow = el('div', 'er-report__basis');
  const details = el('details', 'er-basis');
  const summary = el('summary', 'er-basis__summary', view.basis.label);
  const list = el('dl', 'er-basis__list');
  for (const row of view.basis.rows) {
    const cell = el('div', 'er-basis__row');
    const value = el(
      'dd',
      row.code ? 'er-basis__value er-basis__value--code' : 'er-basis__value',
      row.value,
    );
    cell.append(el('dt', 'er-basis__label', row.label), value);
    list.append(cell);
  }
  details.append(summary, list);
  details.open = !!options.basisOpen;
  details.addEventListener('toggle', () => options.onBasisToggle?.(details.open));
  basisRow.append(details);
  if (view.retrievalNote)
    basisRow.append(el('p', 'er-note er-note--retrieval', view.retrievalNote));
  foot.append(basisRow);
  root.append(foot);
  return root;
}
