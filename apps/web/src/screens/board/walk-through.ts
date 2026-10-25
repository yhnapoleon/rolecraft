// The first minute of a practice (story board P02, direction A). Grace's note arrives in "Needs
// you"; taking it on lands it on the policy item on the board (the card says "Grace handed you
// this"), and a three-step walk-through points at the test bench, the full brief and the
// colleagues. Every step can be skipped; "⋯ → Walk me through again" replays it. A practice that
// already has records, or one this browser has walked before, gets none of it: a returning person
// just carries on. Kept per practice in this browser; taking it on is a local mark, and the
// progress ruler counts it only as "took on the brief" (shell/progress.ts).
import { avatar } from '../../app/art.js';
import { T } from '../../app/i18n';
import { type Attempt, registerActions, registerSignals, type Signal } from '../../shell';
import './walk-through.css';

const KEY = 'rolecraft.walkthrough.v1';
type Walk = { taken?: string; tour?: 'done' | 'skipped'; at?: string };

function all(): Record<string, Walk> {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || '{}');
    return v && typeof v === 'object' ? v : {};
  } catch {
    return {};
  }
}
function save(id: string, patch: Walk) {
  const v = all();
  v[id] = { ...v[id], ...patch };
  try {
    localStorage.setItem(KEY, JSON.stringify(v));
  } catch {
    /* this page only */
  }
}
/** The practice's brief was taken on in the walk-in (this browser). */
export const walkInAccepted = (id: string) => !!all()[id]?.taken;
/** The task Grace's brief landed on, for its card. */
export const handedTask = (id: string) => all()[id]?.taken ?? null;

export type WalkHost = {
  current(): Attempt | null;
  /** A product manager's native practice with no records yet: the walk-in applies. */
  fresh(a: Attempt): boolean;
  /** The seeded policy item, where the first try lands. */
  policyTask(a: Attempt): string | null;
  refresh(parts: string[]): void;
  /** Grace's line in the practice's work language. */
  text(zh: string, en: string, a: Attempt): string;
};
let host: WalkHost | null = null;
export function installWalkThrough(h: WalkHost) {
  host = h;
}

const NOTE_ID = 'walk:grace';
registerSignals((a): Signal[] => {
  if (!host || !a || all()[a.id] || !host.fresh(a)) return [];
  return [
    {
      id: NOTE_ID,
      source: 'person',
      person: 'manager',
      text: host.text(
        '你来判断这个助手能不能试点、怎样试点。先在测试台问一次政策问题，看看它凭什么回答——这件事落在「回应政策问答的开放请求」上。',
        'You decide whether, and how, this assistant goes to pilot. Start by asking it one policy question on the test bench and see what it bases the answer on. That is the “Respond to the policy Q&A request” item.',
        a,
      ),
      action: { label: T('接手', 'Take it on'), action: 'walk-accept' },
      at: '9999',
    },
  ];
});

const reduced = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
const EASE = 'cubic-bezier(0.23, 1, 0.32, 1)';
const frame = () => new Promise<void>((r) => requestAnimationFrame(() => r()));
const cardOf = (taskId: string) =>
  document.querySelector<HTMLElement>(`.kanban .card-open[data-id="${CSS.escape(taskId)}"]`);

/**
 * The note flies from the rail to its card: a still copy of it shrinks into the card's box and
 * fades as the card takes a ring (520ms; the one move here that travels, because it says where
 * the brief went). Reduced motion: no flight, the ring fades in and out.
 */
async function land(copy: HTMLElement | null, from: DOMRect | null, taskId: string) {
  const card = cardOf(taskId);
  if (!card) return;
  card.scrollIntoView({ block: 'center' });
  await frame();
  const to = card.getBoundingClientRect();
  if (copy && from && !reduced()) {
    const ghost = copy;
    ghost.removeAttribute('data-signal-id');
    for (const n of ghost.querySelectorAll('button')) n.remove();
    Object.assign(ghost.style, {
      position: 'fixed',
      left: `${from.left}px`,
      top: `${from.top}px`,
      width: `${from.width}px`,
      margin: '0',
      zIndex: '60',
      pointerEvents: 'none',
      transformOrigin: 'top left',
    });
    document.body.appendChild(ghost);
    const sx = to.width / from.width;
    const sy = Math.min(sx, to.height / Math.max(1, ghost.offsetHeight));
    await ghost
      .animate(
        [
          { transform: 'none', opacity: 1 },
          {
            transform: `translate(${to.left - from.left}px, ${to.top - from.top}px) scale(${sx}, ${sy})`,
            opacity: 0.15,
          },
        ],
        { duration: 520, easing: EASE, fill: 'forwards' },
      )
      .finished.catch(() => {});
    ghost.remove();
  }
  const ring = cardOf(taskId);
  ring?.animate(
    [
      { boxShadow: '0 0 0 0 var(--p-manager)' },
      { boxShadow: '0 0 0 3px var(--p-manager)', offset: 0.3 },
      { boxShadow: '0 0 0 0 transparent' },
    ],
    { duration: reduced() ? 900 : 1100, easing: 'ease-out' },
  );
}

/* ---------- the three-step walk-through ---------- */

type Step = { target: () => HTMLElement | null; title: string; body: string };
const visible = (el: HTMLElement | null) =>
  el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden' ? el : null;
const steps = (): Step[] => [
  {
    target: () => visible(document.querySelector('[data-action="open-bench"]')),
    title: T('先试一下助手', 'Try the assistant first'),
    body: T(
      '在测试台问一个政策问题，比如住宿报销上限。看它答了什么、引用的是哪一版资料。每次测试都会留下记录。',
      'On the test bench, ask it a policy question, such as the hotel reimbursement cap. See what it answers and which version it cites. Every test is kept on record.',
    ),
  },
  {
    target: () =>
      visible(document.querySelector('.brief-line-read')) ||
      visible(document.querySelector('.ws-title .title-btn')),
    title: T('需要时再看完整委托', 'Read the full brief when you need it'),
    body: T(
      '期限、容量和 Grace 要你交回什么都写在里面。不用一开始读完所有资料，用到哪份再翻哪份。',
      'Deadline, capacity and what Grace wants back are all in it. No need to read every document up front; open each one when you need it.',
    ),
  },
  {
    target: () =>
      visible(document.querySelector('#ws-rail .people')) ||
      visible(document.querySelector('.team-btn')),
    title: T('卡住了就问同事', 'Ask a colleague when you are stuck'),
    body: T(
      'Chen 管首批用户和业务流程，Daniel 管系统限制和测试证据，Grace 管目标和资源。他们只看得到你分享的东西。',
      'Chen knows the first users and the workflow, Daniel the system limits and test evidence, Grace the goals and resources. They see only what you share.',
    ),
  },
];

let open: { close(how: 'done' | 'skipped'): void } | null = null;

/** Opens the walk-through at step 1 (replay included). */
export function startTour(id: string) {
  open?.close('skipped');
  const list = steps();
  let i = 0;
  const ring = document.createElement('div');
  ring.className = 'rc-tour-ring';
  ring.setAttribute('aria-hidden', 'true');
  const card = document.createElement('div');
  card.className = 'rc-tour';
  card.setAttribute('role', 'dialog');
  card.setAttribute('aria-modal', 'false');
  card.setAttribute('aria-labelledby', 'rc-tour-title');
  document.body.append(ring, card);
  const before = document.activeElement as HTMLElement | null;
  let target: HTMLElement | null = null;

  const place = () => {
    if (!target?.isConnected) target = list[i].target();
    if (!target) {
      ring.hidden = true;
      card.style.left = `${Math.max(16, innerWidth / 2 - 170)}px`;
      card.style.top = `${innerHeight / 2 - 90}px`;
      card.dataset.side = 'none';
      return;
    }
    ring.hidden = false;
    const r = target.getBoundingClientRect();
    Object.assign(ring.style, {
      left: `${r.left - 6}px`,
      top: `${r.top - 6}px`,
      width: `${r.width + 12}px`,
      height: `${r.height + 12}px`,
    });
    const w = card.offsetWidth;
    const h = card.offsetHeight;
    const below = r.bottom + 14 + h < innerHeight - 8;
    const left = Math.min(Math.max(16, r.left + r.width / 2 - w / 2), innerWidth - w - 16);
    card.style.left = `${left}px`;
    card.style.top = `${below ? r.bottom + 14 : Math.max(8, r.top - 14 - h)}px`;
    card.dataset.side = below ? 'below' : 'above';
    card.style.setProperty('--arrow', `${Math.min(Math.max(18, r.left + r.width / 2 - left), w - 18)}px`);
  };
  const draw = () => {
    const s = list[i];
    target = s.target();
    target?.scrollIntoView({ block: 'center', behavior: 'auto' });
    const last = i === list.length - 1;
    card.innerHTML = `<p class="rc-tour__count">${avatar('manager', 'xs')}<span>${T(`第 ${i + 1} 步，共 ${list.length} 步`, `Step ${i + 1} of ${list.length}`)}</span></p>
      <h2 class="rc-tour__title" id="rc-tour-title">${s.title}</h2>
      <p class="rc-tour__body">${s.body}</p>
      <div class="rc-tour__keys">
        <button type="button" class="btn quiet small" data-tour="skip">${T('跳过引导', 'Skip')}</button>
        <span class="spacer"></span>
        ${i > 0 ? `<button type="button" class="btn small" data-tour="back">${T('上一步', 'Back')}</button>` : ''}
        <button type="button" class="btn primary small" data-tour="next">${last ? T('开始工作', 'Start working') : T('下一步', 'Next')}</button>
      </div>`;
    requestAnimationFrame(() => {
      place();
      if (!reduced()) {
        card.animate([{ opacity: 0, transform: 'translateY(4px)' }, { opacity: 1, transform: 'none' }], {
          duration: 160,
          easing: EASE,
        });
      }
      card.querySelector<HTMLElement>('[data-tour="next"]')?.focus({ preventScroll: true });
    });
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape') close('skipped');
  };
  const onMove = () => requestAnimationFrame(place);
  const close = (how: 'done' | 'skipped') => {
    save(id, { tour: how });
    ring.remove();
    card.remove();
    document.removeEventListener('keydown', onKey, true);
    removeEventListener('resize', onMove);
    document.removeEventListener('scroll', onMove, true);
    open = null;
    if (before?.isConnected) before.focus({ preventScroll: true });
  };
  card.addEventListener('click', (e) => {
    const k = (e.target as HTMLElement).closest<HTMLElement>('[data-tour]')?.dataset.tour;
    if (k === 'skip') close('skipped');
    else if (k === 'back' && i > 0) {
      i -= 1;
      draw();
    } else if (k === 'next') {
      if (i === list.length - 1) close('done');
      else {
        i += 1;
        draw();
      }
    }
  });
  document.addEventListener('keydown', onKey, true);
  addEventListener('resize', onMove);
  document.addEventListener('scroll', onMove, true);
  open = { close };
  draw();
}

registerActions({
  // Take the brief on: it lands on the policy item, then the walk-through starts.
  'walk-accept': async (el) => {
    const a = host?.current();
    if (!a || !host) return;
    const note = (el.closest?.('[data-signal-id]') as HTMLElement | null) ?? null;
    const task = host.policyTask(a);
    save(a.id, { taken: task ?? 'brief', at: new Date().toISOString() });
    // The note's copy and place are taken before the rail redraws without it.
    const copy = (note?.cloneNode(true) as HTMLElement | undefined) ?? null;
    const from = note?.getBoundingClientRect() ?? null;
    host.refresh(['rail', 'stage']);
    await frame();
    if (task) await land(copy, from, task);
    startTour(a.id);
  },
  'walk-tour': () => {
    const a = host?.current();
    if (a) startTour(a.id);
  },
});
