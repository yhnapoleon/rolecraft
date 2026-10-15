/** How the feedback panel names a delivery's saved snapshot. The delivery's own name ("第 2 次
 * 交付", "Delivery 2") comes from the practice catalog that names every evidence button and the
 * reader, numbered by submitted events, so one delivery reads the same everywhere. */
import { referenceLabel, type ReferenceCatalog, type ReferenceKey } from '../../reference-catalog';
import { feedbackCopy, type FeedbackLanguage } from './localization';

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
