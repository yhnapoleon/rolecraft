/** Recognition signals on learner pages. Lens closed (the default): only plain facts a learner
 * can use, usually nothing. Lens open: one chip per recognizer call with the finding in plain
 * words, its course category and a short confidence bar (never a decimal). Both an HTML string
 * form (ui.js pages) and a DOM form (native slots) are built from the same pure description. */
import { copyText, type Language } from '../results-native/localization';
import { strategyName } from '../behavior-native/view';
import { arbiterOutcome, type RecognitionRecord } from './badge';
import { LENS_COPY, type LensKey } from './lens-copy';
import { actualMethod } from './actual-method';
import { type CardOptions, cardHtml, cardProvenance } from './profile-card';
import type { SplitExplanation } from './prefix';
import './signals.css';
import './reading.css';

export type SignalContext = 'test' | 'reply' | 'feedback' | 'criterion';
export type SignalOptions = {
  context: SignalContext;
  lens: boolean;
  /** Material titles for retrieval hits; identifiers are never shown. */
  materialName?: (id: string) => string;
  /** Lens chips open their profile card in place (phase 2): this call's own numbers, its
   * method and course family, the published figures. Without it the chips are plain labels. */
  cards?: CardOptions;
};
export type Meter = { value: number; tick?: number; label: string };
export type LensSignal = {
  task: string;
  text: string;
  category: string;
  method: string;
  meter: Meter | null;
  tone: 'good' | 'bad' | 'unknown' | 'ink';
  fallback: boolean;
};

const t = (language: Language, key: LensKey, values: Record<string, string | number> = {}) =>
  copyText(LENS_COPY, language, key, values);
const num = (value: unknown) => (typeof value === 'number' && Number.isFinite(value) ? value : 0);
const clamp = (value: number) => Math.max(0, Math.min(1, value));

/** A probability as a bar with a word for screen readers. */
export function sureMeter(p: number, language: Language): Meter {
  return { value: clamp(p), label: t(language, p >= 0.8 ? 'sure_high' : p >= 0.6 ? 'sure_mid' : 'sure_low') };
}
/** A distance against its threshold: the bar spans 1.5 × threshold and the tick marks it. */
function thresholdMeter(score: unknown, threshold: unknown, label: string): Meter | null {
  if (typeof score !== 'number' || typeof threshold !== 'number' || threshold <= 0) return null;
  return { value: clamp(score / (threshold * 1.5)), tick: 1 / 1.5, label };
}

export const categoryOf = (record: RecognitionRecord, language: Language) => actualMethod(record, language).category;
const methodOf = (record: RecognitionRecord, language: Language) => actualMethod(record, language).method;

const INTENTS = new Set(['ask_limit', 'ask_resource', 'ask_process', 'seek_approval', 'other']);

/** The lens chip of one record. */
export function lensSignal(
  record: RecognitionRecord,
  language: Language,
  materialName: (id: string) => string = (id) => id,
): LensSignal {
  const out = record.outputs ?? {};
  let text = '';
  let meter: Meter | null = null;
  let tone: LensSignal['tone'] = 'ink';
  switch (record.task) {
    case 'scope':
      text = t(language, record.label === 'out' ? 'scope_out' : 'scope_in');
      meter = thresholdMeter(record.score, record.threshold, t(language, 'distance'));
      break;
    case 'drift': {
      const before = ((out.numbers_before ?? []) as string[]).join('/');
      const after = ((out.numbers_after ?? []) as string[]).join('/');
      text = out.numeric_change
        ? t(language, 'drift_numbers', { before: before || '–', after: after || '–' })
        : t(language, record.label === 'anomaly' || record.label === 'changed' ? 'drift_changed' : 'drift_same');
      meter = thresholdMeter(record.score, record.threshold, t(language, 'change'));
      break;
    }
    case 'retrieval':
      if (Array.isArray(out.per_sentence_top))
        text = t(language, 'retrieval_sentences', { n: out.per_sentence_top.length, k: num(out.k) });
      else {
        text = record.label
          ? t(language, 'retrieval_top', { material: materialName(String(record.label)) })
          : t(language, 'retrieval_none');
        if (typeof record.score === 'number' && record.score <= 1) meter = sureMeter(record.score, language);
      }
      break;
    case 'intent': {
      const label = String(record.label ?? 'other');
      text = t(language, 'intent', {
        intent: INTENTS.has(label) ? t(language, `intent_${label}` as LensKey) : label,
      });
      if (typeof record.score === 'number') meter = sureMeter(record.score, language);
      break;
    }
    case 'reply_check': {
      const grounded = num(out.grounded);
      const leaks = num(out.leaks);
      text = `${t(language, 'reply_grounded', { grounded, total: grounded + num(out.ungrounded) })} · ${
        leaks ? t(language, 'reply_leak', { leaks }) : t(language, 'reply_no_leak')
      }`;
      if (leaks) tone = 'bad';
      break;
    }
    case 'relation': {
      if (out.mode === 'support_check') {
        const verdict = String(record.label ?? 'unverified');
        const quotes = num(out.quotes);
        text = [
          t(language, verdict === 'supported' ? 'support_supported' : verdict === 'unsupported' ? 'support_unsupported' : 'support_unverified'),
          quotes ? t(language, 'support_quotes', { grounded: num(out.quotes_grounded), total: quotes }) : '',
          out.delegated_to_llm ? t(language, 'support_delegated') : '',
        ]
          .filter(Boolean)
          .join(' · ');
        tone = verdict === 'supported' ? 'good' : verdict === 'unsupported' ? 'bad' : 'unknown';
        break;
      }
      const counts = (out.counts ?? {}) as Record<string, number>;
      text = t(language, 'relation_counts', {
        s: num(counts.supported),
        c: num(counts.contradicted),
        u: num(counts.insufficient) + num(counts.deferred),
      });
      break;
    }
    case 'decision': {
      text = t(language, 'decision_deferred', { n: num(out.deferred) });
      const lift = out.lift as { top_fraction?: number; error_coverage?: number } | null | undefined;
      if (lift && typeof lift.top_fraction === 'number' && typeof lift.error_coverage === 'number')
        text += ` · ${t(language, 'decision_lift', {
          top: Math.round(lift.top_fraction * 100),
          coverage: Math.round(lift.error_coverage * 100),
        })}`;
      break;
    }
    case 'arbiter':
      text = t(language, `arbiter_${arbiterOutcome(record)}` as LensKey);
      break;
    case 'behavior':
      text = record.label
        ? t(language, 'behavior_nearest', { strategy: strategyName(String(record.label), language) })
        : t(language, 'behavior_none');
      break;
    default:
      text = String(record.label ?? '');
  }
  return {
    task: record.task,
    text,
    category: categoryOf(record, language),
    method: methodOf(record, language),
    meter,
    tone,
    fallback: !!record.fallback,
  };
}

/** Lens closed: the few facts worth a learner's attention. A test whose answer's numbers
 * changed says so (the world changed under it); everything else stays silent. Out-of-scope
 * questions are not repeated: the answer itself already hands them off. */
export function quietLines(records: RecognitionRecord[], language: Language, context: SignalContext): string[] {
  if (context !== 'test') return [];
  return records
    .filter((r) => r.task === 'drift' && r.outputs?.numeric_change)
    .map((r) =>
      t(language, 'quiet_numbers', {
        before: ((r.outputs?.numbers_before ?? []) as string[]).join('/') || '–',
        after: ((r.outputs?.numbers_after ?? []) as string[]).join('/') || '–',
      }),
    );
}

const esc = (value: string) =>
  value.replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c,
  );
const pct = (value: number) => `${Math.round(value * 100)}%`;

/** A short bar; its value is in the label for screen readers, never printed. */
export function meterHtml(meter: Meter) {
  return `<span class="rc-meter" role="img" aria-label="${esc(meter.label)}" title="${esc(meter.label)}"><i style="inline-size:${pct(meter.value)}"></i>${meter.tick != null ? `<b style="inset-inline-start:${pct(meter.tick)}"></b>` : ''}</span>`;
}

/** A chip that opens its card: the same label as a button, with the method shown after the
 * family (method · family is the one tech label every moment uses). */
export function cardChipHtml(signal: LensSignal, language: Language, cardId: string, provenance = '') {
  const family = [signal.category, signal.method, signal.fallback ? t(language, 'fallback') : '', provenance]
    .filter(Boolean)
    .join(' · ');
  return `<button type="button" class="rc-sig rc-sig--key" data-task="${esc(signal.task)}" data-tone="${signal.tone}"${signal.fallback ? ' data-fallback=""' : ''} aria-expanded="false" aria-controls="${cardId}" data-rc-card="${cardId}"><span class="rc-sig__text">${esc(signal.text)}</span>${signal.meter ? meterHtml(signal.meter) : ''}<span class="rc-cat">${esc(family)}</span><svg class="rc-sig__chev" viewBox="0 0 16 16" aria-hidden="true"><path d="m5 6.5 3 3 3-3"/></svg></button>`;
}

let cardSeq = 0;
/** Chips that open cards, and the cards (hidden until opened) right under the row. */
export function cardsHtml(records: RecognitionRecord[], language: Language, options: SignalOptions) {
  const cardOptions = { source: options.context === 'feedback' || options.context === 'criterion' ? 'delivery' as const : 'saved' as const, ...options.cards };
  const ids = records.map(() => `rc-card-${++cardSeq}`);
  const chips = records
    .map((r, i) => cardChipHtml(lensSignal(r, language, options.materialName), language, ids[i], cardProvenance(language, cardOptions)))
    .join('');
  const cards = records
    .map(
      (r, i) =>
        `<div class="rc-card-slot" id="${ids[i]}" hidden>${cardHtml(r, language, { materialName: options.materialName, ...cardOptions })}</div>`,
    )
    .join('');
  return `<div class="rc-sigs-wrap"><p class="rc-sigs">${chips}</p>${cards}</div>`;
}

export function chipHtml(signal: LensSignal, language: Language) {
  return `<span class="rc-sig" data-task="${esc(signal.task)}" data-tone="${signal.tone}"${signal.fallback ? ' data-fallback=""' : ''} title="${esc(signal.method)}"><span class="rc-sig__text">${esc(signal.text)}</span>${signal.meter ? meterHtml(signal.meter) : ''}<span class="rc-cat">${esc(signal.fallback ? `${signal.category} · ${t(language, 'fallback')}` : signal.category)}</span></span>`;
}

/** The HTML string form: lens chips, quiet lines, or '' when there is nothing to say. */
export function signalsHtml(
  records: RecognitionRecord[] | null | undefined,
  language: Language,
  options: SignalOptions,
) {
  if (!records?.length) return '';
  if (options.lens && options.cards) return cardsHtml(records, language, options);
  if (options.lens)
    return `<p class="rc-sigs">${records.map((r) => chipHtml(lensSignal(r, language, options.materialName), language)).join('')}</p>`;
  const lines = quietLines(records, language, options.context);
  return lines.length ? lines.map((line) => `<p class="rc-quiet">${esc(line)}</p>`).join('') : '';
}

export function renderMeter(doc: Document, meter: Meter) {
  const bar = doc.createElement('span');
  bar.className = 'rc-meter';
  bar.setAttribute('role', 'img');
  bar.setAttribute('aria-label', meter.label);
  bar.setAttribute('title', meter.label);
  const fill = doc.createElement('i');
  fill.setAttribute('style', `inline-size:${pct(meter.value)}`);
  bar.append(fill);
  if (meter.tick != null) {
    const tick = doc.createElement('b');
    tick.setAttribute('style', `inset-inline-start:${pct(meter.tick)}`);
    bar.append(tick);
  }
  return bar;
}

export function renderChip(doc: Document, signal: LensSignal, language: Language) {
  const chip = doc.createElement('span');
  chip.className = 'rc-sig';
  chip.setAttribute('data-task', signal.task);
  chip.setAttribute('data-tone', signal.tone);
  if (signal.fallback) chip.setAttribute('data-fallback', '');
  chip.setAttribute('title', signal.method);
  const text = doc.createElement('span');
  text.className = 'rc-sig__text';
  text.textContent = signal.text;
  chip.append(text);
  if (signal.meter) chip.append(renderMeter(doc, signal.meter));
  const category = doc.createElement('span');
  category.className = 'rc-cat';
  category.textContent = signal.fallback ? `${signal.category} · ${t(language, 'fallback')}` : signal.category;
  chip.append(category);
  return chip;
}

/** The DOM form for native slots; null when there is nothing to show. */
export function renderSignals(
  doc: Document,
  records: RecognitionRecord[] | null | undefined,
  language: Language,
  options: SignalOptions,
): HTMLElement | null {
  if (!records?.length) return null;
  if (options.lens && options.cards) {
    const box = doc.createElement('div');
    box.innerHTML = cardsHtml(records, language, options);
    return (box.firstElementChild as HTMLElement | null) ?? box;
  }
  if (options.lens) {
    const row = doc.createElement('p');
    row.className = 'rc-sigs';
    for (const record of records) row.append(renderChip(doc, lensSignal(record, language, options.materialName), language));
    return row;
  }
  const lines = quietLines(records, language, options.context);
  if (!lines.length) return null;
  const box = doc.createElement('div');
  for (const line of lines) {
    const p = doc.createElement('p');
    p.className = 'rc-quiet';
    p.textContent = line;
    box.append(p);
  }
  return box;
}

/** The reviewer's recognition tag as a quiet label (lens only). A disagreement opens to its
 * reason; the arbiter's own note, when the backend wrote one in front, opens the same way. */
export function renderExplanationTag(
  doc: Document,
  split: SplitExplanation,
  language: Language,
): HTMLElement | null {
  if (!split.tag && !split.arbiter) return null;
  const tag = doc.createElement('span');
  tag.className = 'rc-tag';
  tag.setAttribute('data-tag', split.tag ?? 'arbiter');
  tag.textContent = split.tag ? t(language, `tag_${split.tag}` as LensKey) : t(language, 'm_arbiter');
  const notes = [split.reason ? t(language, 'tag_reason', { reason: split.reason }) : '', split.arbiter ?? ''].filter(
    Boolean,
  );
  if (!notes.length) {
    const line = doc.createElement('p');
    line.className = 'rc-tag-line';
    line.append(tag);
    return line;
  }
  const box = doc.createElement('details');
  box.className = 'rc-tag-box';
  const summary = doc.createElement('summary');
  summary.append(tag);
  box.append(summary);
  for (const note of notes) {
    const p = doc.createElement('p');
    p.textContent = note;
    box.append(p);
  }
  return box;
}
