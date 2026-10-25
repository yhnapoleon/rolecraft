/** Config keys in a colleague's reply, shown in the words of the settings panel (display only).
 * A Chinese practice speaks Chinese: `human_fallback` reads as 人工入口, with the key kept in the
 * hover title. Only keys the settings panel names are replaced; English practices stay as they
 * are; the reply itself (its assembly and storage) is not touched. */
import { FIELD_NAMES } from '../features/engineer-report/copy';
import { locale } from './i18n';

// The settings panel's names (pilot settings, engineer settings); values a field can take.
const ZH: Readonly<Record<string, string>> = {
  ...FIELD_NAMES.zh,
  human_fallback: '人工入口',
  realtime_sync: '实时同步',
  manual_policy: '政策转人工',
  human: '转人工确认',
};
const KEYS = Object.keys(ZH).sort((a, b) => b.length - a.length);
const PATTERN = new RegExp(`(\\s?)(?<![A-Za-z0-9_])(${KEYS.join('|')})(?![A-Za-z0-9_])(\\s?)`, 'g');
const WIDE = /[　-〿㐀-鿿＀-￯]/;

export type Piece = string | { key: string; name: string };
/** Split Chinese text into plain runs and known config keys (with their names). The space that
 * set an English word apart from Chinese goes with it. */
export function termPieces(value: string): Piece[] {
  const parts: Piece[] = [];
  let last = 0;
  for (const m of value.matchAll(PATTERN)) {
    const [whole, before, key, after] = m;
    const at = m.index ?? 0;
    const prev = value[at - 1] ?? '';
    const next = value[at + whole.length] ?? '';
    const keepBefore = before && prev && !WIDE.test(prev) ? before : '';
    const keepAfter = after && next && !WIDE.test(next) ? after : '';
    if (at > last || keepBefore) parts.push(value.slice(last, at) + keepBefore);
    parts.push({ key, name: ZH[key] });
    if (keepAfter) parts.push(keepAfter);
    last = at + whole.length;
  }
  if (last < value.length) parts.push(value.slice(last));
  return parts;
}
/** The display name of a config key written on its own (a code span), or null. */
export const termName = (key: string): string | null => ZH[key.trim()] ?? null;

/** Replace known config keys under `root` with their Chinese names (Chinese interface only). */
export function localizeConfigTerms(doc: Document, root: Element): void {
  if (locale() !== 'zh') return;
  const term = (key: string, name: string) => {
    const span = doc.createElement('span');
    span.className = 'cfg-term';
    span.title = key;
    span.textContent = name;
    return span;
  };
  // A key written as code (`human_fallback`) becomes the name outright.
  for (const code of [...root.querySelectorAll('code')]) {
    const key = (code.textContent ?? '').trim();
    const name = termName(key);
    if (name && !code.closest('pre')) code.replaceWith(term(key, name));
  }
  const walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const texts: Text[] = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode())
    if (!n.parentElement?.closest('code, pre, .cfg-term')) texts.push(n as Text);
  for (const text of texts) {
    const pieces = termPieces(text.nodeValue ?? '');
    if (pieces.every((p) => typeof p === 'string')) continue;
    text.replaceWith(
      ...pieces.map((p) => (typeof p === 'string' ? doc.createTextNode(p) : term(p.key, p.name))),
    );
  }
}
