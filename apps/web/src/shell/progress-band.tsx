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
  // Scroll targets account for the actual dock height, including narrow/translated layouts.
  useLayoutEffect(() => {
    const root = self.current?.closest<HTMLElement>('#main');
    const bar = root?.querySelector<HTMLElement>('.rc-prog-dock__bar');
    if (!root || !bar) return;
    const resize = () => root.style.setProperty('--progress-dock-height', docked ? `${bar.getBoundingClientRect().height + 20}px` : '0px');
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(bar);
    return () => { observer.disconnect(); root.style.removeProperty('--progress-dock-height'); };
  }, [docked]);
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
  const current = p.layers[at];
  const shown = p.layers.find((l) => l.id === looking) ?? current;
  const openViewed = p.actions?.[shown.id];
  const isNow = shown.id === current.id;
  const after = p.layers.slice(at + 1, at + 3);
  const arrived = p.arrived ? p.layers.find((l) => l.id === p.arrived) : undefined;
  const missing = [...new Set([...current.missing, ...p.carried])];
  const confirmed = current.confirmed.length
    ? current.confirmed
    : p.layers
        .slice(0, at)
        .flatMap((l) => l.confirmed)
        .slice(-1);
  const summary = (dock = false) => (
    <div className="rc-prog__summary" data-progress-current={current.id}>
      <div className="rc-prog__focus">
        <p className="rc-prog__eyebrow">
          {p.words.now} · {current.n} / {p.layers.length}
        </p>
        <h2 className="rc-prog__title">
          <span className="rc-prog__n">{num(current.n)}</span>
          {current.label}
        </h2>
        <p className="rc-prog__goal">{current.goal}</p>
      </div>
      <dl className="rc-prog__facts">
        <div>
          <dt>{p.words.confirmed}</dt>
          <dd>
            {confirmed.length
              ? confirmed.join(p.lang === 'en' ? '; ' : '；')
              : p.lang === 'en'
                ? 'No conclusion recorded yet'
                : '尚无已记录的结论'}
          </dd>
        </div>
        <div>
          <dt>{p.words.missing}</dt>
          <dd>
            {missing.length ? missing.join(p.lang === 'en' ? '; ' : '；') : p.words.nothingMissing}
          </dd>
        </div>
      </dl>
      <div className="rc-prog__future">
        {after.map((l, i) => (
          <p key={l.id}>
            <span>{i ? p.words.after : p.words.next}</span>
            <b>
              {num(l.n)} {l.label}
            </b>
          </p>
        ))}
        {!after.length && (
          <p>
            <span>{p.words.ending.title}</span>
            <b>{p.words.ending.items.join(p.lang === 'en' ? '; ' : '；')}</b>
          </p>
        )}
      </div>
      {!isNow && (
        <p className="rc-prog__viewing">
          {p.words.viewing} · {num(shown.n)} {shown.label}
          <button
            type="button"
            className="btn quiet small"
            onClick={() => (viewing ? setViewing(null) : p.back && run(p.back))}
          >
            {p.words.backToNow}
          </button>
        </p>
      )}
      {dock && (
        <button
          type="button"
          className="btn quiet small rc-prog__summary-link"
          onClick={() => setMapOpen(true)}
        >
          {p.words.map} · {p.words.distilled}
        </button>
      )}
    </div>
  );
  return (
    <>
      <div
        className="rc-prog-dock"
        data-on={docked || undefined}
        aria-hidden={!docked || undefined}
      >
        <div className="rc-prog-dock__bar" inert={!docked || undefined}>
          {summary(true)}
        </div>
      </div>
      <section
        ref={self}
        className="rc-prog"
        aria-label={p.words.label}
        data-folded={p.folded || undefined}
        data-viewing={!isNow || undefined}
      >
        {summary()}
        <div className="rc-prog__tools">
          <span className="rc-prog__basis" title={p.words.basisHint}>
            {p.words.basis}
          </span>
          <button type="button" className="btn quiet small" onClick={() => setMapOpen(true)}>
            {p.words.map} · {p.words.distilled}
          </button>
          <button
            type="button"
            className="btn quiet small rc-prog__fold"
            aria-expanded={!p.folded}
            onClick={() => p.onFold(!p.folded)}
          >
            {p.folded ? p.words.unfold : p.words.fold}
          </button>
        </div>
        {!p.folded && (
          <div className="rc-prog__detail">
            <LayoutGroup id={gid}>
              <ol className="rc-prog__track">
                {p.layers.map((l) => (
                  <li key={l.id} className="rc-prog__stop" data-state={l.state}>
                    <button
                      type="button"
                      className="rc-prog__key"
                      aria-current={l.id === p.current ? 'step' : undefined}
                      aria-pressed={looking === l.id}
                      aria-label={`${p.words.stepOf(l.n, p.layers.length, l.label)} · ${p.words.states[l.state]}`}
                      onClick={() => setViewing(l.id === p.current ? null : l.id)}
                    >
                      <span className="rc-prog__dot">
                        <span className="rc-prog__glyph">{num(l.n)}</span>
                      </span>
                      <span className="rc-prog__name">{l.label}</span>
                      {l.id === looking && <span className="rc-prog__look" />}
                    </button>
                  </li>
                ))}
              </ol>
            </LayoutGroup>
            {!isNow && (
              <div className="rc-prog__reading">
                <b>
                  {p.words.viewing} · {num(shown.n)} {shown.label}
                </b>
                <p>{shown.goal}</p>
                <p>
                  {p.words.confirmed} · {shown.confirmed.join(p.lang === 'en' ? '; ' : '；') || '—'}
                </p>
                <p>
                  {p.words.missing} ·{' '}
                  {shown.missing.join(p.lang === 'en' ? '; ' : '；') || p.words.nothingMissing}
                </p>
                {openViewed && (
                  <button type="button" className="btn small" onClick={() => run(openViewed)}>
                    {openViewed.label}
                  </button>
                )}
              </div>
            )}
          </div>
        )}
        <AnimatePresence>
          {arrived?.distilled && (
            <motion.div
              className="rc-prog__distil"
              role="status"
              initial={reduce ? false : { opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              <p>
                <b>
                  {num(arrived.n)} {arrived.label} · {p.words.distilled}
                </b>
                {arrived.distilled.confirmed.join(p.lang === 'en' ? '; ' : '；')}
                {arrived.distilled.kept.length > 0 && (
                  <span className="rc-prog__kept">
                    {p.words.kept}
                    {arrived.distilled.kept.join(p.lang === 'en' ? '; ' : '；')}
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
    <dialog ref={ref} className="rc-map rc-portal" aria-labelledby="rc-map-title">
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
