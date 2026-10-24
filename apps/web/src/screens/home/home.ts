/** The way in: the home page (the manager's first sentence, the desk you will work on, two rows
 * of jobs) and the job page (one brief on paper). Pure HTML builders; ui.js supplies the data and
 * keeps the actions. Shapes follow D「仪器与纸」(197-visual-d.md); decisions 5–7 of 199. */
import './home.css';
import { agentMark, avatar, icon, PEOPLE } from '../../app/art.js';
import { locale, T } from '../../app/i18n';
import { PRI } from '../../app/vocab.js';

export { fadeIn, walkIn } from './walk-in';

const esc = (v: unknown) =>
  String(v ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string,
  );
const key = (label: string, action: string, cls = '', attrs = '') =>
  `<button type="button" class="btn ${cls}" data-action="${action}" ${attrs}>${label}</button>`;
/** A key's spoken name with the job it belongs to: two "Start" keys on one page are not the same. */
const named = (label: string, job: string) => `aria-label="${esc(`${label}: ${job}`)}"`;
const JOB_PM = () => T('AI 产品经理', 'AI Product Manager');
const JOB_ENG = () => T('AI 应用工程师', 'AI Application Engineer');
const TWO_HATS = () =>
  T(
    '一局练习，两顶帽子。产品经理和工程师在同一局里，进去后用顶栏切换，进度都在。',
    'One practice, two hats. Product manager and engineer share it; switch from the top bar and nothing is lost.',
  );
const reduced = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

/** The first sentence of a brief: what the home page sets in large type. */
export function firstSentence(text: string): string {
  const m = String(text || '').match(/^.+?[.。!?！？](?=\s|$|[^.。])/u);
  return (m ? m[0] : String(text || '')).trim();
}

/* ---------- home ---------- */

export type Hat = 'pm' | 'engineer';
/** One practice under way, as the continue slip shows it. */
export type ContinueInfo = {
  id: string;
  title: string;
  hat: Hat;
  /** The current stage of the hat on, in words: Investigating, Deciding, Delivered… */
  stage: string;
  submitted: boolean;
  /** Present when this practice has had the engineer's hat on at least once. */
  engineer: { stage: string } | null;
  /** The practice's own language; inside it the interface speaks it. */
  lang?: 'zh' | 'en' | null;
};

const HAT = (h: Hat) =>
  h === 'engineer' ? T('工程师', 'Engineer') : T('产品经理', 'Product manager');

function continueSlip(c: ContinueInfo): string {
  const pmLine = `<span class="hm-cont__pair"><span class="hm-cont__hat">${HAT('pm')}</span><span class="hm-cont__stage">${esc(c.stage)}</span></span>`;
  const main =
    c.hat === 'engineer'
      ? key(
          T('以工程师继续', 'Continue as engineer'),
          'engineer-take',
          'primary',
          `data-id="${esc(c.id)}"`,
        )
      : c.submitted
        ? key(T('看结果', 'See the result'), 'review-attempt', 'primary', `data-id="${esc(c.id)}"`)
        : key(T('继续', 'Continue'), 'resume', 'primary', `data-id="${esc(c.id)}"`);
  const eng = c.engineer
    ? `<span class="hm-cont__pair"><span class="hm-cont__hat hm-cont__hat--eng">${HAT('engineer')}</span><span class="hm-cont__stage hm-cont__stage--eng">${esc(c.engineer.stage)}</span></span>`
    : '';
  return `<section class="hm-cont paper" aria-labelledby="hm-cont-title" data-hat="${c.hat}">
    <span class="hm-cont__glyph" aria-hidden="true"><i></i></span>
    <div class="hm-cont__body">
      <p class="hm-cont__line"><span class="hm-cont__kicker">${T('接着做', 'Continue')}</span><span class="hm-cont__title" id="hm-cont-title">${esc(c.title)}</span></p>
      <p class="hm-cont__row">${pmLine}${eng ? `<span class="hm-cont__sep" aria-hidden="true"></span>${eng}` : ''}${c.lang && c.lang !== locale() ? `<span class="hm-cont__lang">${c.lang === 'zh' ? T('', 'This practice is in Chinese') : T('这一局用英文', '')}</span>` : ''}</p>
    </div>
    <div class="hm-cont__go">${main}</div>
    <p class="hm-cont__note">${TWO_HATS()}</p>
  </section>`;
}

/** The desk, as a still life: the brief on paper, one readout, two task slips, the team. */
function tableau(o: { memo: string; capacity: number; seeds: string[] }): string {
  return `<div class="hm-desk" aria-hidden="true">
    <div class="hm-desk__memo paper" style="--i:0"><p>${esc(o.memo)}</p><small>${T('经理的委托 · 第 1 版', 'Manager brief, v1')}</small></div>
    <div class="hm-desk__read" style="--i:1"><small>${T('试点容量', 'Capacity')}</small><b class="num">${o.capacity}</b><span>${T('人', 'seats')}</span></div>
    ${o.seeds
      .slice(0, 2)
      .map(
        (s, i) =>
          `<div class="hm-desk__slip paper hm-desk__slip--${i}" style="--i:${i + 2}">${icon(i ? 'circle' : 'half', 'i-sm')}<span>${esc(s)}</span></div>`,
      )
      .join('')}
    <div class="hm-desk__team" style="--i:4">${['manager', 'business', 'technical'].map((r) => avatar(r, 'sm')).join('')}${agentMark('sm')}</div>
  </div>`;
}

/** The engineer row's keys are 201's markup; give each a spoken name with its job here. */
function nameEngineerKeys(html: string): string {
  return html.replace(
    /<button([^>]*?)data-action="(engineer-start|engineer-take)"([^>]*)>([^<]*)<\/button>/g,
    (all, a, action, b, label) =>
      /aria-label=/.test(a + b)
        ? all
        : `<button${a}data-action="${action}"${b} ${named(label.trim(), JOB_ENG())}>${label}</button>`,
  );
}

let settled = false;
/** The desk settles once per page load; later visits to home draw it at rest. */
function settleOnce(): boolean {
  if (settled) return false;
  settled = true;
  return true;
}

export function homeHtml(o: {
  topbar: string;
  quote: string;
  capacity: number;
  seeds: string[];
  resume: ContinueInfo | null;
  /** The engineer's row: its content belongs to the engineer line (201). */
  engineerRow: string;
  continueCode: string;
}): string {
  // In Chinese the closing quote follows the sentence directly; a full stop before it leaves a gap.
  const first = firstSentence(o.quote).replace(/。$/u, '');
  const rest = o.quote.slice(firstSentence(o.quote).length).trim();
  const memo = firstSentence(rest) || rest;
  const g = PEOPLE.manager;
  return `${o.topbar}
    <main id="main" class="page hm" tabindex="-1"${settleOnce() ? ' data-settle' : ''}>
      ${o.resume ? continueSlip(o.resume) : ''}
      <div class="hm-hero">
        <div class="hm-hero__words">
          <p class="hm-hero__pre">${T('练一份真实的工作', 'Practise real work')}</p>
          <h1 class="hm-hero__quote"><span class="hm-q" aria-hidden="true">“</span>${esc(first)}<span aria-hidden="true">”</span></h1>
          <p class="hm-hero__by">${avatar('manager', 'sm')}<span>${esc(T(`${g.name}，你的经理，第 1 天`, `${g.name}, your manager, on day 1`))}</span></p>
          <p class="hm-hero__lede">${T('接手一件真实的工作。可以犯错，可以求助，也可以重来。', 'Take on a real piece of work. Get it wrong, ask for help, try again.')}</p>
        </div>
        ${tableau({ memo, capacity: o.capacity, seeds: o.seeds })}
      </div>
      <section class="hm-jobs" aria-label="${esc(T('岗位', 'Jobs'))}">
        <article class="hm-job hm-job--pm">
          <h2 class="hm-job__name">${JOB_PM()}</h2>
          <p class="hm-job__what">${T('判断一个 AI 功能该不该上线、先给谁用、怎样保障，并为这个决定负责。', 'Decide whether an AI feature should launch, who gets it first and how it stays safe, then own the call.')}</p>
          <p class="hm-job__meta">${T('3 个情境，每次 20–30 分钟。没有倒计时，随时可停。', '3 situations, 20–30 min each. No countdown, pause any time.')}</p>
          <div class="hm-job__go">${(() => {
            const label = o.resume ? T('看看所有情境', 'See all situations') : T('开始', 'Start');
            return key(label, 'open-career', o.resume ? '' : 'primary', named(label, JOB_PM()));
          })()}</div>
        </article>
        <div class="hm-job hm-job--eng" data-job-slot="engineer">${nameEngineerKeys(o.engineerRow)}</div>
      </section>
      <div class="hm-foot">${o.resume ? '' : `<p class="hm-hats">${TWO_HATS()}</p>`}${o.continueCode}</div>
    </main>`;
}

/* ---------- the job page: one brief on paper ---------- */

export type Readout = {
  label: string;
  value: string | number;
  pre?: string;
  unit?: string;
  was?: string;
};
export type Variant = {
  id: string;
  /** What changed, short: "Launch on day 5". */
  label: string;
  value: string | number;
  was: string;
  openId: string | null;
};

/* The starting order of the three tasks, chosen on the brief. Kept here so a redraw of the page
   (language, a refresh while the practice opens) keeps it. */
const PRIS = ['first', 'next', 'later'] as const;
let order: string[] = ['next', 'next', 'next'];
export const seedOrder = () => order.slice();
export const resetSeedOrder = () => {
  order = ['next', 'next', 'next'];
};
function seedPicker(i: number, text: string): string {
  const p = order[i] || 'next';
  return `<label class="hm-pri" data-pri="${p}"><span class="hm-pri__val">${esc(PRI(p))}</span>${icon('down', 'i-xs')}<select data-change="triage" data-i="${i}" aria-label="${esc(T(`「${text}」的优先级`, `Priority for “${text}”`))}">${PRIS.map((k) => `<option value="${k}" ${k === p ? 'selected' : ''}>${esc(PRI(k))}</option>`).join('')}</select></label>`;
}
if (typeof document !== 'undefined') {
  document.addEventListener('change', (e) => {
    const el = e.target as HTMLSelectElement | null;
    if (!el?.matches?.('.hm-pri select[data-change="triage"]')) return;
    order[Number(el.dataset.i)] = el.value;
    const pick = el.closest<HTMLElement>('.hm-pri');
    if (pick) {
      pick.dataset.pri = el.value;
      const val = pick.querySelector('.hm-pri__val');
      if (val) val.textContent = PRI(el.value);
    }
  });
}

/* The job page rises in when you come to it from home (old page fades 160ms, the brief rises 12px
   over 280ms); reduced motion fades it in without moving. */
let enterNext = false;
/** Fade the page out and mark the next job page to rise in. */
export async function leaveForBrief(): Promise<void> {
  enterNext = true;
  const main = document.getElementById('main');
  if (!main || reduced() || typeof main.animate !== 'function') return;
  await main
    .animate([{ opacity: 1 }, { opacity: 0 }], { duration: 160, easing: 'ease', fill: 'forwards' })
    .finished.catch(() => {});
}

export function entryHtml(o: {
  topbar: string;
  caseId: string;
  title: string;
  quote: string;
  minutes: string;
  readouts: Readout[];
  /** The three starting tasks, in words. */
  seeds: string[];
  existingId: string | null;
  /** "Take this on" was pressed and the practice is opening: the key waits, the slips are lifted. */
  holding: boolean;
  variants: Variant[];
  after: string;
}): string {
  const g = PEOPLE.manager;
  const take = `<button type="button" class="btn primary large hm-take${o.holding ? ' is-loading' : ''}" data-action="take-case" data-case="${esc(o.caseId)}"${o.holding ? ' aria-busy="true" aria-disabled="true"' : ''}><span class="hm-take__glyph" aria-hidden="true">${o.holding ? '<i class="hm-spin"></i>' : icon('note', 'i-sm')}</span>${T('接手这件工作', 'Take this on')}</button>`;
  const foot =
    o.existingId && !o.holding
      ? `${key(T('重新开始一次', 'Start over'), 'take-case', 'quiet', `data-case="${esc(o.caseId)}"`)}${key(T('继续', 'Continue'), 'resume-attempt', 'primary large', `data-id="${esc(o.existingId)}"`)}`
      : take;
  const enter = enterNext;
  enterNext = false;
  const readout = (r: Readout) =>
    `<div class="hm-read${r.was ? ' is-changed' : ''}"><dt>${esc(r.label)}</dt><dd>${r.pre ? `<span>${esc(r.pre)}</span>` : ''}<b class="num">${esc(r.value)}</b>${r.unit ? `<span>${esc(r.unit)}</span>` : ''}${r.was ? `<small>${esc(T(`通常 ${r.was}`, `usually ${r.was}`))}</small>` : ''}</dd></div>`;
  const variant = (v: Variant) =>
    `<li class="hm-var">${key(`<span>${esc(v.label)}</span> <b class="num">${esc(v.value)}</b> <small>${esc(T(`通常 ${v.was}`, `usually ${v.was}`))}</small>`, v.openId ? 'resume-attempt' : 'take-case', 'ghost hm-var__key', v.openId ? `data-id="${esc(v.openId)}"` : `data-case="${esc(v.id)}"`)}${v.openId ? `<span class="hm-var__open">${T('进行中', 'In progress')}</span>` : ''}</li>`;
  return `${o.topbar}
    <main id="main" class="page hm-entry${o.holding ? ' is-holding' : ''}" tabindex="-1"${enter ? ' data-enter' : ''}>
      <header class="hm-entry__head">
        <p class="hm-entry__job">${JOB_PM()}</p>
        <p class="hm-entry__lede">${T('你负责判断一个 AI 功能能不能上线、先给谁用、怎样保障，并为这个决定负责。', 'You decide whether an AI feature is ready, who gets it first and how it stays safe, and you own that call.')}</p>
      </header>
      <article class="hm-brief paper case-hero" style="view-transition-name: case-surface" aria-labelledby="hm-brief-title">
        <header class="hm-brief__top">
          <h1 class="hm-brief__title" id="hm-brief-title"><span style="view-transition-name: case-title">${esc(o.title)}</span></h1>
          <span class="hm-brief__min">${esc(T(`${o.minutes}，没有倒计时`, `${o.minutes}, no countdown`))}</span>
        </header>
        <figure class="hm-brief__letter">
          <blockquote>${esc(o.quote)}</blockquote>
          <figcaption>${avatar('manager', 'sm')}<span><b>${esc(g.name)}</b> ${T('你的经理', 'your manager')}</span></figcaption>
        </figure>
        <dl class="hm-reads">${o.readouts.map(readout).join('')}</dl>
        <section class="hm-seeds" aria-labelledby="hm-seeds-cap">
          <p class="hm-seeds__cap" id="hm-seeds-cap">${T('你会接手这三件事，想先排个优先级也可以', 'You pick up these three tasks. Rank them now if you like')}</p>
          <ul class="hm-seeds__list">${o.seeds
            .map(
              (s, i) =>
                `<li class="hm-seed paper seed" style="--i:${i}">${seedPicker(i, s)}<span class="hm-seed__text">${esc(s)}</span></li>`,
            )
            .join('')}</ul>
        </section>
        <footer class="hm-brief__foot">${foot}</footer>
      </article>
      ${
        o.variants.length
          ? `<section class="hm-vars" aria-labelledby="hm-vars-cap"><p class="hm-vars__cap" id="hm-vars-cap">${T('或者换一个条件练：', 'Or practise a variant:')}</p><ul>${o.variants.map(variant).join('')}</ul></section>`
          : ''
      }
      <div class="hm-entry__after">${o.after}</div>
    </main>`;
}
