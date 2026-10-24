// TransmissionStream: every real call of the person's Agent, newest first. Shared by the product
// manager's My agent page (variant "full") and the engineer's sign-off desk ("compact", the last
// three rows). A row reads: direction · plain verb · object (serif) ……… tool name · state.
// A hand-back arrives as a sheet of paper; a refusal turns red with a sentence to pass on.
// Structure after Magic UI Animated List (MIT) and the AI Elements Tool row (Apache-2.0),
// redrawn with our tokens: instrument lines, paper for work, ink / green / red / grey only.
import { ArrowLeft, ArrowRight, Check, Copy, X } from 'lucide-react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { useMemo, useState } from 'react';
import { locale } from '../../app/i18n';
import { Button } from '../../ui-kit';
import type { AgentEvent } from '../../shell/agent-bus';
import { refusal, verbOf } from './verbs';

export type StreamWork = {
  id: string;
  title: string;
  excerpt: string;
  version: number;
  adopted: boolean;
  removed: boolean;
};
export type TransmissionStreamProps = {
  events: readonly AgentEvent[];
  variant?: 'full' | 'compact';
  onOpen?: (e: AgentEvent) => void;
  lang?: 'zh' | 'en';
  /** Rows at or after this id arrived while someone watched; older ones were history. */
  liveFrom?: number;
  /** The board's copy of a handed-back work, for its paper. */
  work?: (id: string) => StreamWork | null;
  onAdopt?: (id: string) => void;
  /** Rows shown before "Show earlier" (full only). */
  limit?: number;
  empty?: React.ReactNode;
  /** The engineer's desk shows only engineer.* calls; the product manager sees every call. */
  hat?: 'pm' | 'engineer';
  /** Any further narrowing, applied after hat. */
  filter?: (e: AgentEvent) => boolean;
};

export const engineerCall = (e: AgentEvent) => e.tool.startsWith('engineer.');

type Row = { event: AgentEvent; times: number; key: string };

const objectKey = (e: AgentEvent) =>
  [
    e.tool,
    e.status,
    e.error ?? '',
    e.object?.kind ?? '',
    e.object?.id ?? e.object?.title ?? '',
  ].join('|');
const isReturn = (e: AgentEvent) =>
  e.status === 'ok' &&
  (e.tool === 'work_products.create' || e.tool === 'work_products.versions.create');

/** Newest first; a run of the same read of the same object folds into one row with a count. */
export function foldEvents(events: readonly AgentEvent[]): Row[] {
  const rows: Row[] = [];
  for (const event of events) {
    const last = rows.at(-1);
    if (
      last &&
      event.direction === 'to_agent' &&
      event.status === 'ok' &&
      objectKey(last.event) === objectKey(event)
    ) {
      // Keep the oldest id as the key, so the row stays put and only its count rolls.
      last.times += 1;
      last.event = event;
      continue;
    }
    rows.push({ event, times: 1, key: event.id });
  }
  return rows.reverse();
}

const t = (lang: 'zh' | 'en', zh: string, en: string) => (lang === 'en' ? en : zh);
const clock = (iso: string, lang: 'zh' | 'en') => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ''
    : d.toLocaleTimeString(lang === 'en' ? 'en-GB' : 'zh-CN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });
};

function CopyLine({ text, lang }: { text: string; lang: 'zh' | 'en' }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="ag-tell"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
        } catch {
          /* the sentence stays on screen to select by hand */
        }
        setDone(true);
        setTimeout(() => setDone(false), 1600);
      }}
      aria-label={t(lang, '复制这句话，转告你的 Agent', 'Copy this sentence for your agent')}
    >
      <span className="ag-tell-text">{text}</span>
      <span className={`ag-swap${done ? ' is-done' : ''}`} aria-hidden="true">
        <Copy className="ag-swap-a" size={13} strokeWidth={1.6} />
        <Check className="ag-swap-b" size={13} strokeWidth={2} />
      </span>
    </button>
  );
}

/** A refused call did not happen: say what it tried, not what it did. */
export function failedVerb(e: AgentEvent, lang: 'zh' | 'en') {
  if (e.tool === 'work_products.remove') return t(lang, '没能删除', 'Couldn’t remove');
  if (e.tool === 'work_products.restore') return t(lang, '没能恢复', 'Couldn’t restore');
  const group = verbOf(e.tool).group;
  if (group === 'return') return t(lang, '没能交回', 'Couldn’t hand back');
  if (group === 'act') return t(lang, '没能执行', 'Couldn’t run');
  return t(lang, '没能读取', 'Couldn’t read');
}

function Line({
  row,
  lang,
  compact,
  onOpen,
}: {
  row: Row;
  lang: 'zh' | 'en';
  compact: boolean;
  onOpen?: (e: AgentEvent) => void;
}) {
  const e = row.event;
  const back = e.direction === 'to_workspace';
  const failed = e.status === 'error';
  const verb = failed ? failedVerb(e, lang) : e.verb[lang === 'en' ? 1 : 0];
  const why = failed ? refusal(e.error, e.tool) : null;
  // An experiment or draft has no title of its own; its tool name already says what it is.
  const object = e.object?.title || (e.object?.id && e.object.kind !== 'other' ? e.object.id : '');
  // Compact rows are one button (the desk opens the matching card); full rows link the object.
  const whole = compact && onOpen ? () => onOpen(e) : undefined;
  const open = !whole && onOpen && e.object?.id ? () => onOpen(e) : undefined;
  const Root = whole ? 'button' : 'div';
  return (
    <Root
      type={whole ? 'button' : undefined}
      onClick={whole}
      className={`ag-line${back ? ' is-back' : ''}${failed ? ' is-error' : ''}${whole ? ' is-row-link' : ''}`}
      data-tool={e.tool}
      data-object={e.object?.id}
    >
      <span className="ag-dir" aria-hidden="true">
        {failed ? (
          <X size={13} strokeWidth={2} />
        ) : back ? (
          <ArrowLeft size={13} strokeWidth={1.8} />
        ) : (
          <ArrowRight size={13} strokeWidth={1.8} />
        )}
      </span>
      <span className="ag-say">
        <span className="ag-verb">{verb}</span>
        {object ? (
          open ? (
            <button type="button" className="ag-obj is-link" onClick={open}>
              {object}
            </button>
          ) : (
            <span className="ag-obj">{object}</span>
          )
        ) : null}
        {e.object?.version != null && e.object.kind !== 'other' ? (
          <span className="ag-ver">v{e.object.version}</span>
        ) : null}
        {row.times > 1 ? <span className="ag-times">×{row.times}</span> : null}
      </span>
      <span className="ag-leader" aria-hidden="true" />
      <code className="ag-tool">{e.tool === 'initialize' ? 'initialize' : e.tool}</code>
      {compact ? null : (
        <time className="ag-time" dateTime={e.at}>
          {clock(e.at, lang)}
        </time>
      )}
      {why && !compact ? (
        <div className="ag-why">
          <p>{why.why[lang === 'en' ? 1 : 0]}</p>
          <CopyLine text={why.tell[lang === 'en' ? 1 : 0]} lang={lang} />
        </div>
      ) : null}
    </Root>
  );
}

function Paper({
  row,
  lang,
  work,
  onOpen,
  onAdopt,
}: {
  row: Row;
  lang: 'zh' | 'en';
  work: StreamWork | null;
  onOpen?: (e: AgentEvent) => void;
  onAdopt?: (id: string) => void;
}) {
  const e = row.event;
  const id = e.object?.id ?? '';
  const title = work?.title || e.object?.title || t(lang, '一份草稿', 'A draft');
  const version = work?.version ?? e.object?.version ?? 1;
  const state = work?.removed
    ? t(lang, '已移除', 'Removed')
    : work?.adopted
      ? t(lang, '已采用', 'Adopted')
      : t(lang, '等你检查', 'Waiting for your check');
  return (
    <article className="ag-paper" aria-label={t(lang, '交回的作品', 'Returned work')}>
      <header className="ag-paper-meta">
        <span className="ag-dir is-back" aria-hidden="true">
          <ArrowLeft size={13} strokeWidth={1.8} />
        </span>
        <span>
          {e.verb[lang === 'en' ? 1 : 0]} · {t(lang, `第 ${version} 版`, `version ${version}`)}
        </span>
        <span className="ag-leader" aria-hidden="true" />
        <code className="ag-tool">{e.tool}</code>
        <time className="ag-time" dateTime={e.at}>
          {clock(e.at, lang)}
        </time>
      </header>
      <h3 className="ag-paper-title">{title}</h3>
      {work?.excerpt ? <p className="ag-paper-excerpt">{work.excerpt}</p> : null}
      <footer className="ag-paper-foot">
        <span className={`ag-paper-state${work?.adopted ? ' is-adopted' : ''}`}>{state}</span>
        <span className="ag-grow" />
        {onOpen && id ? (
          <Button variant="ghost" onClick={() => onOpen(e)}>
            {t(lang, '打开', 'Open')}
          </Button>
        ) : null}
        {onAdopt && id && !work?.adopted && !work?.removed ? (
          <Button variant="secondary" onClick={() => onAdopt(id)}>
            {t(lang, '检查并采用', 'Review & adopt')}
          </Button>
        ) : null}
      </footer>
    </article>
  );
}

export function TransmissionStream({
  events,
  variant = 'full',
  onOpen,
  lang = locale(),
  liveFrom = Number.POSITIVE_INFINITY,
  work,
  onAdopt,
  limit = 40,
  empty,
  hat = 'pm',
  filter,
}: TransmissionStreamProps) {
  const reduce = useReducedMotion();
  const [all, setAll] = useState(false);
  const compact = variant === 'compact';
  const rows = useMemo(
    () =>
      foldEvents(
        events.filter(
          (e) => (hat === 'engineer' ? engineerCall(e) : true) && (filter?.(e) ?? true),
        ),
      ),
    [events, hat, filter],
  );
  const shown = compact ? rows.slice(0, 3) : all ? rows : rows.slice(0, limit);
  if (!rows.length) return empty ? <div className="ag-stream-empty">{empty}</div> : null;
  // New rows press in from the top (FLIP for the rest); history appears without motion.
  // A new row never shares a frame with the row it pushes down: the rows below slide first
  // (280ms, strong ease-out), and the new row fades in as they finish (at 160ms they have
  // covered about 93%, less than a row's padding).
  const slide = { duration: 0.28, ease: [0.23, 1, 0.32, 1] as const };
  const enter = reduce
    ? { initial: { opacity: 0 }, animate: { opacity: 1, transition: { duration: 0.16 } } }
    : {
        initial: { opacity: 0, transform: 'translateY(-4px)' },
        animate: {
          opacity: 1,
          transform: 'translateY(0px)',
          transition: { delay: 0.16, duration: 0.16, ease: [0.23, 1, 0.32, 1] as const },
        },
      };
  return (
    <div className={`ag-stream${compact ? ' is-compact' : ''}`}>
      <ol className="ag-rows">
        <AnimatePresence initial={false}>
          {shown.map((row) => {
            const live = Number(row.key) >= liveFrom;
            const paper = isReturn(row.event) && !compact;
            return (
              <motion.li
                key={row.key}
                layout={reduce ? false : 'position'}
                className={`ag-row${paper ? ' is-paper' : ''}`}
                {...(live ? enter : {})}
                transition={reduce ? { duration: 0 } : { layout: slide }}
              >
                {paper ? (
                  <Paper
                    row={row}
                    lang={lang}
                    work={row.event.object?.id && work ? work(row.event.object.id) : null}
                    onOpen={onOpen}
                    onAdopt={onAdopt}
                  />
                ) : (
                  <Line row={row} lang={lang} compact={compact} onOpen={onOpen} />
                )}
              </motion.li>
            );
          })}
        </AnimatePresence>
      </ol>
      {!compact && rows.length > shown.length ? (
        <Button variant="ghost" className="ag-more" onClick={() => setAll(true)}>
          {t(
            lang,
            `显示更早的 ${rows.length - shown.length} 条`,
            `Show ${rows.length - shown.length} earlier`,
          )}
        </Button>
      ) : null}
    </div>
  );
}

/** The plain sentence a screen reader hears for a batch of calls (merged every 2 seconds). */
export function batchSentence(batch: readonly AgentEvent[], lang: 'zh' | 'en'): string {
  const reads = batch.filter((e) => e.direction === 'to_agent' && e.status === 'ok').length;
  const backs = batch.filter((e) => e.direction === 'to_workspace' && e.status === 'ok').length;
  const errors = batch.filter((e) => e.status === 'error').length;
  const parts: string[] = [];
  if (reads) parts.push(t(lang, `读了 ${reads} 次`, `read ${reads} time${reads > 1 ? 's' : ''}`));
  if (backs) parts.push(t(lang, `交回或执行 ${backs} 次`, `handed back or ran ${backs}`));
  if (errors) parts.push(t(lang, `${errors} 次被拒`, `${errors} refused`));
  if (!parts.length) return '';
  const last = batch.at(-1);
  const what = last ? `${last.verb[lang === 'en' ? 1 : 0]} ${last.object?.title ?? ''}`.trim() : '';
  return t(
    lang,
    `你的 Agent ${parts.join('，')}。最近一次：${what}。`,
    `Your agent ${parts.join(', ')}. Latest: ${what}.`,
  );
}

export { verbOf };
