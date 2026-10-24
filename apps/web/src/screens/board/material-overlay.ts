// Reading a document over the board (decision 14): the sheet itself is DocSheet (sheets.tsx,
// on the ui-kit Sheet). This keeps where to come back to, and how a new version reads.

let returnTo: string | null = null;

/** Remember the row a document was opened from. */
export function willOpen(fromId: string) {
  returnTo = fromId;
}

/** After the sheet closed: focus goes back to the row it came from. */
export function returnFocus() {
  const id = returnTo;
  returnTo = null;
  if (!id) return;
  const row =
    document.querySelector<HTMLElement>(`[data-doc-row="${CSS.escape(id)}"]`) ||
    document.querySelector<HTMLElement>(`[data-action="open-doc"][data-id="${CSS.escape(id)}"]`);
  (row || document.getElementById('main'))?.focus({ preventScroll: true });
}

// A new version, read as itself with its changed figures marked in place: "CNY ~~500~~ 400".
// Figures are paired in order (the first number new to v2 with the first one gone from v1).
// A rewrite with no changed figure is shown as it is; v1 stays one switch away.
const NUM = /\d+(?:[.,]\d+)?/g;
export function markChangedFigures(html: string, before: string, after: string) {
  const was = new Set(String(before).match(NUM) || []);
  const now = new Set(String(after).match(NUM) || []);
  const added = [...now].filter((n) => !was.has(n));
  const gone = [...was].filter((n) => !now.has(n));
  let out = html;
  added.forEach((n, i) => {
    const old = gone[i];
    if (!old) return;
    // The first occurrence outside a tag, on number boundaries.
    const re = new RegExp(`(^|>)([^<]*?)(?<![\\d.,])${n.replace(/[.,]/g, '\\$&')}(?![\\d])`);
    out = out.replace(re, (_m, open, text) => `${open}${text}<del>${old}</del> <ins>${n}</ins>`);
  });
  return out;
}
