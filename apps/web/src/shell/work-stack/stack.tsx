/** The work stack (v2 spec §4): a small pile of papers in the stage's lower-left corner, like a
 * Dock stack. Hover previews it as a fan (or a grid when the window is short or the pile large),
 * a click pins it, the keyboard walks it, a phone gets a capsule and a bottom sheet. The same
 * component shows the materials pile. It only reads `items`; the caller computes every state. */
import NumberFlow from '@number-flow/react';
import {
  BookOpen,
  Building2,
  Check,
  FileText,
  Flag,
  ListChecks,
  type LucideIcon,
  Plus,
  Search,
  ShieldHalf,
  Sparkle,
  Users,
  Workflow,
} from 'lucide-react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { useCallback, useEffect, useId, useRef, useState } from 'react';
import {
  type StackItem,
  type StackSegment,
  fanOffset,
  initialFocus,
  pendingCount,
  stackLayout,
  topItem,
} from './model';
import { flySheet } from './sheet-transition';
import './stack.css';

const ICONS: Record<string, LucideIcon> = {
  Building2,
  Users,
  Search,
  ShieldHalf,
  Workflow,
  ListChecks,
  Flag,
  FileText,
  BookOpen,
};
const Icon = ({ name, size = 16 }: { name: string; size?: number }) => {
  const C = ICONS[name] ?? FileText;
  return <C size={size} strokeWidth={1.6} aria-hidden="true" />;
};
const ORDER = ['①', '②', '③', '④', '⑤', '⑥', '⑦'];
const glyph = (i: StackItem) => (i.order ? `${ORDER[i.order - 1]} ` : '');

export type StackProps = {
  title: string;
  /** The one most pressing line under the title. */
  status: string;
  /** Read out for the pile button: count, how many hold, what waits. */
  ariaLabel: string;
  items: StackItem[];
  /** Headings between groups in the fan, by segment. */
  segments?: Partial<Record<StackSegment, string>>;
  header?: { title: string; actions: { label: string; plus?: boolean; run(): void }[] };
  /** Phone capsule text, e.g. "Sheets 2/7 ②". */
  capsule: string;
  /** pinned: the pile's line while it is pinned open, e.g. "Pinned · Esc to close". */
  words: { suggested: string; close: string; pinned?: string };
  /** Shown once beside the pile (first visit). */
  hint?: string;
  /** When the hint is shown it calls this once, so the caller can remember it. */
  onHint?(): void;
  /** Kind of pile, for the top paper's look. */
  kind?: 'sheets' | 'materials';
  onOpen(id: string): void;
};
type Open = 'closed' | 'preview' | 'pinned';

const readViewport = () =>
  typeof window === 'undefined' || typeof window.innerWidth !== 'number'
    ? { w: 1440, h: 900 }
    : { w: window.innerWidth, h: window.innerHeight };
function useViewport() {
  const [v, setV] = useState(readViewport);
  useEffect(() => {
    const on = () => setV(readViewport());
    window.addEventListener('resize', on);
    return () => window.removeEventListener('resize', on);
  }, []);
  return v;
}

export function WorkStack(p: StackProps) {
  const [open, setOpen] = useState<Open>('closed');
  const [active, setActive] = useState(-1);
  const reduce = useReducedMotion() ?? false;
  const { w, h } = useViewport();
  // The room above the pile, measured when it opens: a fan that would not fit becomes a grid,
  // and a grid scrolls within it.
  const [room, setRoom] = useState<number | null>(null);
  const fits = room === null || room >= p.items.length * 62 + 64;
  const auto = stackLayout(p.items.length, h, w);
  const layout = auto === 'fan' && !fits ? 'grid' : auto;
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const pile = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const enter = useRef<ReturnType<typeof setTimeout>>(undefined);
  const leave = useRef<ReturnType<typeof setTimeout>>(undefined);
  const top = topItem(p.items);
  const badge = pendingCount(p.items);
  const agent = p.items.some((i) => i.agentDraft);
  // Fan: ① sits nearest the pile, so the list reads from ⑦ at the top down to ①.
  const shown = layout === 'fan' ? [...p.items].reverse() : p.items;

  const close = useCallback((focusPile: boolean) => {
    setOpen('closed');
    setActive(-1);
    if (focusPile) pile.current?.focus({ preventScroll: true });
  }, []);
  const pin = useCallback(
    (focusItem: boolean) => {
      setOpen('pinned');
      if (focusItem) {
        const at = initialFocus(p.items);
        setActive(layout === 'fan' ? p.items.length - 1 - at : at);
      }
    },
    [p.items, layout],
  );

  useEffect(() => {
    if (open === 'closed') return;
    const top = root.current?.getBoundingClientRect().top;
    if (typeof top === 'number') setRoom(Math.max(160, top - 72));
  }, [open]);

  // Focus follows the roving index once the list exists.
  useEffect(() => {
    if (active < 0 || open === 'closed') return;
    list.current
      ?.querySelectorAll<HTMLButtonElement>('[data-stack-item]')
      [active]?.focus({ preventScroll: true });
  }, [active, open]);

  // Pinned: a press outside closes it.
  useEffect(() => {
    if (open !== 'pinned') return;
    const down = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) close(false);
    };
    document.addEventListener('pointerdown', down, true);
    return () => document.removeEventListener('pointerdown', down, true);
  }, [open, close]);

  // First visit: lift once and say where the sheets are.
  const [hinting, setHinting] = useState(!!p.hint);
  const onHint = useRef(p.onHint);
  onHint.current = p.onHint;
  // A hint that arrives later (after the walk-through) still plays once.
  useEffect(() => {
    if (p.hint) setHinting(true);
  }, [p.hint]);
  useEffect(() => {
    if (!hinting) return;
    onHint.current?.();
    const t = setTimeout(() => setHinting(false), 4200);
    return () => clearTimeout(t);
  }, [hinting]);

  const hoverIn = (e: React.PointerEvent) => {
    if (e.pointerType !== 'mouse') return;
    clearTimeout(leave.current);
    if (open === 'closed') enter.current = setTimeout(() => setOpen('preview'), 120);
  };
  const hoverOut = (e: React.PointerEvent) => {
    if (e.pointerType !== 'mouse') return;
    clearTimeout(enter.current);
    if (open === 'preview') leave.current = setTimeout(() => setOpen('closed'), 280);
  };
  useEffect(
    () => () => {
      clearTimeout(enter.current);
      clearTimeout(leave.current);
    },
    [],
  );

  // The pile owns its keys: Esc closes the open pile (never the sheet behind it), and Enter,
  // Space and the arrows open it with focus on the suggested sheet.
  const onPileKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape' && open !== 'closed') {
      e.preventDefault();
      e.stopPropagation();
      close(true);
    } else if (['ArrowUp', 'ArrowDown', 'Enter', ' '].includes(e.key)) {
      e.preventDefault();
      clearTimeout(enter.current);
      pin(true);
    }
  };
  const onListKey = (e: React.KeyboardEvent) => {
    const n = shown.length;
    const cols = layout === 'grid' ? 3 : 1;
    const move = (to: number) => {
      e.preventDefault();
      setActive(Math.max(0, Math.min(n - 1, to)));
    };
    const at = Math.max(0, active);
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      close(true);
    } else if (e.key === 'ArrowUp') move(at - cols);
    else if (e.key === 'ArrowDown') move(at + cols);
    else if (layout === 'grid' && e.key === 'ArrowLeft') move(at - 1);
    else if (layout === 'grid' && e.key === 'ArrowRight') move(at + 1);
    else if (e.key === 'Home') move(0);
    else if (e.key === 'End') move(n - 1);
  };
  const choose = (item: StackItem, event: React.MouseEvent<HTMLButtonElement>) => {
    const openSheet = () => {
      close(false);
      p.onOpen(item.id);
    };
    const thumb = event.currentTarget.querySelector<HTMLElement>('.ws-stack__thumb');
    if (p.kind === 'materials' || event.detail === 0 || reduce || !thumb) openSheet();
    else flySheet(thumb, openSheet);
  };

  const isOpen = open !== 'closed';
  const panelId = `${id}-panel`;
  const quick = { duration: 0.12 };
  // About 280ms to settle with a slight overshoot; closing runs top-down, quicker, no bounce.
  const spring = { type: 'spring' as const, stiffness: 420, damping: 32, mass: 0.9 };
  const away = (fromTop: number) => ({
    duration: 0.14,
    ease: [0.4, 0, 1, 1] as const,
    delay: fromTop * 0.016,
  });

  // Materials stay in the board on phones; omit the hidden pile from keyboard navigation too.
  if (w < 768 && p.kind === 'materials') return null;

  return (
    <div
      ref={root}
      className="ws-stack"
      data-layout={layout}
      data-open={open}
      data-kind={p.kind ?? 'sheets'}
      onPointerEnter={hoverIn}
      onPointerLeave={hoverOut}
    >
      <AnimatePresence>
        {open === 'pinned' && (
          <motion.div
            key="scrim"
            className="ws-stack__scrim"
            aria-hidden="true"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={quick}
            onClick={() => close(false)}
          />
        )}
      </AnimatePresence>
      <AnimatePresence>
        {isOpen && (
          <motion.div
            key="panel"
            id={panelId}
            className={`ws-stack__panel ws-stack__panel--${layout}`}
            style={room ? ({ '--room': `${room}px` } as React.CSSProperties) : undefined}
            initial={
              reduce ? { opacity: 0 } : layout === 'fan' ? { opacity: 1 } : { opacity: 0, y: 8 }
            }
            animate={{ opacity: 1, y: 0 }}
            exit={
              reduce
                ? { opacity: 0, transition: quick }
                : { opacity: 0, transition: { duration: 0.1, delay: shown.length * 0.016 + 0.06 } }
            }
            transition={reduce ? quick : spring}
            onKeyDown={onListKey}
          >
            {p.header && (
              <div className="ws-stack__head">
                <span className="ws-stack__head-title">{p.header.title}</span>
                {p.header.actions.map((a) => (
                  <button
                    type="button"
                    key={a.label}
                    className="ws-stack__head-action"
                    data-plus={a.plus || undefined}
                    onClick={() => {
                      close(false);
                      a.run();
                    }}
                  >
                    {a.plus && <Plus size={13} strokeWidth={1.8} aria-hidden="true" />}
                    {a.label}
                  </button>
                ))}
              </div>
            )}
            <ul ref={list} className="ws-stack__list" aria-label={p.title}>
              {shown.map((item, i) => {
                const prev = shown[i - 1];
                const heading =
                  layout === 'fan' && p.segments && prev?.segment !== item.segment
                    ? p.segments[item.segment]
                    : undefined;
                // Index from the pile upward, for the stagger and the fan's drift.
                const fromPile = layout === 'fan' ? shown.length - 1 - i : i;
                const { x, rotate } = layout === 'fan' ? fanOffset(fromPile) : { x: 0, rotate: 0 };
                // Only the paper turns; its label stays level so the words stay sharp.
                const tilt = { '--tilt': `${rotate}deg` } as React.CSSProperties;
                return (
                  <motion.li
                    key={item.id}
                    className="ws-stack__row"
                    style={tilt}
                    initial={
                      reduce
                        ? { opacity: 0, x, y: 0, scale: 1 }
                        : layout === 'fan'
                          ? { opacity: 0, y: 18 + fromPile * 6, x: 0, scale: 0.94 }
                          : { opacity: 0, scale: 0.96 }
                    }
                    animate={{ opacity: 1, y: 0, x, scale: 1 }}
                    exit={
                      reduce
                        ? { opacity: 0, transition: quick }
                        : { opacity: 0, y: 10, transition: away(i) }
                    }
                    transition={reduce ? quick : { ...spring, delay: fromPile * 0.024 }}
                  >
                    {heading && <span className="ws-stack__segment">{heading}</span>}
                    <button
                      type="button"
                      data-stack-item
                      className="ws-stack__item"
                      data-suggested={item.suggested || undefined}
                      tabIndex={active === i || (active < 0 && i === 0) ? 0 : -1}
                      onFocus={() => setActive(i)}
                      onClick={(event) => choose(item, event)}
                    >
                      <Thumb item={item} dot={layout !== 'grid'} />
                      {layout === 'grid' && <Dot status={item.status} />}
                      <span className="ws-stack__label">
                        <span className="ws-stack__name">
                          {glyph(item)}
                          {layout === 'grid' ? (item.short ?? item.name) : item.name}
                          {item.suggested && (
                            <span className="ws-stack__tag">{p.words.suggested}</span>
                          )}
                        </span>
                        <span className="ws-stack__state" data-status={item.status}>
                          {item.statusText}
                          {item.recheckReason ? ` · ${item.recheckReason}` : ''}
                        </span>
                        {layout !== 'grid' && (
                          <span className="ws-stack__more">
                            {item.purpose}
                            {item.gapHint ? ` ${item.gapHint}` : ''}
                          </span>
                        )}
                      </span>
                    </button>
                  </motion.li>
                );
              })}
            </ul>
            {layout === 'sheet' && (
              <button type="button" className="ws-stack__sheet-close" onClick={() => close(true)}>
                {p.words.close}
              </button>
            )}
          </motion.div>
        )}
      </AnimatePresence>
      <button
        ref={pile}
        type="button"
        className="ws-stack__pile"
        aria-expanded={isOpen}
        aria-controls={panelId}
        aria-label={p.ariaLabel}
        data-hint={hinting || undefined}
        onClick={() => {
          // A click inside the hover delay must not be turned back into a preview by the timer.
          clearTimeout(enter.current);
          if (open === 'pinned') close(false);
          else pin(false);
        }}
        onKeyDown={onPileKey}
      >
        {layout === 'sheet' ? (
          <span className="ws-stack__capsule">
            {top && <Icon name={top.icon} size={15} />}
            {p.capsule}
            {badge > 0 && <span className="ws-stack__badge">{badge}</span>}
          </span>
        ) : (
          <>
            <span className="ws-stack__papers" aria-hidden="true">
              <span className="ws-stack__paper ws-stack__paper--back" />
              <span className="ws-stack__paper ws-stack__paper--mid" />
              <AnimatePresence initial={false} mode="popLayout">
                <motion.span
                  key={top?.id ?? 'empty'}
                  className="ws-stack__paper ws-stack__paper--top"
                  data-segment={top?.segment}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: reduce ? 0 : 0.16 }}
                >
                  {top && <Icon name={top.icon} size={18} />}
                </motion.span>
              </AnimatePresence>
              {badge > 0 && (
                <span className="ws-stack__badge">
                  <NumberFlow value={badge} />
                </span>
              )}
              {agent && (
                <span className="ws-stack__agent">
                  <Sparkle size={9} strokeWidth={2.2} />
                </span>
              )}
            </span>
            <span className="ws-stack__caption" aria-hidden="true">
              <span className="ws-stack__title">{p.title}</span>
              <span className="ws-stack__status">
                {open === 'pinned' && p.words.pinned ? p.words.pinned : p.status}
              </span>
            </span>
          </>
        )}
      </button>
      {hinting && p.hint && layout !== 'sheet' && (
        <span className="ws-stack__hint" role="status">
          {p.hint}
        </span>
      )}
    </div>
  );
}

const Dot = ({ status }: { status: StackItem['status'] }) => (
  <span className="ws-stack__dot" data-status={status} aria-hidden="true">
    {status === 'solid' && <Check size={9} strokeWidth={3} />}
    {status === 'recheck' && '!'}
  </span>
);

// A sheet's paper: its icon, the segment's colour along the top, its state in the corner (the
// grid puts the state in the cell's corner instead, clear of the icon).
function Thumb({ item, dot }: { item: StackItem; dot: boolean }) {
  return (
    <span className="ws-stack__thumb" data-segment={item.segment} aria-hidden="true">
      <Icon name={item.icon} size={17} />
      {dot && <Dot status={item.status} />}
      {item.agentDraft && (
        <span className="ws-stack__agent ws-stack__agent--thumb">
          <Sparkle size={8} strokeWidth={2.2} />
        </span>
      )}
    </span>
  );
}
