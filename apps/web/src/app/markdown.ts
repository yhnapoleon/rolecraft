/** The Markdown the workbench shows: `#`/`##` headings, `###`–`######` subheadings,
 * `-`/`*` and `1.`/`1)` list items, paragraphs, `**bold**` and `` `code` ``.
 * Text is never read as HTML: the string form escapes every text run and the DOM form
 * only creates these elements and appends text. Blank lines separate nothing else. */
export type MarkdownInline =
  | { kind: 'text'; text: string }
  | { kind: 'code'; text: string }
  | { kind: 'strong'; children: MarkdownInline[] };
export type MarkdownLine = { tag: 'h3' | 'h4' | 'p'; inline: MarkdownInline[] };
/** `start` is the number an ordered list was written with, when it is not 1. */
export type MarkdownList = { tag: 'ul' | 'ol'; items: MarkdownInline[][]; start?: number };
export type MarkdownBlock = MarkdownLine | MarkdownList;
const isList = (block: MarkdownBlock): block is MarkdownList => 'items' in block;
export interface MarkdownOptions {
  /** Leave out a leading level-one heading: the page already shows the title. */
  readonly dropTitle?: boolean;
}

const STRONG = /\*\*([^*]+)\*\*/g;
const CODE = /`([^`]+)`/g;
const BULLET = /^\s*[-*]\s+(.*)$/;
const NUMBERED = /^\s*(\d+)[.)]\s+(.*)$/;
const HEADING = /^#{1,2}\s/;
const SUBHEADING = /^#{3,6}\s/;

/** Code spans stand in the line as private-use markers, so bold can wrap them while
 * asterisks inside code stay literal. */
const OPEN = '\uE000';
const CLOSE = '\uE001';
const MARKER = /\uE000(\d+)\uE001/g;

function inline(text: string): MarkdownInline[] {
  const code: string[] = [];
  const marked = text.replace(CODE, (_, content: string) => {
    code.push(content);
    return OPEN + (code.length - 1) + CLOSE;
  });
  const restore = (part: string): MarkdownInline[] => {
    const runs: MarkdownInline[] = [];
    let last = 0;
    for (const match of part.matchAll(MARKER)) {
      if (match.index > last) runs.push({ kind: 'text', text: part.slice(last, match.index) });
      runs.push({ kind: 'code', text: code[Number(match[1])] });
      last = match.index + match[0].length;
    }
    if (last < part.length) runs.push({ kind: 'text', text: part.slice(last) });
    return runs;
  };
  const runs: MarkdownInline[] = [];
  let last = 0;
  for (const match of marked.matchAll(STRONG)) {
    if (match.index > last) runs.push(...restore(marked.slice(last, match.index)));
    runs.push({ kind: 'strong', children: restore(match[1]) });
    last = match.index + match[0].length;
  }
  if (last < marked.length) runs.push(...restore(marked.slice(last)));
  return runs;
}

export function parseMarkdown(raw: unknown, options: MarkdownOptions = {}): MarkdownBlock[] {
  let lines = String(raw || '').split('\n');
  if (options.dropTitle && /^#\s/.test(lines[0] ?? '')) lines = lines.slice(1);
  const blocks: MarkdownBlock[] = [];
  // Any other line, blank lines included, ends the list in progress.
  let list: MarkdownList | undefined;
  for (const line of lines) {
    const bullet = BULLET.exec(line);
    const numbered = bullet ? null : NUMBERED.exec(line);
    if (bullet || numbered) {
      const tag = bullet ? 'ul' : 'ol';
      if (!list || list.tag !== tag) {
        // A list that starts again (after a blank line or a bullet) keeps its own number.
        const start = numbered ? Number.parseInt(numbered[1], 10) : 1;
        list = start === 1 ? { tag, items: [] } : { tag, items: [], start };
        blocks.push(list);
      }
      list.items.push(inline(bullet ? bullet[1] : (numbered?.[2] ?? '')));
      continue;
    }
    list = undefined;
    if (HEADING.test(line)) blocks.push({ tag: 'h3', inline: inline(line.replace(HEADING, '')) });
    else if (SUBHEADING.test(line))
      blocks.push({ tag: 'h4', inline: inline(line.replace(SUBHEADING, '')) });
    else if (line.trim()) blocks.push({ tag: 'p', inline: inline(line) });
  }
  return blocks;
}

/** True when the text has a heading, a list or inline marks; plain lines stay plain. */
export function hasMarkdownStructure(raw: unknown): boolean {
  return parseMarkdown(raw).some(
    (block) =>
      isList(block) || block.tag !== 'p' || block.inline.some((run) => run.kind !== 'text'),
  );
}

const ENTITY: Readonly<Record<string, string>> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
};
const escapeHtml = (value: string) => value.replace(/[&<>"']/g, (c) => ENTITY[c] ?? c);

function inlineHtml(runs: readonly MarkdownInline[]): string {
  return runs
    .map((run) =>
      run.kind === 'strong'
        ? `<strong>${inlineHtml(run.children)}</strong>`
        : run.kind === 'code'
          ? `<code>${escapeHtml(run.text)}</code>`
          : escapeHtml(run.text),
    )
    .join('');
}

/** Escaped HTML for the string-built pages; empty when there is nothing to show. */
export function markdownHtml(raw: unknown, options: MarkdownOptions = {}): string {
  return parseMarkdown(raw, options)
    .map((block) =>
      isList(block)
        ? `<${block.tag}${block.start !== undefined ? ` start="${block.start}"` : ''}>${block.items.map((item) => `<li>${inlineHtml(item)}</li>`).join('')}</${block.tag}>`
        : `<${block.tag}>${inlineHtml(block.inline)}</${block.tag}>`,
    )
    .join('');
}

function appendInline(doc: Document, parent: HTMLElement, runs: readonly MarkdownInline[]) {
  for (const run of runs) {
    if (run.kind === 'text') {
      parent.append(run.text);
      continue;
    }
    const node = doc.createElement(run.kind);
    if (run.kind === 'strong') appendInline(doc, node, run.children);
    else node.textContent = run.text;
    parent.append(node);
  }
}

/** Elements for the DOM-built surfaces; text is only ever appended as text. */
export function markdownNodes(
  doc: Document,
  raw: unknown,
  options: MarkdownOptions = {},
): HTMLElement[] {
  return parseMarkdown(raw, options).map((block) => {
    const node = doc.createElement(block.tag);
    if (isList(block) && block.start !== undefined) node.setAttribute('start', String(block.start));
    if (isList(block))
      for (const item of block.items) {
        const li = doc.createElement('li');
        appendInline(doc, li, item);
        node.append(li);
      }
    else appendInline(doc, node, block.inline);
    return node;
  });
}
