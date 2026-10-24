/** Figures on the system profile page, each tied to a field of a published result file.
 *
 * A figure is never typed into the copy: copy carries `{name}` placeholders and the page
 * fills them from `public/lab/<file>.json` at the given key path (the same path exists in
 * `experiments/recognition/results/`). A sum or ratio of fields says so in `derived`.
 */
import type { Results } from './data';

export type Path = readonly (string | number)[];
export interface Ref {
  file: string;
  path: Path;
}
export interface Figure {
  refs: Ref[];
  show: (values: number[]) => string;
  derived?: string;
}

export const ref = (file: string, ...path: Path): Ref => ({ file, path });

export function read(results: Results, r: Ref): number | null {
  let node: unknown = results[r.file];
  for (const key of r.path) {
    if (node === null || typeof node !== 'object') return null;
    node = (node as Record<string | number, unknown>)[key];
  }
  return typeof node === 'number' && Number.isFinite(node) ? node : null;
}

const one =
  (show: (x: number) => string) =>
  (r: Ref): Figure => ({ refs: [r], show: ([x]) => show(x) });
/** Three decimals: macro-F1, AUROC, MRR (the reports use the same precision). */
export const f3 = one((x) => x.toFixed(3));
/** Two decimals: recall over 100 questions, accuracy over 80 runs. */
export const f2 = one((x) => x.toFixed(2));
export const pct = one((x) => `${(x * 100).toFixed(1)}%`);
export const pct0 = one((x) => `${Math.round(x * 100)}%`);
export const int = one((x) => String(Math.round(x)));
/** "a/b" where a and b are sums of counts. */
export const fraction = (top: Ref[], bottom: Ref[]): Figure => ({
  refs: [...top, ...bottom],
  show: (xs) =>
    `${xs.slice(0, top.length).reduce((a, b) => a + b, 0)}/${xs.slice(top.length).reduce((a, b) => a + b, 0)}`,
  derived: 'sum',
});

/** Fill every figure, or null when any field is missing (the section then says so). */
export function fill(
  results: Results,
  figures: Record<string, Figure>,
): Record<string, string> | null {
  const out: Record<string, string> = {};
  for (const [name, figure] of Object.entries(figures)) {
    const values = figure.refs.map((r) => read(results, r));
    if (values.some((v) => v === null)) return null;
    out[name] = figure.show(values as number[]);
  }
  return out;
}

/** A plain number for a chart; NaN draws as "–". */
export const value = (results: Results, file: string, ...path: Path) =>
  read(results, ref(file, ...path)) ?? Number.NaN;
