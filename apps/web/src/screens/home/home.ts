/** Home role selection, the resume strip, and the product-manager brief.
 * Pure HTML builders; ui.js supplies data and owns the actions. */
import './home.css';
import { careersHtml } from './careers';
import { avatar, icon, PEOPLE } from '../../app/art.js';
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
const JOB_PM = () => T('AI 产品经理', 'AI Product Manager');
const TWO_HATS = () =>
  T(
    '一局只演一个岗位。另一边的工作由 AI 同事承担：你做产品经理，工程修复由 Daniel 负责；你做工程师，产品侧由 Grace 接收。',
    'One practice, one role. An AI colleague takes the other side: as product manager, Daniel handles the engineering fix; as engineer, Grace receives it for the product side.',
  );
const reduced = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

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

export function homeHtml(o: {
  topbar: string;
  quote: string;
  capacity: number;
  resume: ContinueInfo | null;
  continueCode: string;
}): string {
  return careersHtml({ ...o, resumeHtml: o.resume ? continueSlip(o.resume) : '' });
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
