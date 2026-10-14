/** Names for deliveries and the work versions they hold. A submission is a new record at
 * version 1 each time, so its round comes from its place in the practice's list; record
 * ids are never shown. */
import type { ObjectRef } from '../workspace/contract-types';
import { feedbackCopy, type FeedbackLanguage } from './localization';

/** 1-based round of a submission among the practice's submissions, oldest first. */
export function deliveryNumber(
  submissions: readonly { ref: ObjectRef }[],
  ref: ObjectRef,
): number | undefined {
  const index = submissions.findIndex(
    (row) => row.ref.object_id === ref.object_id && row.ref.version === ref.version,
  );
  return index < 0 ? undefined : index + 1;
}

export const deliveryName = (language: FeedbackLanguage, n: number) =>
  feedbackCopy(language, 'delivery', { n });

export const snapshotName = (language: FeedbackLanguage, n: number | undefined) =>
  n === undefined
    ? feedbackCopy(language, 'deliverySnapshotUnnumbered')
    : feedbackCopy(language, 'deliverySnapshot', { n });

type Titled = { product_id: string; version: number; title?: string };

/** Titles of exact work versions. The current version's title is known; an earlier
 * version's own title is read once from its record, and `changed` runs when it arrives. */
export function versionTitles(
  read: (ref: ObjectRef) => Promise<string | undefined>,
  changed: () => void,
) {
  const known = new Map<string, string>();
  const asked = new Set<string>();
  return {
    title(products: readonly Titled[], ref: ObjectRef): string | undefined {
      const current = products.find(
        (p) => p.product_id === ref.object_id && p.version === ref.version,
      );
      if (current?.title) return current.title;
      const id = `${ref.object_id}:${ref.version}`;
      if (known.has(id)) return known.get(id);
      if (!asked.has(id)) {
        asked.add(id);
        read(ref).then(
          (title) => {
            if (!title) return;
            known.set(id, title);
            changed();
          },
          () => {
            /* An unreadable version keeps its generic name. */
          },
        );
      }
      return undefined;
    },
  };
}
