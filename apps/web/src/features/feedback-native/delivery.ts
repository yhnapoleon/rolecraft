/** How the feedback panel names a delivery's saved snapshot. The delivery's own name ("第 2 次
 * 交付", "Delivery 2") comes from the practice catalog that names every evidence button and the
 * reader, numbered by submitted events, so one delivery reads the same everywhere. */
import { referenceLabel, type ReferenceCatalog, type ReferenceKey } from '../../reference-catalog';
import { feedbackCopy, type FeedbackLanguage } from './localization';
import './delivery.css';

const deliveryOf = (ref: ReferenceKey, catalog: ReferenceCatalog, language: FeedbackLanguage) =>
  catalog.deliveries[ref.object_id] === undefined
    ? undefined
    : referenceLabel(ref, catalog, language).text;

/** The history entry that opens a delivery's snapshot. */
export function snapshotName(
  ref: ReferenceKey,
  catalog: ReferenceCatalog,
  language: FeedbackLanguage,
): string {
  const delivery = deliveryOf(ref, catalog, language);
  return delivery === undefined
    ? feedbackCopy(language, 'deliverySnapshotUnnumbered')
    : feedbackCopy(language, 'deliverySnapshot', { delivery });
}

/** The heading over the exact versions a delivery saved. */
export function snapshotHeading(
  ref: ReferenceKey,
  catalog: ReferenceCatalog,
  language: FeedbackLanguage,
): string {
  const delivery = deliveryOf(ref, catalog, language);
  return delivery === undefined
    ? feedbackCopy(language, 'deliverySnapshotHeadingUnnumbered')
    : feedbackCopy(language, 'deliverySnapshotHeading', { delivery });
}

const PURPOSES: Record<string, [string, string]> = {
  exploration: ['探索笔记', 'Exploration note'],
  test_plan: ['测试计划', 'Test plan'],
  option: ['方案比较', 'Option comparison'],
  commitment: ['试点决定', 'Pilot decision'],
  free_form: ['自由作品', 'Free-form'],
  freeform: ['自由作品', 'Free-form'],
  result: ['结果报告', 'Result report'],
};
/** A work's purpose in the panel language; an unrecognised purpose stays as written. */
export function purposeWords(purpose: string | undefined, language: FeedbackLanguage): string {
  const words = purpose ? PURPOSES[purpose] : undefined;
  return words ? (language === 'en' ? words[1] : words[0]) : (purpose ?? '');
}
/** "第 N 版" / "version N", the one way a work version is named. */
export const versionWords = (n: number, language: FeedbackLanguage) =>
  language === 'en' ? `version ${n}` : `第 ${n} 版`;

/** The parts of a work version as a paper attachment: title, version and purpose. */
export function attachmentParts(
  product: { title?: string | null; version: number; purpose?: string },
  language: FeedbackLanguage,
): string[] {
  const title = product.title || (language === 'en' ? 'Untitled work' : '未命名作品');
  const purpose = purposeWords(product.purpose, language);
  return [
    language === 'en' ? `“${title}”` : `《${title}》`,
    versionWords(product.version, language),
    ...(purpose ? [purpose] : []),
  ];
}
/** A work version as a paper attachment: 《标题》 · 第 N 版 · 用途 / “Title” · version N · purpose. */
export function attachmentLine(
  product: { title?: string | null; version: number; purpose?: string },
  language: FeedbackLanguage,
): string {
  return attachmentParts(product, language).join(' · ');
}
/** The attachment line as text whose version and purpose never break inside themselves. */
export function attachmentText(
  doc: Document,
  product: { title?: string | null; version: number; purpose?: string },
  language: FeedbackLanguage,
): DocumentFragment {
  const out = doc.createDocumentFragment();
  attachmentParts(product, language).forEach((part, i) => {
    if (i) out.append(' · ');
    const span = doc.createElement('span');
    span.textContent = part;
    if (i) span.className = 'attachment-part';
    out.append(span);
  });
  return out;
}

/** The delivery time as people read it on a stamp: today shows the time, other days the date. */
export function stampTime(at: string | undefined, language: FeedbackLanguage, now = new Date()) {
  const when = at ? new Date(at) : null;
  if (!when || Number.isNaN(when.getTime())) return '';
  const locale = language === 'en' ? 'en-GB' : 'zh-CN';
  const sameDay = when.toDateString() === now.toDateString();
  const time = when.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' });
  if (sameDay) return time;
  const date = when.toLocaleDateString(locale, { month: 'short', day: 'numeric' });
  return `${date} ${time}`;
}

/** The delivered stamp: "已交付", the decision in words, and when. `fresh` plays the press once. */
export function deliveryStamp(
  doc: Document,
  input: { decision: string; when?: string; language: FeedbackLanguage; fresh?: boolean },
): HTMLElement {
  const stamp = doc.createElement('div');
  stamp.className = `delivery-stamp${input.fresh ? ' is-fresh' : ''}`;
  stamp.dataset.deliveryStamp = '';
  const kicker = doc.createElement('span');
  kicker.className = 'delivery-stamp__kicker';
  kicker.textContent = input.language === 'en' ? 'Submitted' : '已交付';
  const decision = doc.createElement('span');
  decision.className = 'delivery-stamp__decision';
  decision.textContent = input.decision;
  stamp.append(kicker, decision);
  if (input.when) {
    const when = doc.createElement('span');
    when.className = 'delivery-stamp__when';
    when.textContent = input.when;
    stamp.append(when);
  }
  return stamp;
}
