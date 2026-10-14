/** "Recorded business decisions" of a submission's feedback, one decision per line, worded from
 * the recorded requests and decisions rather than the joined text. The stored text stays the
 * record: it is shown as written for reviews, when nothing was decided, or when the records
 * cannot be read. */
import { outcomeTerm } from '../workspace/native-v4/outcome-copy';
import { feedbackText, type FeedbackLanguage } from './localization';
import type { Report } from './index';
import './business-decisions.css';

export type DecisionRecord = {
  request: string;
  status: string;
  requested: Readonly<Record<string, number>>;
  /** Granted when approved or accepted; otherwise the counteroffer, if any. */
  result: Readonly<Record<string, number>>;
  /** Storage revision of the point the decision was taken at; it is saved right after it. */
  at: number;
};

type Row = { ref?: { kind?: unknown; object_id?: unknown }; content?: Record<string, unknown> };
const terms = (value: unknown): Record<string, number> =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? Object.fromEntries(
        Object.entries(value).filter((entry): entry is [string, number] =>
          Number.isInteger(entry[1]),
        ),
      )
    : {};

/** Decisions recorded on the workspace timeline, with the terms of the request they answer. */
export function decisionRecords(rows: readonly unknown[]): DecisionRecord[] {
  const requested = new Map<string, Record<string, number>>();
  for (const row of rows as Row[])
    if (row?.ref?.kind === 'business_request' && typeof row.ref.object_id === 'string')
      requested.set(row.ref.object_id, terms(row.content?.requested));
  const records: DecisionRecord[] = [];
  for (const row of rows as Row[]) {
    const content = row?.content;
    if (row?.ref?.kind !== 'business_decision' || !content) continue;
    const request = (content.request as { object_id?: unknown } | undefined)?.object_id;
    const at = (content.as_of as { storage_revision?: unknown } | undefined)?.storage_revision;
    if (typeof request !== 'string' || typeof content.status !== 'string') continue;
    if (!Number.isInteger(at) || !requested.has(request)) continue;
    records.push({
      request,
      status: content.status,
      requested: requested.get(request) ?? {},
      result: terms(
        ['approved', 'accepted'].includes(content.status) ? content.granted : content.countered,
      ),
      at: at as number,
    });
  }
  return records;
}

/** The latest decision of each request saved before the feedback point, in request order. */
export function decisionsAt(
  records: readonly DecisionRecord[],
  point: { storage_revision: number },
): DecisionRecord[] {
  const latest = new Map<string, DecisionRecord>();
  for (const record of records) {
    if (record.at >= point.storage_revision) continue;
    const prior = latest.get(record.request);
    if (!prior || record.at > prior.at) latest.set(record.request, record);
  }
  return [...latest.values()];
}

export function decisionLines(
  records: readonly DecisionRecord[],
  language: FeedbackLanguage,
): string[] {
  const T = (zh: string, en: string) => feedbackText(language, zh, en);
  const list = (values: Readonly<Record<string, number>>) =>
    Object.entries(values)
      .map(([key, value]) => `${outcomeTerm(language, 'resource', key)} ${value}`)
      .join(T('、', ', '));
  return records.map((record) => {
    const result = list(record.result);
    return (
      T('申请 ', 'Requested ') +
      list(record.requested) +
      ' → ' +
      outcomeTerm(language, 'status', record.status) +
      (result ? T('：', ': ') + result : '')
    );
  });
}

export function renderDecisions(
  doc: Document,
  report: Report,
  records: readonly DecisionRecord[] | undefined,
  language: FeedbackLanguage,
): HTMLElement {
  const point = report.as_of;
  const rows =
    report.subject.kind === 'submission' && records && point ? decisionsAt(records, point) : [];
  if (!rows.length) {
    const stored = doc.createElement('p');
    stored.className = 'rule-detail';
    stored.textContent = report.business_response;
    return stored;
  }
  const section = doc.createElement('section');
  section.className = 'business-decisions';
  const heading = doc.createElement('h3');
  heading.textContent = feedbackText(
    language,
    '已记录的业务决定（规则核实）',
    'Recorded business decisions (rule checked)',
  );
  const list = doc.createElement('ul');
  for (const line of decisionLines(rows, language)) {
    const item = doc.createElement('li');
    item.textContent = line;
    list.append(item);
  }
  section.append(heading, list);
  return section;
}
