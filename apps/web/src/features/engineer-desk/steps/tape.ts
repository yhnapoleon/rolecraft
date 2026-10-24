/** S4f · The trial log: a recessed tape of runs, yours and your Agent's, newest on top. Each line:
 * time, who, what, the settings it tried as a short diff, one square per check, the public tally.
 * Opening a line shows that run's settings as a diff, then each check's expected and actual. */
import { T } from '../../../app/i18n';
import { countNode, diffList, squares } from '../bits';
import { agentNode, button, el, workLang } from '../dom';
import {
  diffShort,
  experimentRows,
  reproductionVerdict,
  settingsDiff,
  trialLine,
  type Experiment,
  type ExperimentSummary,
  type Mark,
  type TicketDetail,
} from '../model';

/** The squares of one run: per row when the whole run is here, else drawn from its counts. */
export function runMarks(
  summary: ExperimentSummary,
  full: Experiment | undefined,
  publicCount: number,
): Mark[] {
  if (full?.rows) {
    const rows = experimentRows(full).filter((r) => r.id || summary.kind === 'reproduce');
    return rows.map((r) =>
      summary.kind === 'reproduce' ? (r.mark === 'good' ? 'warn' : 'ink') : r.mark,
    );
  }
  const c = summary.counts;
  if (summary.kind === 'trial') {
    const passed = c.passed ?? 0;
    const failed = c.failed ?? 0;
    return Array.from({ length: publicCount }, (_, i) =>
      i < passed ? 'good' : i < passed + failed ? 'ink' : 'unknown',
    );
  }
  // A reproduction that matches the record means the problem is still there: amber, not green.
  return Array.from({ length: c.total ?? 0 }, (_, i) => (i < (c.matched ?? 0) ? 'warn' : 'ink'));
}

export function tapeRow(
  doc: Document,
  ticket: TicketDetail,
  summary: ExperimentSummary,
  full: Experiment | undefined,
  open: boolean,
  onToggle: () => void,
): HTMLElement {
  const publicCount = ticket.public_probes.length;
  const line = trialLine(summary, publicCount);
  const changes = full?.changes ?? summary.changes;
  const diff = changes ? settingsDiff(ticket.baseline_config, changes, ticket.editable_fields) : [];
  const short =
    summary.kind === 'reproduce'
      ? ''
      : diff.length
        ? diffShort(diff)
        : (summary.changed_fields ?? []).length
          ? (summary.changed_fields ?? []).join(' · ')
          : T('基线设置', 'Baseline settings');
  const rowsId = `ed-rows-${summary.id}`;
  const tally =
    summary.kind === 'reproduce'
      ? (() => {
          // "Still broken" is amber; "differs from the record" is a plain fact, in ink.
          const verdict = reproductionVerdict(summary, ticket);
          return el(
            doc,
            'span',
            { class: 'ed-line__tally', 'data-tone': verdict.tone },
            verdict.label,
          );
        })()
      : el(
          doc,
          'span',
          {
            class: 'ed-line__tally',
            'data-tone': (summary.counts.passed ?? 0) >= publicCount ? 'good' : 'ink',
          },
          T('公开 ', 'Public '),
          countNode(doc, summary.counts.passed ?? 0, 'ed-count'),
          `/${publicCount}`,
          T(' 通过', ' passed'),
        );
  const head = button(
    doc,
    [
      el(doc, 'time', { class: 'ed-line__time', datetime: summary.created_at }, line.time),
      el(doc, 'span', { class: 'ed-line__who' }, line.agent ? agentNode(doc) : null, line.who),
      el(doc, 'span', { class: 'ed-line__verb' }, line.verb),
      el(doc, 'span', { class: 'ed-line__fields', lang: 'en', title: short || null }, short),
      squares(doc, runMarks(summary, full, publicCount)),
      tally,
    ],
    'ed-line__head',
    { id: `ed-line-${summary.id}`, 'aria-expanded': String(open), 'aria-controls': rowsId },
  );
  head.addEventListener('click', onToggle);
  const rows = el(doc, 'div', { class: 'ed-line__rows', id: rowsId, hidden: !open });
  if (open) rows.append(lineRows(doc, ticket, summary, full, diff));
  return el(
    doc,
    'li',
    {
      class: 'ed-line',
      'data-kind': summary.kind,
      'data-id': summary.id,
      'data-agent': line.agent ? 'true' : null,
    },
    head,
    rows,
  );
}

/** A run that has been sent and not answered yet: grey dashed squares, a sentence in place of
 * the tally. */
export function pendingRow(
  doc: Document,
  ticket: TicketDetail,
  short: string,
  kind: 'trial' | 'reproduce',
) {
  const n = kind === 'trial' ? ticket.public_probes.length : ticket.target_tests.length;
  return el(
    doc,
    'li',
    { class: 'ed-line is-pending', 'data-kind': kind },
    el(
      doc,
      'div',
      { class: 'ed-line__head' },
      el(doc, 'span', { class: 'ed-line__time' }, T('现在', 'Now')),
      el(doc, 'span', { class: 'ed-line__who' }, T('你', 'You')),
      el(
        doc,
        'span',
        { class: 'ed-line__verb' },
        kind === 'trial' ? T('试跑', 'Trial') : T('复现', 'Reproduce'),
      ),
      el(doc, 'span', { class: 'ed-line__fields', lang: 'en' }, short),
      squares(
        doc,
        Array.from({ length: n }, () => 'unknown' as Mark),
      ),
      el(
        doc,
        'span',
        { class: 'ed-line__tally', 'data-tone': 'unknown' },
        kind === 'trial'
          ? T(`正在跑 ${n} 条公开检查`, `Running ${n} public checks`)
          : T('正在重跑', 'Rerunning'),
      ),
    ),
  );
}

/** A trial that did not go through: the pending row stays (grey dashed squares), the tally says
 * what went wrong, and "try again" sits at its end. */
export function failedRow(
  doc: Document,
  ticket: TicketDetail,
  short: string,
  message: string,
  retry: HTMLElement,
) {
  const row = pendingRow(doc, ticket, short, 'trial');
  row.classList.remove('is-pending');
  row.classList.add('is-failed');
  const tally = row.querySelector('.ed-line__tally') as HTMLElement;
  tally.replaceChildren(el(doc, 'span', { role: 'alert' }, message), retry);
  return row;
}

function lineRows(
  doc: Document,
  ticket: TicketDetail,
  summary: ExperimentSummary,
  full: Experiment | undefined,
  diff: ReturnType<typeof settingsDiff>,
): Node {
  const lang = workLang(ticket.work_language);
  const reproduction = summary.kind === 'reproduce';
  const settings =
    !reproduction && diff.length
      ? el(
          doc,
          'div',
          { class: 'ed-line__settings' },
          el(doc, 'p', { class: 'ed-mini' }, T('这次的设置', 'Settings this run')),
          diffList(doc, diff),
        )
      : null;
  if (!full?.rows)
    return el(
      doc,
      'div',
      {},
      settings,
      el(
        doc,
        'p',
        { class: 'ed-rows-note' },
        summary.executor.kind === 'human'
          ? T(
              '这次试验的逐行结果不在这个页面上，这里只有计数。',
              'This run’s rows aren’t on this page; only its counts are.',
            )
          : T(
              '逐行结果在你的 Agent 那里，这里只有计数。',
              'Your agent has this run’s rows; only its counts are here.',
            ),
      ),
    );
  return el(
    doc,
    'div',
    {},
    settings,
    el(
      doc,
      'ol',
      { class: 'ed-rows' },
      ...experimentRows(full).map((row) => {
        const mark: Mark = reproduction ? (row.mark === 'good' ? 'warn' : 'ink') : row.mark;
        return el(
          doc,
          'li',
          { class: 'ed-row', 'data-mark': mark },
          el(doc, 'span', { class: 'ed-square', 'data-mark': mark, 'aria-hidden': 'true' }),
          el(doc, 'span', { class: 'ed-row__id', lang: 'en' }, row.id),
          el(
            doc,
            'span',
            { class: 'ed-row__q', lang },
            row.query,
            row.target && !reproduction
              ? el(doc, 'span', { class: 'ed-chip', 'data-tone': 'outline' }, T('要修的', 'To fix'))
              : null,
          ),
          el(
            doc,
            'span',
            { class: 'ed-row__io' },
            row.expected
              ? `${reproduction ? T('记录 ', 'Recorded: ') : T('期望 ', 'Expected: ')}${row.expected} · `
              : '',
            `${reproduction ? T('复现 ', 'Rerun: ') : T('实际 ', 'Got: ')}${row.actual}`,
          ),
          el(
            doc,
            'span',
            { class: 'ed-row__verdict', 'data-mark': mark },
            reproduction
              ? row.mark === 'good'
                ? T('问题还在', 'Still broken')
                : T('和记录不同', 'Differs')
              : row.verdict,
          ),
          row.answer ? el(doc, 'p', { class: 'ed-row__answer', lang }, row.answer) : null,
        );
      }),
    ),
  );
}
