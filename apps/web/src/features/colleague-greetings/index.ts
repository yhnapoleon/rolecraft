import { unreadStore } from './unread';
export { watchMessages } from './unread';
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
export const hasEntryStory = (id: string) => book.story(id);
export const hasGreetingEntry = (id: string) => book.job(id) !== null;
export const prepareGreetings = (id: string, job: Job) => book.prepare(id, job);
export const receipts = unreadStore(storage());
export const greetingId = 'preset-opening';
export const greetingArrived = (id: string, person: Person) => {
  const job = book.job(id),
    start = book.started(id);
  return (
    !!job && start !== null && Date.now() - start >= ARRIVAL_DELAYS[orderFor(job).indexOf(person)]
  );
};
export const finishArrivals = (id: string) => {
  // Completing the tour leaves all three colleagues waiting, even if it was skipped quickly.
  for (const timer of timers) clearTimeout(timer);
  timers = [];
  ready.add(id);
  book.complete(id);
  document.dispatchEvent(new Event('rolecraft:greetings'));
};
const ready = new Set<string>();
export const hasArrived = (id: string, person: Person) =>
  ready.has(id) || greetingArrived(id, person);
const readIntroductions = new Set<string>();
if (typeof document !== 'undefined')
  document.addEventListener(
    'toggle',
    (event) => {
      const el = event.target;
      if (!(el instanceof HTMLDetailsElement) || !el.classList.contains('rc-greet-chat')) return;
      const key = `${el.dataset.greetSession}:${el.dataset.greetRole}`;
      if (el.open) readIntroductions.delete(key);
      else readIntroductions.add(key);
    },
    true,
  );
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
  const body = `<div data-message-id="${greetingId}"><p class="rc-greet-hello">${esc(m.hello)}</p><p>${esc(m.body)}</p></div><div class="rc-greet-questions" aria-label="${words(language, '点一下直接提问', 'Select a question to send it')}">${questions}</div>`;
  if (!chat) return '';
  return `<details class="rc-greet-chat" data-greet-session="${esc(id)}" data-greet-role="${person}" ${readIntroductions.has(key) ? '' : 'open'}><summary>${words(language, '开场介绍 · 场景预设', 'Introduction · preset scene content')}</summary>${body}</details>`;
}

export function rememberIntroduction(id: string, person: Person) {
  readIntroductions.add(`${id}:${person}`);
}
export function showIntroduction(id: string, person: Person) {
  readIntroductions.delete(`${id}:${person}`);
}
/** Arrival changes only local unread state; the host patches badges and the introduction slot. */
export function mountGreetings(id: string | null, _language: Language) {
  if (visibleSession === id) return;
  for (const timer of timers) clearTimeout(timer);
  timers = [];
  visibleSession = id;
  if (!id) return;
  const job = book.job(id),
    start = book.start(id);
  if (!job || start === null) return;
  if (reduced()) {
    ready.add(id);
    book.complete(id);
  }
  orderFor(job).forEach((_person, i) => {
    const delay = start + ARRIVAL_DELAYS[i] - Date.now();
    if (delay > 0 && !ready.has(id))
      timers.push(
        setTimeout(() => {
          document.dispatchEvent(new Event('rolecraft:greetings'));
        }, delay),
      );
  });
  queueMicrotask(() => document.dispatchEvent(new Event('rolecraft:greetings')));
}
export function dismissGreetings(id: string) {
  finishArrivals(id);
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
