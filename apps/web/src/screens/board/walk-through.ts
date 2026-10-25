// One entry story: Grace’s brief, four real-interface stops, then the current item.
import { avatar } from '../../app/art.js';
import { T } from '../../app/i18n';
import { type Attempt, registerActions } from '../../shell';
import './walk-through.css';

const KEY = 'rolecraft.walkthrough.v1';
let fallback: Record<string, Walk> = {};
type Walk = { taken?: string; tour?: 'done' | 'skipped'; at?: string };

function all(): Record<string, Walk> {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || '{}');
    return v && typeof v === 'object' ? { ...fallback, ...v } : fallback;
  } catch {
    return fallback;
  }
}
function save(id: string, patch: Walk) {
  const v = all();
  v[id] = { ...v[id], ...patch };
  fallback = v;
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
  job(a: Attempt): 'pm' | 'engineer';
  prepareTour(): void;
  finish(id: string): void;
  openTicket?(): Promise<void>;
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

export const entryPending = (a: Attempt) =>
  !!host && host.fresh(a) && !all()[a.id]?.taken && !all()[a.id]?.tour;
export function entryStory(a: Attempt) {
  if (!entryPending(a) || !host) return '';
  const engineer = host.job(a) === 'engineer';
  return `<section class="rc-entry-story" aria-labelledby="entry-title">
    <p class="rc-entry-from">${avatar('manager', 'md')}<span>Grace · ${T('经理', 'Manager')}</span></p>
    <p class="rc-entry-role">${engineer ? T('你的岗位 · AI 应用工程师', 'Your role · AI Application Engineer') : T('你的岗位 · AI 产品经理', 'Your role · AI Product Manager')}</p>
    <h1 id="entry-title">${engineer ? T('把这个问题修好，再告诉我能否采用。', 'Fix this issue, then tell me whether we can adopt the change.') : T('这个知识助手，可以开始试点了吗？', 'Is this knowledge assistant ready for a pilot?')}</h1>
    <p class="rc-entry-body">${engineer ? T('由你复现问题、验证改动，最后交回亲自签字的修复报告。现在先看委托里的失败，再复现一次。', 'Reproduce the issue, verify your change and hand back a repair report you have signed. Start with the failure in the ticket and reproduce it.') : T('由你决定先服务谁、开放什么、需要哪些保障，并交回有依据的试点决定。现在先试一个员工会问的问题。', 'Decide whom to serve, what to offer and which safeguards are needed, then hand back a pilot recommendation with evidence. Start with a question an employee would ask.')}</p>
    <details class="rc-entry-brief"><summary>${T('看完整委托', 'Read the full brief')}</summary><p>${engineer ? T('核对原问题和当时回答，只改允许的设置；用公开测试检查改动，再说明可能受影响的问题。签字后会进行复核，报告交回 Grace。', 'Check the original question and answer, change only supported settings, test the change and explain what else it may affect. Signing starts the review; hand the report back to Grace.') : T('结合委托里的资源、期限与业务资料，调查知识助手是否适合试点；你可以自由安排事项、向同事求助、测试和修订，最终说明推进范围、保障与暂停条件。', 'Use the resources, timing and business material in the brief to investigate a pilot. Organise the work, ask colleagues, test and revise freely, then explain the scope, safeguards and stopping conditions.')}</p><button type="button" class="btn quiet small" data-action="${engineer ? 'walk-ticket' : 'open-doc'}" data-id="brief">${T('打开委托原文', 'Open the original brief')}</button></details>
    <button type="button" class="btn primary" data-action="walk-accept">${T('开始', 'Start')}</button>
  </section>`;
}

const reduced = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
const EASE = 'cubic-bezier(0.23, 1, 0.32, 1)';
const frame = () => new Promise<void>((r) => requestAnimationFrame(() => r()));
type Step = { target: () => HTMLElement | null; title: string; body: string };
const visible = (el: HTMLElement | null) =>
  el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden' ? el : null;
const currentItem = () => {
  const a = host?.current();
  if (a && host?.job(a) === 'engineer')
    return document.querySelector<HTMLElement>('[data-step="reproduce"]');
  const id = a && host?.policyTask(a);
  return (
    (id
      ? document.querySelector<HTMLElement>(`.kanban .card-open[data-id="${CSS.escape(id)}"]`)
      : null) || document.querySelector<HTMLElement>('.kanban .card-open')
  );
};
const steps = (): Step[] => {
  const a = host?.current();
  const engineer = !!a && host?.job(a) === 'engineer';
  const find = (selector: string) => visible(document.querySelector(selector));
  return [
    {
      target: () => find(engineer ? '.rc-scale' : '.rc-prog'),
      title: T('当前在哪一层', 'Where you are'),
      body: T(
        '问题航段尺告诉你当前的问题、已有依据和还没解决的事。',
        'The progress ruler shows the current question, the evidence you have and what remains unresolved.',
      ),
    },
    {
      target: () => visible(currentItem()),
      title: T('当前事项', 'Your current work'),
      body: engineer
        ? T(
            '先复现委托里的问题，再改设置、试跑，最后签字。',
            'Reproduce the issue in the ticket, change settings and test, then sign your report.',
          )
        : T(
            '从这件事开始，之后可以自己调整事项和先后顺序。',
            'Start with this item; you can arrange the work and its priorities as you go.',
          ),
    },
    {
      target: () => find('#ws-rail .people') || find('.team-btn'),
      title: T('同事在这里', 'Your colleagues are here'),
      body: T(
        '红点表示有未读消息；点开一位同事看介绍、直接提问，或自由继续聊。',
        'A red dot means unread messages; open a colleague to read their introduction, choose a question or chat freely.',
      ),
    },
    {
      target: () => find(engineer ? '[data-step="reproduce"]' : '[data-action="open-bench"]'),
      title: T('用测试和资料拿证据', 'Find evidence in tests and documents'),
      body: engineer
        ? T(
            '复现和试跑会保留记录；对照委托里的原问题和资料，检查修复是否有效。',
            'Reproduction and trials keep a record; compare them with the ticket and source material to check your repair.',
          )
        : T(
            '在测试台问一个员工的问题，再打开回答引用的资料，核对原文和版本。',
            'Ask an employee’s question on the test bench, then open the cited document to check its wording and version.',
          ),
    },
  ];
};

let open: { close(how: 'done' | 'skipped'): void } | null = null;

/** Opens the walk-through at step 1 (replay included). */
export function startTour(id: string) {
  open?.close('skipped');
  host?.prepareTour();
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
    card.style.setProperty(
      '--arrow',
      `${Math.min(Math.max(18, r.left + r.width / 2 - left), w - 18)}px`,
    );
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
        card.animate(
          [
            { opacity: 0, transform: 'translateY(4px)' },
            { opacity: 1, transform: 'none' },
          ],
          {
            duration: 160,
            easing: EASE,
          },
        );
      }
      card.querySelector<HTMLElement>('[data-tour="next"]')?.focus({ preventScroll: true });
    });
  };
  const onRoute = () => close('skipped');
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape') close('skipped');
  };
  const onMove = () => requestAnimationFrame(place);
  const surfaces = new MutationObserver(() => {
    if (!target?.isConnected) onMove();
  });
  surfaces.observe(document.getElementById('app') || document.body, {
    childList: true,
    subtree: true,
  });
  const close = (how: 'done' | 'skipped') => {
    save(id, { tour: how });
    surfaces.disconnect();
    ring.remove();
    card.remove();
    document.removeEventListener('keydown', onKey, true);
    removeEventListener('resize', onMove);
    document.removeEventListener('scroll', onMove, true);
    removeEventListener('hashchange', onRoute);
    open = null;
    if (host?.current()?.id === id) host.finish(id);
    const landing = currentItem();
    if (landing) {
      landing.scrollIntoView({ block: 'center' });
      landing.setAttribute('tabindex', '-1');
      landing.focus({ preventScroll: true });
    } else if (before?.isConnected) before.focus({ preventScroll: true });
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
  addEventListener('hashchange', onRoute);
  document.addEventListener('keydown', onKey, true);
  addEventListener('resize', onMove);
  document.addEventListener('scroll', onMove, true);
  open = { close };
  draw();
}

registerActions({
  'walk-accept': async () => {
    const a = host?.current();
    if (!a || !host) return;
    save(a.id, {
      taken: host.policyTask(a) ?? 'brief',
      at: new Date().toISOString(),
    });
    host.refresh(['toolbar', 'rail', 'stage']);
    await frame();
    startTour(a.id);
  },
  'walk-ticket': async () => {
    await host?.openTicket?.();
  },
  'walk-tour': async () => {
    const a = host?.current();
    if (!a || !host) return;
    save(a.id, { taken: all()[a.id]?.taken ?? 'brief' });
    host.prepareTour();
    await frame();
    startTour(a.id);
  },
});
