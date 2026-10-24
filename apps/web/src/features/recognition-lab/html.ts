/** String-HTML helpers shared by the page's renderers. */
export const esc = (v: string) =>
  v.replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c,
  );

/** Escaped copy with each `{figure}` set in tabular weight. */
export function rich(template: string, values: Record<string, string>) {
  return esc(template).replace(/\{(\w+)\}/g, (_, name: string) =>
    values[name] == null ? '' : `<b class="rc-lab-num">${esc(values[name])}</b>`,
  );
}
