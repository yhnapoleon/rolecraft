// The problem ruler under the topbar: six layers on one track, and right under it the five
// things a person needs at a glance (where am I, what is this layer for, what is confirmed,
// what is missing, what comes next and after). "Viewing" (a layer picked on the track) is kept
// apart from the progress itself: looking at another layer never moves or undoes anything.
// A passed layer leaves a short distillation in place. The map opens the same data as an
// open path of six stops for the overview. Labels arrive already in the interface language.
import { AnimatePresence, LayoutGroup, motion, useReducedMotion } from 'motion/react';
import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { runAction } from './registry';
import { showToast } from './toast';

const EASE_OUT = [0.23, 1, 0.32, 1] as const;

export type BandLayer = {
  id: string;
  n: number;
  label: string;
  goal: string;
  state: 'done' | 'current' | 'reopened' | 'todo' | 'uncovered';
  confirmed: string[];
  missing: string[];
  reopened?: string;
  /** The distillation left when the layer was passed. */
  distilled?: { confirmed: string[]; kept: string[] };
};

export type ProgressBandProps = {
  layers: BandLayer[];
  current: string;
  /** Missing pieces carried into the current layer from reopened ones. */
  carried: string[];
  /** A layer just passed whose distillation should arrive now (once). */
  arrived?: string;
  /** The person's own choice for this kind of page; null leaves it to the default below. */
  folded: boolean | null;
  /** Folded unless chosen otherwise (pages where the work itself is done); phone width always is. */
  foldedByDefault: boolean;
  /** The layer whose screen is open when it is not the current layer's (the dossier, the result). */
  routeViewing?: string;
  /** A way into a layer's own screen, shown in its column when it is the one in view. */
  actions?: Record<string, { label: string; action: string; data?: Record<string, string> }>;
  /** Leaves a layer's screen for the current one (when the route, not the track, is viewing). */
  back?: { label: string; action: string };
  words: {
    label: string;
    now: string;
    missing: string;
    nothingMissing: string;
    confirmed: string;
    next: string;
    after: string;
    basis: string;
    basisHint: string;
    map: string;
    fold: string;
    unfold: string;
    viewing: string;
    backToNow: string;
    distilled: string;
    kept: string;
    gotIt: string;
    close: string;
    mapTitle: string;
    mapLead: string;
    states: Record<BandLayer['state'], string>;
    stepOf: (n: number, total: number, label: string) => string;
    /** At the last layer, in place of "next": what can follow. */
    ending: { title: string; items: string[] };
  };
  lang?: string;
  onFold: (folded: boolean) => void;
  onArrivedSeen: (id: string) => void;
};

const num = (n: number) => String(n).padStart(2, '0');
const PHONE = '(max-width: 720px)';
/** Phone width, followed live (a window resized, a phone turned). */
function useNarrow() {
  const [narrow, setNarrow] = useState(() => window.matchMedia?.(PHONE).matches ?? false);
  useEffect(() => {
    const mq = window.matchMedia?.(PHONE);
    if (!mq) return;
    const on = () => setNarrow(mq.matches);
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, []);
  return narrow;
}
const run = (a: { action: string; data?: Record<string, string> }) => {
  runAction(a.action, undefined, a.data).catch((e: unknown) =>
    showToast(e instanceof Error ? e.message : String(e)),
  );
};

export function ProgressBand(props: ProgressBandProps) {
  const narrow = useNarrow();
  const p = { ...props, folded: props.folded ?? (props.foldedByDefault || narrow) };
  const reduce = useReducedMotion();
  const [viewing, setViewing] = useState<string | null>(null);
  const [mapOpen, setMapOpen] = useState(false);
  const gid = useId();
  // Once the full band scrolls out of #main, a slim copy docks at the top of it, so where you are
  // stays on screen while the board or a document is read further down. It docks only once the
  // whole band has left, so the two never overlap.
  const self = useRef<HTMLElement>(null);
  const [docked, setDocked] = useState(false);
  // Measured on scroll rather than observed: ui.js replaces #main on a full redraw, which would
  // leave an IntersectionObserver watching a detached root.
  useEffect(() => {
    let raf = 0;
    const measure = () => {
      raf = 0;
      const el = self.current;
      const root = el?.closest('#main');
      if (!el || !root) return;
      setDocked(el.getBoundingClientRect().bottom < root.getBoundingClientRect().top + 40);
    };
    const soon = () => {
      if (!raf) raf = requestAnimationFrame(measure);
    };
    measure();
    document.addEventListener('scroll', soon, { capture: true, passive: true });
    addEventListener('resize', soon);
    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener('scroll', soon, { capture: true });
      removeEventListener('resize', soon);
    };
  }, []);
  // A redraw can move the band (another page under it) without a scroll.
  useEffect(() => {
    const el = self.current;
    const root = el?.closest('#main');
    if (el && root)
      setDocked(el.getBoundingClientRect().bottom < root.getBoundingClientRect().top + 40);
  });
  // biome-ignore lint/correctness/useExhaustiveDependencies: a new frontier ends a look elsewhere
  useEffect(() => setViewing(null), [p.current]);
  const at = Math.max(
    0,
    p.layers.findIndex((l) => l.id === p.current),
  );
  const looking = viewing ?? (p.routeViewing !== p.current ? p.routeViewing : undefined) ?? null;
  const shown = p.layers.find((l) => l.id === (looking ?? p.current)) ?? p.layers[at];
  const isNow = shown.id === p.current;
  const open = p.actions?.[shown.id];
  const after = p.layers.slice(at + 1, at + 3);
  const arrived = p.arrived ? p.layers.find((l) => l.id === p.arrived) : undefined;
  const slide = reduce
    ? { duration: 0 }
    : { type: 'spring' as const, duration: 0.42, bounce: 0.12 };
  const fill = (at + (p.layers[at]?.state === 'current' ? 0.5 : 0)) / (p.layers.length - 1);
  const missing = isNow ? [...shown.missing, ...p.carried] : shown.missing;
  return (
    <>
      <div
        className="rc-prog-dock"
        data-on={docked || undefined}
        aria-hidden={!docked || undefined}
      >
        <div className="rc-prog-dock__bar" inert={!docked || undefined}>
          <ol className="rc-prog-dock__dots">
            {p.layers.map((l) => (
              <li
                key={l.id}
                data-state={l.state}
                title={`${num(l.n)} ${l.label} · ${p.words.states[l.state]}`}
              />
            ))}
          </ol>
          <b className="rc-prog-dock__now">
            <span className="rc-prog__n">{num(p.layers[at].n)}</span>
            {p.layers[at].label}
          </b>
          <span className="rc-prog-dock__part">
            {p.words.missing} ·{' '}
            {[...p.layers[at].missing, ...p.carried][0] ?? p.words.nothingMissing}
          </span>
          {p.layers[at + 1] && (
            <span className="rc-prog-dock__part rc-prog-dock__next">
              {p.words.next} · {num(p.layers[at + 1].n)} {p.layers[at + 1].label}
            </span>
          )}
          <button
            type="button"
            className="btn quiet small rc-prog-dock__map"
            onClick={() => setMapOpen(true)}
          >
            {p.words.map}
          </button>
        </div>
      </div>
      <section
        ref={self}
        className="rc-prog"
        aria-label={p.words.label}
        data-folded={p.folded || undefined}
        data-viewing={!isNow || undefined}
      >
        <div className="rc-prog__top">
          <LayoutGroup id={gid}>
            <ol className="rc-prog__track" style={{ ['--fill' as string]: String(fill) }}>
              <span className="rc-prog__line" aria-hidden="true">
                <motion.i
                  className="rc-prog__walked"
                  initial={false}
                  animate={{ scaleX: fill }}
                  transition={reduce ? { duration: 0 } : { duration: 0.52, ease: EASE_OUT }}
                />
              </span>
              {p.layers.map((l) => (
                <li key={l.id} className="rc-prog__stop" data-state={l.state}>
                  <button
                    type="button"
                    className="rc-prog__key"
                    aria-current={l.id === p.current ? 'step' : undefined}
                    aria-pressed={looking ? looking === l.id : undefined}
                    aria-label={`${p.words.stepOf(l.n, p.layers.length, l.label)} · ${p.words.states[l.state]}`}
                    onClick={() => setViewing(l.id === p.current ? null : l.id)}
                  >
                    <span className="rc-prog__dot" aria-hidden="true">
                      {l.id === p.current && (
                        <motion.span
                          layoutId="now"
                          className="rc-prog__now-disc"
                          transition={slide}
                        />
                      )}
                      <span className="rc-prog__glyph">
                        {l.state === 'done' ? (
                          <svg viewBox="0 0 16 16" aria-hidden="true">
                            <path d="m3.5 8.5 3 3 6-7" />
                          </svg>
                        ) : (
                          num(l.n)
                        )}
                      </span>
                    </span>
                    <span className="rc-prog__name">{l.label}</span>
                    {l.id === (looking ?? '') && (
                      <motion.span
                        layoutId="viewing"
                        className="rc-prog__look"
                        transition={slide}
                      />
                    )}
                  </button>
                </li>
              ))}
            </ol>
          </LayoutGroup>
          <div className="rc-prog__tools">
            <span className="rc-prog__basis" title={p.words.basisHint}>
              {p.words.basis}
            </span>
            <button type="button" className="btn quiet small" onClick={() => setMapOpen(true)}>
              <svg viewBox="0 0 16 16" className="rc-prog__i" aria-hidden="true">
                <path d="M2.5 12.5c2-1 2.5-4 5-4.5s3.5 1.5 6-3M2.5 12.5h0M13.5 5h0" />
                <circle cx="2.5" cy="12.5" r="1.3" />
                <circle cx="13.5" cy="5" r="1.3" />
              </svg>
              {p.words.map}
            </button>
            <button
              type="button"
              className="btn quiet icon small rc-prog__fold"
              aria-expanded={!p.folded}
              aria-label={p.folded ? p.words.unfold : p.words.fold}
              title={p.folded ? p.words.unfold : p.words.fold}
              onClick={() => p.onFold(!p.folded)}
            >
              <svg viewBox="0 0 16 16" className="rc-prog__i" aria-hidden="true">
                <path d={p.folded ? 'm4 6 4 4 4-4' : 'm4 10 4-4 4 4'} />
              </svg>
            </button>
          </div>
        </div>
        {p.folded && (
          // Folded, one line still says the five things: where, what is missing, what is next.
          <p className="rc-prog__brief" aria-live="polite">
            <b>
              <span className="rc-prog__n">{num(shown.n)}</span>
              {shown.label}
            </b>
            <span className="rc-prog__brief-part">
              {p.words.missing} · {missing[0] ?? p.words.nothingMissing}
            </span>
            {after[0] && (
              <span className="rc-prog__brief-part">
                {p.words.next} · {num(after[0].n)} {after[0].label}
              </span>
            )}
          </p>
        )}
        <AnimatePresence initial={false}>
          {!p.folded && (
            <motion.div
              key="body"
              className="rc-prog__body"
              initial={reduce ? { opacity: 0 } : { opacity: 0, height: 0 }}
              animate={reduce ? { opacity: 1 } : { opacity: 1, height: 'auto' }}
              exit={reduce ? { opacity: 0 } : { opacity: 0, height: 0 }}
              transition={{ duration: reduce ? 0.16 : 0.28, ease: EASE_OUT }}
            >
              <div className="rc-prog__cols" aria-live="polite">
                <div className="rc-prog__col rc-prog__col--now">
                  <p className="rc-prog__eyebrow">
                    {isNow ? p.words.now : `${p.words.viewing} · ${p.words.states[shown.state]}`}
                  </p>
                  <h2 className="rc-prog__title">
                    <span className="rc-prog__n">{num(shown.n)}</span>
                    {shown.label}
                  </h2>
                  <p className="rc-prog__goal">{shown.goal}</p>
                  <span className="rc-prog__keys">
                    {open && (
                      <button
                        type="button"
                        className="btn small rc-prog__open"
                        onClick={() => run(open)}
                      >
                        {open.label}
                      </button>
                    )}
                    {!isNow && (
                      <button
                        type="button"
                        className="btn quiet small rc-prog__back"
                        onClick={() =>
                          viewing ? setViewing(null) : p.back ? run(p.back) : setViewing(null)
                        }
                      >
                        {viewing ? p.words.backToNow : (p.back?.label ?? p.words.backToNow)}
                      </button>
                    )}
                  </span>
                </div>
                <div className="rc-prog__col">
                  {shown.confirmed.length > 0 && (
                    <>
                      <p className="rc-prog__eyebrow">{p.words.confirmed}</p>
                      <ul className="rc-prog__list rc-prog__list--good">
                        {shown.confirmed.slice(0, 3).map((t) => (
                          <li key={t}>{t}</li>
                        ))}
                      </ul>
                    </>
                  )}
                  <p className="rc-prog__eyebrow">{p.words.missing}</p>
                  {missing.length ? (
                    <ul className="rc-prog__list">
                      {missing.slice(0, 3).map((t) => (
                        <li key={t} data-carried={p.carried.includes(t) || undefined}>
                          {t}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="rc-prog__quiet">{p.words.nothingMissing}</p>
                  )}
                  {shown.reopened && <p className="rc-prog__reopened">{shown.reopened}</p>}
                </div>
                <div className="rc-prog__col rc-prog__col--next">
                  {after.length === 0 && (
                    <div className="rc-prog__ahead">
                      <p className="rc-prog__eyebrow">{p.words.ending.title}</p>
                      <ul className="rc-prog__list">
                        {p.words.ending.items.map((t) => (
                          <li key={t}>{t}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {after.map((l, i) => (
                    <div key={l.id} className="rc-prog__ahead">
                      <p className="rc-prog__eyebrow">{i === 0 ? p.words.next : p.words.after}</p>
                      <p className="rc-prog__ahead-name">
                        <span className="rc-prog__n">{num(l.n)}</span>
                        {l.label}
                      </p>
                      <p className="rc-prog__ahead-goal">{l.goal}</p>
                    </div>
                  ))}
                </div>
              </div>
              <AnimatePresence>
                {arrived?.distilled && (
                  <motion.div
                    key={arrived.id}
                    className="rc-prog__distil"
                    role="status"
                    initial={reduce ? { opacity: 0 } : { opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: reduce ? 0.16 : 0.28, ease: EASE_OUT }}
                  >
                    <svg
                      viewBox="0 0 16 16"
                      className="rc-prog__i rc-prog__distil-i"
                      aria-hidden="true"
                    >
                      <path d="m3.5 8.5 3 3 6-7" />
                    </svg>
                    <p>
                      <b>
                        {num(arrived.n)} {arrived.label} · {p.words.distilled}
                      </b>
                      {arrived.distilled.confirmed.join('；')}
                      {arrived.distilled.kept.length > 0 && (
                        <span className="rc-prog__kept">
                          {p.words.kept}
                          {arrived.distilled.kept.join('；')}
                        </span>
                      )}
                    </p>
                    <button
                      type="button"
                      className="btn quiet small"
                      onClick={() => p.onArrivedSeen(arrived.id)}
                    >
                      {p.words.gotIt}
                    </button>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          )}
        </AnimatePresence>
        {mapOpen && <WorkMap {...p} onClose={() => setMapOpen(false)} />}
      </section>
    </>
  );
}

/**
 * The open work map: six stops on a rising path. The path shows the usual order, not a lock;
 * every stop can be read at any time. Each stop carries the same confirmed / missing lines and
 * the distillation it left, so the map is also where earlier summaries are read again.
 */
function WorkMap(p: ProgressBandProps & { onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const reduce = useReducedMotion();
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    d.showModal();
    const close = () => p.onClose();
    // A press on the backdrop (the dialog element itself, outside its content) closes it.
    const outside = (e: MouseEvent) => {
      if (e.target === d) d.close();
    };
    d.addEventListener('close', close);
    d.addEventListener('click', outside);
    return () => {
      d.removeEventListener('close', close);
      d.removeEventListener('click', outside);
    };
  }, [p.onClose]);
  // The path runs through each stop's node, measured after layout: solid ink up to the current
  // stop, a dashed line ahead. It shows the usual order only; nothing on it is locked.
  const field = useRef<HTMLDivElement>(null);
  const [path, setPath] = useState<{ w: number; h: number; all: string; walked: string } | null>(
    null,
  );
  const at = Math.max(
    0,
    p.layers.findIndex((l) => l.id === p.current),
  );
  useLayoutEffect(() => {
    const host = field.current;
    if (!host) return;
    const draw = () => {
      const box = host.getBoundingClientRect();
      const pts = [...host.querySelectorAll<HTMLElement>('.rc-map__node')].map((n) => {
        const r = n.getBoundingClientRect();
        return [r.left + r.width / 2 - box.left, r.top + r.height / 2 - box.top] as const;
      });
      if (pts.length < 2 || pts[0][0] === pts[1][0]) return setPath(null);
      const seg = (list: (typeof pts)[number][]) =>
        list
          .map(([x, y], k) => {
            if (k === 0) return `M ${x} ${y}`;
            const [px, py] = list[k - 1];
            const mx = (px + x) / 2;
            return `C ${mx} ${py} ${mx} ${y} ${x} ${y}`;
          })
          .join(' ');
      setPath({ w: box.width, h: box.height, all: seg(pts), walked: seg(pts.slice(0, at + 1)) });
    };
    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(host);
    return () => ro.disconnect();
  }, [at]);
  return (
    <dialog
      ref={ref}
      className="rc-map rc-portal"
      aria-labelledby="rc-map-title"
    >
      <header className="rc-map__head">
        <div>
          <h2 id="rc-map-title">{p.words.mapTitle}</h2>
          <p>{p.words.mapLead}</p>
        </div>
        <button type="button" className="btn quiet small" onClick={() => ref.current?.close()}>
          {p.words.close}
        </button>
      </header>
      <div className="rc-map__field" ref={field}>
        {path && (
          <svg className="rc-map__path" width={path.w} height={path.h} aria-hidden="true">
            <path className="rc-map__path-ahead" d={path.all} />
            <motion.path
              className="rc-map__path-walked"
              d={path.walked}
              initial={reduce ? false : { pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: 0.52, ease: EASE_OUT }}
            />
          </svg>
        )}
        <ol className="rc-map__stops">
          {p.layers.map((l, i) => (
            <motion.li
              key={l.id}
              className="rc-map__stop"
              data-state={l.state}
              style={{ ['--rise' as string]: `${(p.layers.length - 1 - i) * 16}px` }}
              initial={reduce ? false : { opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.28, delay: reduce ? 0 : 0.04 * i, ease: EASE_OUT }}
            >
              <span className="rc-map__node" aria-hidden="true" />
              <p className="rc-map__state">
                <span className="rc-prog__n">{num(l.n)}</span>
                {p.words.states[l.state]}
              </p>
              <h3>{l.label}</h3>
              <p className="rc-map__goal">{l.goal}</p>
              {l.confirmed.length > 0 && (
                <ul className="rc-prog__list rc-prog__list--good">
                  {l.confirmed.map((t) => (
                    <li key={t}>{t}</li>
                  ))}
                </ul>
              )}
              {l.missing.length > 0 && (
                <ul className="rc-prog__list">
                  {l.missing.map((t) => (
                    <li key={t}>{t}</li>
                  ))}
                </ul>
              )}
              {l.reopened && <p className="rc-prog__reopened">{l.reopened}</p>}
              {/* The summary's confirmed half is the list above; what it kept open is added here. */}
              {l.distilled && l.distilled.kept.length > 0 && (
                <p className="rc-map__distil">
                  <b>{p.words.kept}</b>
                  {l.distilled.kept.join('；')}
                </p>
              )}
            </motion.li>
          ))}
        </ol>
      </div>
      <p className="rc-map__foot">{p.words.basisHint}</p>
    </dialog>
  );
}
