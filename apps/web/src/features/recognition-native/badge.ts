import { copyText, type Language } from '../results-native/localization';
import { BADGE_COPY, type BadgeKey } from './badge-copy';
import './badge.css';

/** One recognizer call as the backend records it (contracts/v2/recognition.py). */
export interface RecognitionRecord {
  recognizer_id: string;
  revision: string;
  task: string;
  label?: string | null;
  score?: number | null;
  threshold?: number | null;
  outputs?: Record<string, unknown>;
  fallback?: boolean;
  duration_ms?: number;
}

const t = (language: Language, key: BadgeKey, values: Record<string, string | number> = {}) =>
  copyText(BADGE_COPY, language, key, values);

const fmt = (value: unknown) =>
  typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '–';

const num = (value: unknown) => (typeof value === 'number' ? value : 0);

/** The signature's two parts: the recognizer's task name and its finding. */
export function describe(record: RecognitionRecord, language: Language) {
  const out = record.outputs ?? {};
  if (record.task === 'relation' && out.mode === 'support_check') {
    const verdict = String(record.label ?? 'unverified');
    const quotes = num(out.quotes);
    const parts = [
      t(language, `verdict_${verdict}` as BadgeKey),
      quotes ? t(language, 'quotes_grounded', { grounded: num(out.quotes_grounded), total: quotes }) : '',
      out.delegated_to_llm ? t(language, 'delegated') : '',
    ];
    return {
      name: t(language, 'task_support_check'),
      detail: parts.filter(Boolean).join(' · '),
      fallback: !!record.fallback,
    };
  }
  const name = t(language, `task_${record.task}` as BadgeKey);
  let detail = record.label ?? '';
  switch (record.task) {
    case 'scope':
      detail =
        t(language, record.label === 'out' ? 'scope_out' : 'scope_in') +
        (record.score != null
          ? ' · ' +
            t(language, 'distance', { score: fmt(record.score), threshold: fmt(record.threshold) })
          : '');
      break;
    case 'retrieval': {
      if (Array.isArray(out.per_sentence_top)) {
        detail = t(language, 'per_sentence', {
          method: 'rrf',
          k: num(out.k),
          n: out.per_sentence_top.length,
        });
        break;
      }
      const method = String(out.method ?? '');
      detail =
        (method ? `${method} · ` : '') +
        t(language, 'top1', { score: fmt(record.score), material: record.label ?? '–' });
      break;
    }
    case 'drift': {
      const out = (record.outputs ?? {}) as { numeric_change?: boolean; numbers_before?: string[]; numbers_after?: string[] };
      detail = out.numeric_change
        ? t(language, 'drift_numbers', {
            before: (out.numbers_before ?? []).join('/') || '–',
            after: (out.numbers_after ?? []).join('/') || '–',
            score: fmt(record.score),
          })
        : record.score != null
          ? t(language, record.label === 'anomaly' ? 'drift_anomaly' : 'drift_normal', {
              score: fmt(record.score),
            })
          : t(language, record.label === 'changed' ? 'drift_changed' : 'drift_same');
      break;
    }
    case 'intent':
      detail = `${record.label ?? '–'}${record.score != null ? ` ${fmt(record.score)}` : ''}`;
      break;
    case 'reply_check': {
      const grounded = num(out.grounded);
      const total = grounded + num(out.ungrounded);
      const leaks = num(out.leaks);
      detail =
        t(language, 'reply_grounded', { grounded, total }) +
        ' · ' +
        (leaks ? t(language, 'reply_leak', { leaks }) : t(language, 'reply_no_leak'));
      break;
    }
    case 'relation': {
      const counts = (out.counts ?? {}) as Record<string, number>;
      detail = t(language, 'relation_counts', {
        supported: num(counts.supported),
        contradicted: num(counts.contradicted),
        insufficient: num(counts.insufficient),
      });
      break;
    }
    case 'decision': {
      detail = t(language, 'decision_deferred', { deferred: num(out.deferred) });
      const lift = out.lift as { top_fraction?: number; error_coverage?: number } | null | undefined;
      if (lift && typeof lift.error_coverage === 'number' && typeof lift.top_fraction === 'number')
        detail +=
          ' · ' +
          t(language, 'decision_lift', {
            top: Math.round(lift.top_fraction * 100),
            coverage: Math.round(lift.error_coverage * 100),
          });
      break;
    }
    case 'arbiter':
      detail = out.agreement
        ? t(language, 'arbiter_agree')
        : t(language, 'arbiter_conservative', {
            recognizer: String(out.recognizer_label ?? '–'),
            judge: String(out.judge_label ?? '–'),
          });
      break;
    case 'behavior':
      detail = t(language, 'behavior_nearest', { strategy: String(record.label ?? '–') });
      break;
  }
  return { name, detail, fallback: !!record.fallback };
}

export function badgeTitle(record: RecognitionRecord, language: Language) {
  return t(language, 'title_detail', { id: record.recognizer_id, revision: record.revision });
}

function badgeText(record: RecognitionRecord, language: Language) {
  const { name, detail, fallback } = describe(record, language);
  return [name, detail, fallback ? t(language, 'fallback') : ''].filter(Boolean).join(' · ');
}

const escapeHtml = (value: string) =>
  value.replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c,
  );

/** String form for the HTML-string pages (ui.js). */
export function badgeHtml(record: RecognitionRecord, language: Language) {
  return `<span class="rc-badge" data-task="${escapeHtml(record.task)}"${record.fallback ? ' data-fallback=""' : ''} title="${escapeHtml(badgeTitle(record, language))}">${escapeHtml(badgeText(record, language))}</span>`;
}

export function badgesHtml(records: RecognitionRecord[] | null | undefined, language: Language) {
  if (!records?.length) return '';
  return `<p class="rc-badges">${records.map((r) => badgeHtml(r, language)).join('')}</p>`;
}

/** DOM form for the native slots (roles, feedback). */
export function renderBadge(doc: Document, record: RecognitionRecord, language: Language) {
  const span = doc.createElement('span');
  span.className = 'rc-badge';
  span.setAttribute('data-task', record.task);
  if (record.fallback) span.setAttribute('data-fallback', '');
  span.setAttribute('title', badgeTitle(record, language));
  span.textContent = badgeText(record, language);
  return span;
}

export function renderBadges(
  doc: Document,
  records: RecognitionRecord[] | null | undefined,
  language: Language,
) {
  const row = doc.createElement('p');
  row.className = 'rc-badges';
  for (const record of records ?? []) row.appendChild(renderBadge(doc, record, language));
  return row;
}

const SUMMARY: [string, BadgeKey][] = [
  ['scope', 'unit_times'],
  ['retrieval', 'unit_times'],
  ['relation_units', 'unit_sentences'],
  ['decision', 'unit_times'],
  ['intent', 'unit_times'],
  ['reply_check', 'unit_items'],
  ['drift', 'unit_times'],
  ['behavior', 'unit_items'],
  ['arbiter', 'unit_entries'],
];

/** "This session: scope 6 · relation 24 sentences · ..." from GET /recognition counts. */
export function summaryText(counts: Record<string, number> | null | undefined, language: Language) {
  const parts = SUMMARY.filter(([key]) => (counts?.[key] ?? 0) > 0).map(([key, unit]) =>
    t(language, 'summary_part', {
      name: t(language, `task_${key === 'relation_units' ? 'relation' : key}` as BadgeKey),
      count: counts?.[key] ?? 0,
      unit: t(language, unit),
    }).trim(),
  );
  if (!parts.length) return t(language, 'summary_empty');
  const fallback = counts?.fallback
    ? `（${t(language, 'summary_fallback', { count: counts.fallback })}）`
    : '';
  return (
    t(language, 'summary_lead') +
    parts.join(' · ') +
    (language === 'en' ? fallback.replace('（', ' (').replace('）', ')') : fallback)
  );
}
