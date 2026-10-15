/** Which requested totals become terms. Pure: no DOM, host or journal. */

export type Totals = Partial<Record<string, number>>;

/**
 * The selected totals the learner changed from the allocation in effect. A blank total
 * or one equal to the allocation is not a term: the approval rules return a mixed
 * request with an unnecessary term as a whole.
 */
export function changedTerms(
  selected: readonly string[],
  values: Readonly<Record<string, string | undefined>>,
  current: Readonly<Totals>,
): Record<string, number> {
  const terms: Record<string, number> = {};
  for (const key of selected) {
    const value = values[key]?.trim();
    if (!value) continue;
    const amount = Number(value);
    if (!Number.isSafeInteger(amount) || amount <= 0) throw new RangeError('Invalid amount');
    if (amount !== current[key]) terms[key] = amount;
  }
  return terms;
}
