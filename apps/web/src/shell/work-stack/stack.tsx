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
  words: { suggested: string; close: string };
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
  const layout = stackLayout(p.items.length, h, w);
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

  const onPileKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowUp') {
      e.preventDefault();
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
      close(true);
    } else if (e.key === 'ArrowUp') move(at - cols);
    else if (e.key === 'ArrowDown') move(at + cols);
    else if (layout === 'grid' && e.key === 'ArrowLeft') move(at - 1);
    else if (layout === 'grid' && e.key === 'ArrowRight') move(at + 1);
    else if (e.key === 'Home') move(0);
    else if (e.key === 'End') move(n - 1);
  };
  const choose = (item: StackItem) => {
    close(false);
    p.onOpen(item.id);
  };

  const isOpen = open !== 'closed';
  const panelId = `${id}-panel`;
  const quick = { duration: 0.12 };
  const spring = { type: 'spring' as const, duration: 0.28, bounce: 0.18 };

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
            initial={
              reduce ? { opacity: 0 } : layout === 'fan' ? { opacity: 1 } : { opacity: 0, y: 8 }
            }
            animate={{ opacity: 1, y: 0 }}
            exit={
              reduce
                ? { opacity: 0, transition: quick }
                : { opacity: 0, transition: { duration: 0.16 } }
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
                return (
                  <motion.li
                    key={item.id}
                    className="ws-stack__row"
                    initial={
                      reduce
                        ? { opacity: 0 }
                        : layout === 'fan'
                          ? { opacity: 0, y: 18 + fromPile * 6, x: 0, rotate: 0, scale: 0.94 }
                          : { opacity: 0, scale: 0.96 }
                    }
                    animate={{ opacity: 1, y: 0, x, rotate, scale: 1 }}
                    exit={
                      reduce
                        ? { opacity: 0 }
                        : { opacity: 0, y: 10, transition: { duration: 0.16 } }
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
                      onClick={() => choose(item)}
                    >
                      <Thumb item={item} />
                      <span className="ws-stack__label">
                        <span className="ws-stack__name">
                          {glyph(item)}
                          {item.name}
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
        onClick={() => (open === 'pinned' ? close(false) : pin(false))}
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
              <span className="ws-stack__status">{p.status}</span>
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

// A sheet's paper: its icon, the segment's colour along the top, its state in the corner.
function Thumb({ item }: { item: StackItem }) {
  return (
    <span className="ws-stack__thumb" data-segment={item.segment} aria-hidden="true">
      <Icon name={item.icon} size={17} />
      <span className="ws-stack__dot" data-status={item.status}>
        {item.status === 'solid' && <Check size={9} strokeWidth={3} />}
        {item.status === 'recheck' && '!'}
      </span>
      {item.agentDraft && (
        <span className="ws-stack__agent ws-stack__agent--thumb">
          <Sparkle size={8} strokeWidth={2.2} />
        </span>
      )}
    </span>
  );
}
