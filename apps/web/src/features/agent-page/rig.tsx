// The rig: your workspace on the left, your agent on the right, and the conduit between them.
// ★ Signature moment (the third of three): the conduit is drawn once, the moment the agent
// connects, and every real tool call sends one short ink pulse along it in the direction the
// content travels (reading: workspace → agent; handing back: agent → workspace). It never loops.
// The workspace row the call touched lights up; the agent's lamp rings once.
// Technique after Magic UI Animated Beam (MIT): one straight line, no gradient colours.
// Motion exceptions (allowed for the signature only): the pulse travels 520ms with the strong
// ease-in-out, the draw is a 520ms scaleX; both fall back to a 160ms fade with reduced motion.
import { BookOpen, ClipboardList, FileText, FlaskConical, ListTodo, Ticket } from 'lucide-react';
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { onAgentEvent } from '../../shell/agent-bus';
import type { AgentEvent } from './feed';
import type { WorkspaceRow } from './index';
import { failedVerb } from './stream';

type Phase = 'none' | 'waiting' | 'connected' | 'idle';
const EASE_IO = 'cubic-bezier(.77,0,.175,1)';
const EASE_OUT = 'cubic-bezier(.23,1,.32,1)';
const ICONS = {
  documents: FileText,
  brief: BookOpen,
  tests: FlaskConical,
  work: ClipboardList,
  tasks: ListTodo,
  ticket: Ticket,
};
const t = (lang: 'zh' | 'en', zh: string, en: string) => (lang === 'en' ? en : zh);
const reduced = () =>
  typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;

/** Narrow screens stack workspace, conduit and agent; the conduit then runs top to bottom. */
const NARROW = '(max-width: 760px)';
function useVertical() {
  return useSyncExternalStore(
    (cb) => {
      if (typeof matchMedia === 'undefined') return () => {};
      const q = matchMedia(NARROW);
      q.addEventListener('change', cb);
      return () => q.removeEventListener('change', cb);
    },
    () => typeof matchMedia !== 'undefined' && matchMedia(NARROW).matches,
  );
}

/** Which workspace rows a call touched. */
export function rowsHit(e: AgentEvent): WorkspaceRow['key'][] {
  const tool = e.tool;
  if (tool === 'observation' || tool === 'tools' || tool === 'initialize')
    return ['documents', 'brief', 'tests', 'work', 'tasks', 'ticket'];
  if (tool.startsWith('engineer.'))
    return ['ticket', ...(tool === 'engineer.trial' ? ['tests' as const] : [])];
  if (tool.startsWith('work_items.')) return ['tasks'];
  if (tool.startsWith('tests.') || e.object?.kind === 'test') return ['tests'];
  if (tool.startsWith('work_products.') || e.object?.kind === 'work_product') return ['work'];
  if (tool === 'materials.list' || e.object?.kind === 'material') return ['documents'];
  return [];
}

export function Rig({
  phase,
  client,
  lastSeen,
  workspace,
  lang,
  caption,
  children,
  settled = true,
}: {
  /** False until the first read: the state the page opens on is never drawn as an event. */
  settled?: boolean;
  phase: Phase;
  client: string;
  lastSeen?: string;
  workspace: WorkspaceRow[];
  lang: 'zh' | 'en';
  caption?: React.ReactNode;
  children?: React.ReactNode;
}) {
  const line = useRef<HTMLDivElement>(null);
  const packet = useRef<HTMLDivElement>(null);
  const ends = useRef<{ ws: HTMLSpanElement | null; agent: HTMLSpanElement | null }>({
    ws: null,
    agent: null,
  });
  const lamp = useRef<HTMLSpanElement>(null);
  const [hit, setHit] = useState<Record<string, number>>({});
  const vertical = useVertical();
  const axis = useRef(vertical);
  axis.current = vertical;
  const [now, setNow] = useState<{ e: AgentEvent; n: number } | null>(null);
  const shown = useRef(phase);
  const queue = useRef<AgentEvent[]>([]);
  const busy = useRef(false);

  // The draw: only when the connection happens on this screen, never on arrival.
  useEffect(() => {
    const was = shown.current;
    shown.current = phase;
    if (!settled) {
      shown.current = 'connected';
      return;
    }
    const el = line.current;
    if (!el || phase !== 'connected' || was === 'connected' || was === 'idle') return;
    if (reduced()) {
      el.animate({ opacity: [0, 1] }, { duration: 160 });
      return;
    }
    el.animate(
      { transform: axis.current ? ['scaleY(0)', 'scaleY(1)'] : ['scaleX(0)', 'scaleX(1)'] },
      { duration: 520, easing: EASE_IO, fill: 'backwards' },
    );
    for (const end of [ends.current.ws, ends.current.agent])
      end?.animate(
        { transform: ['scale(.6)', 'scale(1)'], opacity: [0, 1] },
        {
          duration: 280,
          delay: end === ends.current.agent ? 400 : 0,
          easing: EASE_OUT,
          fill: 'backwards',
        },
      );
  }, [phase, settled]);

  useEffect(() => {
    const ring = (el: HTMLElement | null) =>
      el?.animate(
        { transform: ['scale(1)', 'scale(2.2)'], opacity: [0.45, 0] },
        { duration: 520, easing: EASE_OUT, pseudoElement: '::after' },
      );
    const travel = async (e: AgentEvent) => {
      const el = packet.current;
      const track = line.current;
      const toAgent = e.direction === 'to_agent';
      const touched = rowsHit(e);
      const stamp = Date.now();
      setHit((h) => ({ ...h, ...Object.fromEntries(touched.map((k) => [k, stamp])) }));
      setNow((n) => ({ e, n: (n?.n ?? 0) + 1 }));
      ring(lamp.current);
      if (!el || !track) return;
      const down = axis.current;
      el.dataset.dir = down ? (toAgent ? 'down' : 'up') : toAgent ? 'right' : 'left';
      el.dataset.state = e.status;
      const w = down ? track.clientHeight : track.clientWidth;
      const len = down ? el.offsetHeight : el.offsetWidth;
      const dest = toAgent ? ends.current.agent : ends.current.ws;
      if (reduced()) {
        await dest?.animate({ opacity: [0.4, 1] }, { duration: 160 }).finished;
        return;
      }
      const from = toAgent ? -len : w;
      const to = toAgent ? w : -len;
      await el.animate(
        {
          transform: down
            ? [`translateY(${from}px)`, `translateY(${to}px)`]
            : [`translateX(${from}px)`, `translateX(${to}px)`],
          opacity: [0, 1, 1, 0],
        },
        { duration: 520, easing: EASE_IO },
      ).finished;
      if (e.status === 'ok') ring(dest);
    };
    const drain = async () => {
      if (busy.current) return;
      busy.current = true;
      while (queue.current.length) {
        const next = queue.current.shift() as AgentEvent;
        try {
          await travel(next);
        } catch {
          /* an interrupted animation is fine */
        }
        await new Promise((r) => setTimeout(r, 90));
      }
      busy.current = false;
    };
    return onAgentEvent((e) => {
      // A burst keeps its latest few pulses; the stream still lists every call.
      queue.current = [...queue.current, e].slice(-4);
      void drain();
    });
  }, []);

  useEffect(() => {
    if (!Object.keys(hit).length) return;
    const id = setTimeout(() => setHit({}), 700);
    return () => clearTimeout(id);
  }, [hit]);

  const live = phase === 'connected';
  const agentName =
    phase === 'none' || phase === 'waiting' ? t(lang, '你的 Agent', 'Your agent') : client;
  const state =
    phase === 'connected'
      ? t(lang, '已连接', 'Connected')
      : phase === 'idle'
        ? t(
            lang,
            `最近一次 ${clockShort(lastSeen, lang)}`,
            `Last seen ${clockShort(lastSeen, lang)}`,
          )
        : phase === 'waiting'
          ? t(lang, '等待中', 'Waiting')
          : t(lang, '还没连接', 'Not connected');

  return (
    <section
      className={`ag-rig${vertical ? ' is-vertical' : ''}`}
      data-phase={phase}
      aria-label={t(lang, '工作区与 Agent', 'Workspace and agent')}
    >
      <div className="ag-side ag-ws">
        <p className="ag-side-title">{t(lang, '你的工作区', 'Your workspace')}</p>
        <ul className="ag-ws-rows">
          {workspace.map((row) => {
            const Icon = ICONS[row.key];
            return (
              <li
                key={row.key}
                className={`ag-ws-row${hit[row.key] ? ' is-hit' : ''}`}
                data-ws={row.key}
              >
                <Icon size={14} strokeWidth={1.6} aria-hidden="true" />
                <span className="ag-ws-label">{row.label[lang === 'en' ? 1 : 0]}</span>
                <span className="ag-ws-value">{row.value}</span>
              </li>
            );
          })}
        </ul>
      </div>

      <div className="ag-conduit">
        <div className="ag-caption" aria-hidden="true">
          {now && live ? (
            <span
              key={now.n}
              className={`ag-caption-text${now.e.status === 'error' ? ' is-error' : ''}`}
            >
              <b>
                {now.e.status === 'error'
                  ? failedVerb(now.e, lang)
                  : now.e.verb[lang === 'en' ? 1 : 0]}
              </b>{' '}
              {now.e.object?.title ?? ''}
            </span>
          ) : (
            caption
          )}
        </div>
        <div className="ag-track">
          <span
            className="ag-end is-ws"
            ref={(n) => {
              ends.current.ws = n;
            }}
          />
          <div className="ag-wire" ref={line} />
          <div className="ag-packet" ref={packet} />
          <span
            className="ag-end is-agent"
            ref={(n) => {
              ends.current.agent = n;
            }}
          />
        </div>
        <div className="ag-conduit-slot">{children}</div>
      </div>

      <div className="ag-side ag-agent">
        <div className="ag-agent-id">
          <span className="ag-agent-mark" aria-hidden="true">
            {phase === 'connected' || phase === 'idle' ? initial(client) : ''}
          </span>
          <div className="ag-agent-text">
            <p className="ag-agent-name">{agentName}</p>
            <p className="ag-agent-state">
              <span className="ag-lamp" ref={lamp} aria-hidden="true" />
              <span>{state}</span>
            </p>
          </div>
        </div>
        <p className="ag-agent-scope">
          {phase === 'none'
            ? t(
                lang,
                'Claude Code、Codex 或任何 MCP 客户端。',
                'Claude Code, Codex or any MCP client.',
              )
            : t(
                lang,
                '能读整个工作区，能交回草稿、跑测试。',
                'Reads the whole workspace, hands back drafts and runs tests.',
              )}
        </p>
      </div>
    </section>
  );
}

function initial(name: string) {
  const n = name.trim();
  return n ? n[0].toUpperCase() : 'A';
}
function clockShort(iso: string | undefined, lang: 'zh' | 'en') {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ''
    : d.toLocaleTimeString(lang === 'en' ? 'en-GB' : 'zh-CN', {
        hour: '2-digit',
        minute: '2-digit',
      });
}
