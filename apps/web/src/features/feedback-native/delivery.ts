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
  plan: ['方案', 'Plan'],
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
  input: {
    decision: string;
    when?: string;
    language: FeedbackLanguage;
    fresh?: boolean;
    /** Already this far into the press (ms): continue it rather than start over. */
    elapsed?: number;
  },
): HTMLElement {
  const stamp = doc.createElement('div');
  stamp.className = `delivery-stamp${input.fresh ? ' is-fresh' : ''}`;
  if (input.fresh && input.elapsed)
    stamp.style.animationDelay = `calc(var(--fast) - ${Math.round(input.elapsed)}ms)`;
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

/** What the delivery button says it will do: the one version, how many, or (nothing chosen yet)
 * the plain action. */
export function submitLabel(
  products: readonly { version: number }[],
  language: FeedbackLanguage,
): string {
  if (products.length === 1)
    return language === 'en'
      ? `Submit version ${products[0].version}`
      : `提交第 ${products[0].version} 版`;
  if (products.length > 1)
    return language === 'en' ? `Submit ${products.length} versions` : `提交 ${products.length} 个版本`;
  return language === 'en' ? 'Submit selected versions' : '提交选中的版本';
}

/** A work version as a paper slip: its title, with the version small; the purpose sits outside
 * the slip as a plain note. */
export function attachmentSlip(
  doc: Document,
  product: { title?: string | null; version: number; purpose?: string },
  language: FeedbackLanguage,
  tag: 'span' | 'button' = 'span',
): DocumentFragment & { slip: HTMLElement } {
  const out = doc.createDocumentFragment() as DocumentFragment & { slip: HTMLElement };
  const slip = doc.createElement(tag);
  slip.className = 'paper-slip';
  if (tag === 'button') (slip as HTMLButtonElement).type = 'button';
  const title = doc.createElement('span');
  title.className = 'paper-slip__title';
  title.textContent = product.title || (language === 'en' ? 'Untitled work' : '未命名作品');
  const version = doc.createElement('small');
  version.className = 'paper-slip__version';
  version.textContent = versionWords(product.version, language);
  slip.append(title, version);
  out.append(slip);
  const purpose = purposeWords(product.purpose, language);
  if (purpose) {
    const note = doc.createElement('span');
    note.className = 'paper-slip__purpose';
    note.textContent = purpose;
    out.append(note);
  }
  out.slip = slip;
  return out;
}
