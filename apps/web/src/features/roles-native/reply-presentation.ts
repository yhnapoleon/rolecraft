import { locale } from '../../app/i18n';
import { copyText, type CopyTable } from '../results-native/localization';

export type RoleMode = 'local_reference' | 'model' | 'unavailable';
export type GenerationMode = 'local' | 'model';

export interface ReplyPresentationContext {
  generationMode?: GenerationMode;
  receivedVersionsOnly?: boolean;
  omissionCount?: number;
}

export interface ReplyPresentation {
  /** First-screen text: the colleague's own words, or a derived line when none fit. */
  summary: string;
  /** Citation tag of a quoted first-screen passage, e.g. "Manager brief · v1". */
  source?: string;
  /** The full reply says more than the first screen. */
  partial: boolean;
  /** `summary` is written by this view from the reply structure, not quoted. */
  derived: boolean;
  /** Distinct `[title · vN]` citations in the full reply. */
  sourceCount: number;
  status?: string;
  versionNote?: string;
  omissionNote?: string;
}

const zh = {
  statusLocal: '本地来源：规则核实 · 判断等待模型接入',
  statusModel: '模型建议（不计分） · 保留原回复',
  versionNote: '仅依据已分享的确切版本；新版需要重新分享。',
  omissionNote: '部分资料因授权或上下文限额未纳入本次回复。',
  modeLocal: '本地资料参考；需要同事判断的部分等待模型接入。',
  modeUnavailable: '同事对话暂不可用，已有记录仍保留。',
  modeModel: '当前同事模式：模型建议（不计分）。',
  expand: '展开原文',
  sources: '引用 {n} 份资料',
  noPassage: '这次回复没有直接相关的原文摘录。',
  noPassageListed: '这次回复没有直接相关的原文摘录，列出了 {n} 份可参考资料。',
  longReply: '完整回复较长，引用 {n} 份资料。',
  longExcerpt: '首条引用的原文较长，引用 {n} 份资料，见原文。',
  longReplyUncited: '完整回复较长。',
};
const COPY: CopyTable<keyof typeof zh> = {
  zh,
  en: {
    statusLocal: 'Sources checked by rules · judgment waiting for model connection',
    statusModel: 'Model advice (not scored) · original reply retained',
    versionNote: 'Only exact shared versions are available; share a new version explicitly.',
    omissionNote: 'Some sources were omitted because of access or context limits.',
    modeLocal: 'Local source reference; colleague judgment is waiting for model connection.',
    modeUnavailable: 'Colleague replies are unavailable; existing records are retained.',
    modeModel: 'Current colleague mode: model advice (not scored).',
    expand: 'Show full reply',
    sources: 'Sources cited: {n}',
    noPassage: 'This reply quotes no directly related passage.',
    noPassageListed:
      'This reply quotes no directly related passage; sources listed for reference: {n}.',
    longReply: 'The full reply is long; sources cited: {n}.',
    longExcerpt: 'The first cited passage is long; sources cited: {n}. See the full reply.',
    longReplyUncited: 'The full reply is long.',
  },
};
export const replyCopyTable = COPY;
const text = (key: keyof typeof zh, values?: Record<string, number>) =>
  copyText(COPY, locale(), key, values);

/** Public citation format shared by local excerpts and model replies. */
const TAG = /\[([^[\]\n]+ · v\d+)\]/g;
const PASSAGE = /^\[([^[\]\n]+ · v\d+)\] (.*)$/;
const CITES = /\[[^[\]\n]+ · v\d+\]/;
/** Separator the local reference places between two distinct quoted fragments. */
const GAP = / (?:……|…) /;
/** Longest first-screen excerpt built from whole sentences; never cut mid-sentence. */
const EXCERPT_CHARS = 200;
const SENTENCE_CHARS = 320;
const PARAGRAPH_CHARS = 280;

type Chosen = Pick<ReplyPresentation, 'summary' | 'source'> | undefined;

function sentences(value: string): string[] {
  const parts: string[] = [];
  let start = 0;
  for (let i = 0; i < value.length; i++) {
    const c = value[i];
    if (!'。！？!?\n'.includes(c) && !(c === '.' && /\s/.test(value[i + 1] ?? ' '))) continue;
    // Closing quotes and the following line break belong to the sentence they end.
    while ('”’」』）)"\' \n'.includes(value[i + 1] ?? '_')) i++;
    parts.push(value.slice(start, i + 1));
    start = i + 1;
  }
  if (start < value.length) parts.push(value.slice(start));
  return parts;
}

/** Leading whole sentences of one quoted fragment, so its own conditions stay together. */
function leading(fragment: string): string | undefined {
  let shown = '';
  for (const part of sentences(fragment)) {
    if (shown && (shown + part).trim().length > EXCERPT_CHARS) break;
    shown += part;
  }
  shown = shown.trim();
  return shown && shown.length <= SENTENCE_CHARS ? shown : undefined;
}

/** The reply's first cited passage: one rule-checked excerpt or recorded decision with its
 * source. The backend orders citations (decisions on the asked subject, newer notices,
 * then initial materials; recalled questions last), so only the first is considered. */
function firstPassage(reply: string): Chosen {
  const lines = reply.split('\n');
  const start = lines.findIndex((line) => PASSAGE.test(line));
  const match = start < 0 ? null : PASSAGE.exec(lines[start]);
  if (!match) return undefined;
  const body = [match[2]];
  for (const line of lines.slice(start + 1)) {
    if (line.startsWith('[') || CITES.test(line)) break;
    body.push(line);
  }
  const shown = leading(body.join('\n').split(GAP)[0]);
  return shown ? { summary: shown, source: match[1] } : undefined;
}

/** A model reply leads with one observation or question and its conditions. */
function firstParagraph(reply: string): Chosen {
  const first = reply.split('\n')[0].trim();
  return first && first.length <= PARAGRAPH_CHARS ? { summary: first } : undefined;
}

const singleLine = (reply: string): Chosen =>
  reply && !reply.includes('\n') ? { summary: reply } : undefined;

/** First screen from the reply's own structure; the full text is never altered. */
export function presentReply(reply: string, context: ReplyPresentationContext): ReplyPresentation {
  const whole = reply.trim();
  const sourceCount = new Set([...whole.matchAll(TAG)].map((m) => m[1])).size;
  const order =
    context.generationMode === 'local'
      ? [firstPassage, singleLine]
      : [firstParagraph, firstPassage];
  let chosen: Chosen;
  for (const pick of order) chosen ??= pick(whole);
  const derived = !chosen;
  const local = context.generationMode === 'local';
  // A derived line says only what the structure shows: "no excerpt" only when no
  // passage is cited at all, otherwise that the cited text is too long to lead with.
  const cited = whole.split('\n').some((line) => PASSAGE.test(line));
  const summary =
    chosen?.summary ??
    (local && cited
      ? text('longExcerpt', { n: sourceCount })
      : local
        ? sourceCount
          ? text('noPassageListed', { n: sourceCount })
          : text('noPassage')
        : sourceCount
          ? text('longReply', { n: sourceCount })
          : text('longReplyUncited'));
  return {
    summary,
    source: chosen?.source,
    partial: summary !== whole,
    derived,
    sourceCount,
    versionNote: context.receivedVersionsOnly ? text('versionNote') : undefined,
    omissionNote:
      context.omissionCount && context.omissionCount > 0 ? text('omissionNote') : undefined,
    status:
      context.generationMode === 'local'
        ? text('statusLocal')
        : context.generationMode === 'model'
          ? text('statusModel')
          : undefined,
  };
}

/** Expand control for the full reply; the count is only shown when citations exist. */
export function replyDisclosure(presentation: Pick<ReplyPresentation, 'sourceCount'>) {
  return {
    label: text('expand'),
    meta: presentation.sourceCount ? text('sources', { n: presentation.sourceCount }) : undefined,
  };
}

/** Panel configuration is independent of the generator recorded on each reply. */
export function currentModeNotice(mode: RoleMode): string {
  if (mode === 'local_reference') return text('modeLocal');
  if (mode === 'unavailable') return text('modeUnavailable');
  return text('modeModel');
}
