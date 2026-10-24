/** What the colleague chat shows, worked out from the reply text alone (no DOM). The saved
 * reply is never changed: these functions only decide how it reads in the thread. */

export interface Cite {
  /** The tag as the reply wrote it, without brackets: "Manager brief · v1". */
  label: string;
  title: string;
  version: number;
}

/** A document the sentence needs stays in it by name; in English the name is marked so the
 * view can set it as a title. Chinese names it in book quotes, which reads as a title already. */
export const NAME_OPEN = '';
export const NAME_CLOSE = '';

const MARK_OPEN = '';
const MARK_CLOSE = '';
const MARK = /(\d+)/g;
/** `[Title · v1]`, optionally a Markdown link `[Title · v1](material:x)`, or `《Title · v1》`. */
const TAG = /\[([^[\]\n]+? · v(\d+))\](?:\([^)\s]*\))?|《([^《》\n]+? · v(\d+))》/g;
/** A parenthesis that holds nothing but citations and their separators. */
const CITES_ONLY = new RegExp(
  `[ \\t]*[（(]\\s*(?:${MARK_OPEN}\\d+${MARK_CLOSE}\\s*[;；,，、]?\\s*)+[)）]`,
  'g',
);
const CJK = /[㐀-鿿]/;
const WORD = /[\p{L}\p{N}]/u;
/** Characters and words after which a document is the object of the sentence, not a footnote. */
const ZH_NEEDS = new Set('按据见在于和与及或从由照依自同跟看读查对向把将是为即'.split(''));
const EN_NEEDS = new Set(
  'from in see per under to and or of by the with on at into check read cite cites citing via than is was are'.split(
    ' ',
  ),
);
/** A trailing citation that leaves one of these dangling also takes it away. */
const LEAD_IN = /[\s:：—–-]+$/;

function needsName(before: string, language: 'zh' | 'en') {
  const left = before.replace(/\s+$/, '');
  if (!left) return false;
  if (language === 'zh' && CJK.test(left.slice(-1))) return ZH_NEEDS.has(left.slice(-1));
  const word = /([A-Za-z]+)$/.exec(left)?.[1]?.toLowerCase();
  return !!word && EN_NEEDS.has(word);
}

/** The reply's text with its citation tags taken out of the sentences, and the sources it cited. */
export function splitCitations(
  text: string,
  language: 'zh' | 'en',
): { text: string; cites: Cite[] } {
  const found: Cite[] = [];
  let marked = text.replace(TAG, (_m, a: string, av: string, b: string, bv: string) => {
    const label = (a ?? b).trim();
    const version = Number(av ?? bv);
    const title = label.slice(0, label.lastIndexOf(' · v')).trim();
    found.push({ label, title, version });
    return MARK_OPEN + (found.length - 1) + MARK_CLOSE;
  });
  marked = marked.replace(CITES_ONLY, '');
  // Each remaining tag either names a document the sentence needs or closes a sentence.
  let out = '';
  let last = 0;
  for (const match of marked.matchAll(MARK)) {
    const at = match.index;
    const cite = found[Number(match[1])];
    let before = out + marked.slice(last, at);
    const after = marked.slice(at + match[0].length);
    const next = after.replace(/^[ \t]+/, '').charAt(0);
    const grammatical =
      (next && (WORD.test(next) || /[:：]/.test(next))) || needsName(before, language);
    if (grammatical) {
      if (language === 'zh') {
        before = before.replace(/[ \t]+$/, '');
        out = `${before}《${cite.title}》`;
        last = at + match[0].length;
        // The book quotes separate the name; spaces the tag stood between go with it.
        const rest = marked.slice(last);
        const spaces = /^[ \t]+/.exec(rest);
        if (spaces && CJK.test(rest.charAt(spaces[0].length))) last += spaces[0].length;
        continue;
      }
      out = before + NAME_OPEN + cite.title + NAME_CLOSE;
    } else {
      // A footnote: it goes, with the space or colon that led into it.
      out = before.replace(LEAD_IN, (lead) => (/\n/.test(lead) ? lead.replace(/[^\n]/g, '') : ''));
    }
    last = at + match[0].length;
  }
  out += marked.slice(last);
  out = out
    .split('\n')
    .map((line) => line.replace(/[ \t]+$/, ''))
    .join('\n');
  const seen = new Set<string>();
  const cites = found.filter((c) => !seen.has(c.label) && !!seen.add(c.label));
  return { text: out, cites };
}

export const languageOf = (text: string): 'zh' | 'en' => (CJK.test(text) ? 'zh' : 'en');

/* ---------- the local reference reply ---------- */

/** Lines the local reference writes around its excerpts (runtime/context_v2.py, roles_v2.py).
 * They say how the reply was made, which the grey mark and the notes already say. */
const LOCAL_PREAMBLE = [
  '本地资料参考；来源与权限由规则核实；需要同事判断的部分等待模型接入。',
  'Local source reference; sources and access checked by rules; colleague judgment is waiting for model connection.',
];
const LOCAL_ROLE = ['我的职责：', 'My responsibilities:'];
const LOCAL_OTHERS = ['其余可参考的资料（未展开）：', 'Other sources available (not expanded):'];
const LOCAL_NO_MATCH = [
  '本地资料中没有找到与这个问题直接相关的内容。',
  'No passage directly related to this question was found in the local sources.',
];
const LOCAL_NOTES = [
  '仅按已收到的版本引用作品；新版本需明确分享后才能讨论。',
  'Only the received versions are cited; share a new version explicitly before discussing it.',
  '有学员材料超出本次授权，相关内容未读取或复述。',
  'Some learner materials are outside the current authorization and were not read or repeated.',
];
const EXCERPT = /^\[([^[\]\n]+? · v(\d+))\] ?(.*)$/;

export type LocalRow =
  | { kind: 'excerpt'; cite: Cite; text: string }
  | { kind: 'others'; cites: Cite[] }
  | { kind: 'none'; text: string };

const citeOf = (label: string): Cite => ({
  label,
  title: label.slice(0, label.lastIndexOf(' · v')).trim(),
  version: Number(label.slice(label.lastIndexOf(' · v') + 4)),
});

/** The local reply as rows: each quoted passage with its source, the sources it only lists,
 * and the line saying nothing matched. Lines about how the reply was made are left out. */
export function localRows(reply: string): LocalRow[] {
  const rows: LocalRow[] = [];
  let open: Extract<LocalRow, { kind: 'excerpt' }> | undefined;
  for (const raw of reply.split('\n')) {
    const line = raw.trim();
    const excerpt = EXCERPT.exec(line);
    if (excerpt) {
      open = { kind: 'excerpt', cite: citeOf(excerpt[1]), text: excerpt[3] };
      rows.push(open);
      continue;
    }
    if (
      LOCAL_PREAMBLE.includes(line) ||
      LOCAL_NOTES.includes(line) ||
      LOCAL_ROLE.some((p) => line.startsWith(p))
    ) {
      open = undefined;
      continue;
    }
    const others = LOCAL_OTHERS.find((p) => line.startsWith(p));
    if (others) {
      open = undefined;
      const labels = [...line.slice(others.length).matchAll(/\[([^[\]\n]+? · v\d+)\]/g)];
      rows.push({ kind: 'others', cites: labels.map((m) => citeOf(m[1])) });
      continue;
    }
    if (LOCAL_NO_MATCH.includes(line)) {
      open = undefined;
      rows.push({ kind: 'none', text: line });
      continue;
    }
    // A passage that runs over several lines (a shared work, a list) stays together.
    if (open) open.text += `\n${raw}`;
    else if (line) rows.push({ kind: 'none', text: line });
  }
  return rows;
}

/** The local reference writes its preamble first; a model reply never does. */
export const isLocalReply = (reply: string) =>
  reply.split('\n').some((line) => LOCAL_PREAMBLE.includes(line.trim()));
/** The role line ("我的职责：…") of a local reply, shown only with the full text. */
export const localRoleLine = (reply: string) =>
  reply
    .split('\n')
    .map((line) => line.trim())
    .find((line) => LOCAL_ROLE.some((p) => line.startsWith(p))) ?? '';

/* ---------- a reply as messages ---------- */

/** Up to this many characters a reply is shown whole (decided in 193, 2026-10-24). */
export const WHOLE_REPLY_CHARS = 700;

/** Each paragraph is its own bubble, the way a person sends a few short messages. A reply
 * longer than WHOLE_REPLY_CHARS shows its first two paragraphs; the rest wait to be opened. */
export function replyParts(text: string): { shown: string[]; folded: string[] } {
  const parts = text
    .split(/\n[ \t]*\n/)
    .map((p) => p.replace(/^\n+|\s+$/g, ''))
    .filter((p) => p.trim());
  const length = parts.reduce((n, p) => n + p.length, 0);
  if (length <= WHOLE_REPLY_CHARS || parts.length <= 2) return { shown: parts, folded: [] };
  return { shown: parts.slice(0, 2), folded: parts.slice(2) };
}

/* ---------- the exact passage behind a source tag ---------- */

/** Pair each verified quote (the reply's `spoken_evidence`: source text the reply contains
 * word for word) with the source tag nearest to it in the same paragraph. A quote with no tag
 * beside it is left out: the source is then only opened, never guessed. */
export function evidenceBySource(reply: string, quotes: readonly string[]): Map<string, string> {
  const pairs = new Map<string, string>();
  for (const quote of quotes) {
    const at = quote ? reply.indexOf(quote) : -1;
    if (at < 0) continue;
    const start = Math.max(reply.lastIndexOf('\n\n', at), reply.lastIndexOf('\n[', at));
    const from = start < 0 ? 0 : start + 1;
    const ends = [
      reply.indexOf('\n\n', at + quote.length),
      reply.indexOf('\n[', at + quote.length),
    ];
    const to = Math.min(...ends.map((e) => (e < 0 ? reply.length : e)));
    let best: { label: string; distance: number } | undefined;
    for (const m of reply.slice(from, to).matchAll(TAG)) {
      const label = (m[1] ?? m[3]).trim();
      const tagAt = from + m.index;
      const distance =
        tagAt + m[0].length <= at
          ? at - (tagAt + m[0].length)
          : Math.max(0, tagAt - (at + quote.length));
      if (!best || distance < best.distance) best = { label, distance };
    }
    if (best && !pairs.has(best.label)) pairs.set(best.label, quote);
  }
  return pairs;
}

/* ---------- who is replying, and replies that did not come through ---------- */

type Outcome = { requestId: string; status: string; result?: unknown };
const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
const text = (value: unknown) => (typeof value === 'string' ? value : undefined);
/** The turn a `turns.create` request made, in either the first or the recovered result shape. */
function turnOf(outcome: Outcome): { role?: string; turn?: string } {
  let data = record(outcome.result);
  if (data.response) data = record(data.response);
  if (data.result && !data.role_id) data = record(data.result);
  return { role: text(data.role_id), turn: text(record(data.turn).object_id) };
}

/** Colleagues whose question this browser sent is still being answered: the request is pending
 * on the server and no reply to that turn is in the conversation yet. */
export function awaitingRoles(
  outcomes: readonly Outcome[],
  roleRequests: readonly string[],
  replied: ReadonlySet<string>,
): Set<string> {
  const mine = new Set(roleRequests);
  const roles = new Set<string>();
  for (const outcome of outcomes) {
    if (outcome.status !== 'pending' || !mine.has(outcome.requestId)) continue;
    const { role, turn } = turnOf(outcome);
    if (role && turn && !replied.has(turn)) roles.add(role);
  }
  return roles;
}

/** Error codes of replies the checks held back: the colleague answered, the text was stopped. */
const HELD = new Set([
  'role_output_blocked',
  'role_reply_stance_inconsistent',
  'role_reply_semantics_unverified',
  'role_help_unverified',
  'role_help_citation_invalid',
]);
export type NoticeKind =
  | 'typing'
  | 'held'
  | 'failed'
  | 'context'
  | 'paused'
  | 'stopped'
  | 'unknown';
export function noticeKind(status: string, errorCode?: string): NoticeKind {
  if (status === 'queued' || status === 'running') return 'typing';
  if (status === 'failed') return errorCode && HELD.has(errorCode) ? 'held' : 'failed';
  if (status === 'needs_context') return 'context';
  if (status === 'paused') return 'paused';
  if (status === 'cancelled') return 'stopped';
  return 'unknown';
}

/* ---------- one line for the colleague list ---------- */

const CLOSERS = '”’」』）)"\'';
function firstSentence(value: string): string {
  for (let i = 0; i < value.length; i++) {
    const c = value[i];
    const ends = '。！？!?'.includes(c) || (c === '.' && /\s/.test(value[i + 1] ?? ' '));
    if (!ends) continue;
    let end = i + 1;
    while (end < value.length && CLOSERS.includes(value[end])) end++;
    return value.slice(0, end);
  }
  return value;
}
const plainMarkdown = (line: string) =>
  line
    .replace(/^\s*(?:#{1,6}|[-*+]|\d+[.)])\s+/, '')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(new RegExp(`[${NAME_OPEN}${NAME_CLOSE}]`, 'g'), '');

/** The first sentence of a reply, as the colleague list shows it: no Markdown, no source tags,
 * none of the lines the local reference writes about itself. Empty when nothing fits. */
export function previewLine(reply: string): string {
  const rows = localRows(reply);
  const first = isLocalReply(reply)
    ? rows.find((r): r is Extract<LocalRow, { kind: 'excerpt' }> => r.kind === 'excerpt')?.text
    : reply.split('\n').find((l) => l.trim());
  if (!first) return '';
  const line = first.split('\n').find((l) => l.trim()) ?? '';
  const { text } = splitCitations(line, languageOf(line));
  return firstSentence(plainMarkdown(text).replace(/\s+/g, ' ').trim())
    .replace(/[：:]$/, '')
    .trim();
}

/** The workbench's Markdown has bold but no italics; a reply's `*word*` reads as the word. */
export const dropEmphasis = (text: string) =>
  text.replace(/(^|[^*\w])\*(?=[^\s*])([^*\n]*?[^\s*])\*(?![*\w])/gm, '$1$2');
