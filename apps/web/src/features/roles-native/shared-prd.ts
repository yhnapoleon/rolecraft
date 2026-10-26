import type { ObjectRef } from '../../contracts-v2';
import type { PublicObject } from '../../v4-host-operations';

const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' ? (value as Record<string, unknown>) : {};

/** Resolve the exact share versions recorded on this turn, including later-revoked shares.
 * The note describes what was attached at send time; it never uses the current share head. */
export async function sharedPrdVersions(
  shares: unknown,
  prd: ObjectRef | null | undefined,
  session: string,
  read: (input: { kind: string; object_id: string; version: number }) => Promise<PublicObject>,
): Promise<number[]> {
  if (!Array.isArray(shares) || prd?.session_id !== session || prd.kind !== 'product') return [];
  const versions = await Promise.all(
    shares.map(async (value: unknown) => {
      const share = record(value);
      if (
        share.session_id !== session ||
        share.kind !== 'share' ||
        typeof share.object_id !== 'string' ||
        typeof share.version !== 'number' ||
        !Number.isSafeInteger(share.version) ||
        share.version < 1
      )
        return null;
      try {
        const saved = await read({
          kind: 'share',
          object_id: share.object_id,
          version: share.version,
        });
        if (
          saved.ref.session_id !== session ||
          saved.ref.kind !== 'share' ||
          saved.ref.object_id !== share.object_id ||
          saved.ref.version !== share.version
        )
          return null;
        const product = record(saved.content.product);
        return product.session_id === session &&
          product.kind === 'product' &&
          product.object_id === prd.object_id &&
          typeof product.version === 'number' &&
          Number.isSafeInteger(product.version) &&
          product.version > 0
          ? product.version
          : null;
      } catch {
        // An unavailable share cannot be labelled from memory or by guessing the title.
        return null;
      }
    }),
  );
  return [...new Set(versions.filter((version): version is number => version !== null))];
}
