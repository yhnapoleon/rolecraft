import { avatar } from '../../app/art.js';
import {
  ARRIVAL_DELAYS,
  greetingStore,
  introduction,
  orderFor,
  type Job,
  type Language,
  type Person,
} from './model';
import './greetings.css';
const esc = (s: string) =>
  s.replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c,
  );
const storage = () => {
  try {
    return localStorage;
  } catch {
    return undefined;
  }
};
const book = greetingStore(storage());
export const hasGreetingEntry = (id: string) => book.job(id) !== null;
export const prepareGreetings = (id: string, job: Job) => book.prepare(id, job);
const running = new Map<string, { job: Job; shown: Person[]; dismissed: boolean }>();
const readIntroductions = new Set<string>();
const sent = new Set<string>();
let visibleSession: string | null = null;
let pending: string | null = null;
let timers: ReturnType<typeof setTimeout>[] = [];
const reduced = () => !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
const words = (l: Language, zh: string, en: string) => (l === 'zh' ? zh : en);
export function introductionHtml(
  id: string,
  job: Job,
  person: Person,
  language: Language,
  chat = false,
  writable = true,
) {
  const m = introduction(job, person, language),
    key = `${id}:${person}`;
  const questions = m.questions
    .map(
      (q, i) =>
        `<button type="button" class="rc-greet-question" data-action="greet-ask" data-role="${person}" data-question="${i}" ${!writable || sent.has(`${key}:${i}`) ? 'disabled' : ''}>${esc(q)}<span aria-hidden="true">↗</span></button>`,
    )
    .join('');
  const body = `<p class="rc-greet-hello">${esc(m.hello)}</p><p>${esc(m.body)}</p><div class="rc-greet-questions" aria-label="${words(language, '点一下直接提问', 'Select a question to send it')}">${questions}</div>`;
  if (chat)
    return `<details class="rc-greet-chat" data-greet-session="${esc(id)}" data-greet-role="${person}" ${readIntroductions.has(key) ? '' : 'open'}><summary>${words(language, '开场介绍 · 场景预设', 'Introduction · preset scene content')}</summary>${body}</details>`;
  return `<article class="rc-greet-card" data-greet-person="${person}"><header>${avatar(person, 'sm')}<div><b>${esc(m.name)}</b><span>${esc(m.title)}</span></div><small>${words(language, '场景预设', 'Preset opening')}</small></header>${body}<button type="button" class="btn quiet small" data-action="greet-chat" data-role="${person}">${words(language, '直接和我聊', 'Chat with me')} →</button></article>`;
}
export function rememberIntroduction(id: string, person: Person) {
  readIntroductions.add(`${id}:${person}`);
}
export function showIntroduction(id: string, person: Person) {
  readIntroductions.delete(`${id}:${person}`);
}
export function greetSlot(id: string) {
  return `<div data-greetings="${esc(id)}"></div>`;
}
function draw(id: string, language: Language, arrival?: Person) {
  const root = document.querySelector<HTMLElement>('[data-greetings]');
  const state = running.get(id);
  if (!root || root.dataset.greetings !== id || !state || state.dismissed) {
    if (root?.dataset.greetings === id) root.replaceChildren();
    return;
  }
  if (!root.firstElementChild)
    root.innerHTML = `<section class="rc-greetings" aria-label="${words(language, '认识你的同事', 'Meet your colleagues')}"><header class="rc-greetings-head"><div><h2>${words(language, '我们一起做这件事', 'Let’s get started together')}</h2><p>${words(language, '先认识一下。点问题直接发给同事，也可以自己问。', 'Meet the team. Choose a question to send, or ask your own.')}</p></div><button type="button" class="btn quiet small" data-action="greet-dismiss">${words(language, '开始工作', 'Get to work')}</button></header><div class="rc-greetings-list" aria-live="polite" aria-relevant="additions"></div></section>`;
  const list = root.querySelector<HTMLElement>('.rc-greetings-list');
  if (!list) return;
  for (const person of state.shown)
    if (!list.querySelector(`[data-greet-person="${person}"]`)) {
      list.insertAdjacentHTML('beforeend', introductionHtml(id, state.job, person, language));
      const node = list.lastElementChild as HTMLElement;
      if (person === arrival && !reduced())
        node.animate(
          [
            { opacity: 0, transform: 'translateY(8px)' },
            { opacity: 1, transform: 'none' },
          ],
          { duration: 240, easing: 'cubic-bezier(.23,1,.32,1)' },
        );
    }
}
/** Timers touch only the greeting surface, never the live conversation or its composer. */
let togglesInstalled = false;
export function mountGreetings(id: string | null, language: Language) {
  if (!togglesInstalled) {
    document.addEventListener('toggle', (event) => {
      const node = event.target;
      if (!(node instanceof HTMLDetailsElement) || !node.classList.contains('rc-greet-chat')) return;
      const key = `${node.dataset.greetSession}:${node.dataset.greetRole}`;
      if (node.open) readIntroductions.delete(key); else readIntroductions.add(key);
    }, true);
    togglesInstalled = true;
  }
  if (visibleSession !== id) {
    for (const timer of timers) clearTimeout(timer);
    timers = [];
    if (visibleSession) {
      const old = running.get(visibleSession);
      if (old) old.dismissed = true;
    }
    visibleSession = id;
  }
  if (!id) return;
  let state = running.get(id);
  if (!state) {
    const job = book.claim(id);
    if (!job) return;
    state = { job, shown: [], dismissed: false };
    running.set(id, state);
    orderFor(job).forEach((person, i) => {
      const arrive = () => {
        const current = running.get(id);
        if (!current || current.dismissed || visibleSession !== id) return;
        current.shown.push(person);
        draw(id, language, person);
      };
      if (reduced() || i === 0) arrive();
      else timers.push(setTimeout(arrive, ARRIVAL_DELAYS[i]));
    });
  }
  draw(id, language);
}
export function dismissGreetings(id: string) {
  const state = running.get(id);
  if (state) state.dismissed = true;
  for (const t of timers) clearTimeout(t);
  timers = [];
  document.querySelector(`[data-greetings="${CSS.escape(id)}"]`)?.replaceChildren();
}
/** A rapid repeated click never queues a second question. The host owns the real send path. */
export async function askGreeting(
  id: string,
  job: Job,
  person: Person,
  index: number,
  language: Language,
  send: (question: string) => Promise<boolean>,
) {
  const key = `${id}:${person}:${index}`;
  const question = introduction(job, person, language).questions[index];
  if (!question || pending || sent.has(key)) return;
  pending = key;
  try {
    if (await send(question)) {
      sent.add(key);
      for (const button of document.querySelectorAll<HTMLButtonElement>(
        `[data-action="greet-ask"][data-role="${person}"][data-question="${index}"]`,
      )) {
        button.disabled = true;
        button.title = words(language, '已转入对话', 'Sent to the conversation');
      }
      rememberIntroduction(id, person);
      document.querySelector<HTMLDetailsElement>('.rc-greet-chat')?.removeAttribute('open');
    }
  } finally {
    pending = null;
  }
}
