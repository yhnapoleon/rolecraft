// "Needs you" at the top of the right rail (decision 12): at most three things that ask for a
// response. The material says who is asking: a colleague's words are a paper note, a signal
// from the system or your agent is one line on the instrument face.
import { agentMark, avatar, icon } from '../../app/art.js';
import { T, when } from '../../app/i18n';
import type { Signal } from '../../shell/signals';

const MAX = 3;
const esc = (v: unknown) =>
  String(v ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string,
  );

export type SignalPeople = Record<string, { name: string; title: string }>;

const key = (s: Signal, cls: string) =>
  s.action
    ? `<button type="button" class="btn small ${cls}" data-action="${esc(s.action.action)}"${s.action.id != null ? ` data-id="${esc(s.action.id)}" data-key="${esc(s.action.id)}"` : ''} data-signal="${esc(s.id)}">${esc(s.action.label)}</button>`
    : '';
// A colleague's reminder (id "note:<key>") is set aside on the practice itself, as the
// reminders always were; any other dismissible signal is hidden in this browser.
const aside = (s: Signal) =>
  s.id.startsWith('note:')
    ? `<button type="button" class="btn small quiet" data-action="ack" data-key="${esc(s.id)}">${T('先放一放', 'Set aside')}</button>`
    : s.dismissible
      ? `<button type="button" class="btn small quiet" data-action="board-signal-dismiss" data-id="${esc(s.id)}">${T('先放一放', 'Set aside')}</button>`
      : '';

function note(s: Signal, people: SignalPeople) {
  const who = s.person && people[s.person];
  return `<article class="needs-note who-${esc(s.person || '')}" data-signal-id="${esc(s.id)}">
    <p class="needs-who">${s.person ? avatar(s.person, 'xs') : ''}<b>${esc(who?.name || '')}</b><span>${esc(who?.title || '')}</span></p>
    <p class="needs-text"${s.id.startsWith('note:') ? ` data-note-message-id="${esc(s.id)}"` : ''}>${esc(s.text)}</p>
    ${s.action || s.dismissible ? `<div class="needs-keys">${key(s, '')}${aside(s)}</div>` : ''}
  </article>`;
}

// The shell's Signal carries an optional tone (good / warn); a provider may also add a kicker,
// the small head line ("Engineering review · signed by you").
type Extra = { kicker?: string };
const extra = (s: Signal) => s as Signal & Extra;

// A sentence written as "head: conclusion" (as the engineering review's is, until its provider
// sends a kicker) splits into the two lines; the conclusion starts with a capital.
function split(s: Signal): { kicker: string; text: string } | null {
  const k = extra(s).kicker;
  if (k) return { kicker: k, text: s.text };
  const m = /^(.{6,60}?)[：:]\s*(.+)$/.exec(s.text);
  if (!m) return null;
  return { kicker: m[1], text: m[2].charAt(0).toUpperCase() + m[2].slice(1) };
}

// The state is told by one small mark only: a green tick, or an amber arrow down.
const DOWN =
  '<svg class="i i-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v13M6.5 12.5 12 18l5.5-5.5"/></svg>';
const toneMark = (tone?: 'good' | 'warn') =>
  tone === 'warn'
    ? `<span class="needs-tone is-warn">${DOWN}</span>`
    : tone === 'good'
      ? `<span class="needs-tone is-good">${icon('check', 'i-sm')}</span>`
      : '';

// A signal with a head line (B8): three layers on the instrument face, never a coloured block.
function report(s: Signal, parts: { kicker: string; text: string }) {
  const tone = s.tone;
  const head = `${icon('branch', 'i-xs')}<span>${esc(parts.kicker)}</span>${s.at ? `<span aria-hidden="true">·</span><time datetime="${esc(s.at)}">${esc(when(s.at))}</time>` : ''}`;
  return `<article class="needs-report is-${s.source}" data-signal-id="${esc(s.id)}">
    <p class="needs-kicker">${head}</p>
    <p class="needs-conclusion">${toneMark(tone)}<span>${esc(parts.text)}</span></p>
    ${s.action || s.dismissible ? `<div class="needs-keys">${key(s, '')}${aside(s)}</div>` : ''}
  </article>`;
}

function line(s: Signal) {
  const parts = s.source === 'system' ? split(s) : null;
  if (parts) return report(s, parts);
  const tone = s.tone;
  const mark =
    s.source === 'agent' ? agentMark('xs') : toneMark(tone) || icon('info', 'i-sm needs-sys');
  return `<div class="needs-line is-${s.source}" data-signal-id="${esc(s.id)}">${mark}<p class="needs-text">${esc(s.text)}</p>${key(s, 'quiet')}${s.dismissible ? `<button type="button" class="btn icon quiet small" data-action="board-signal-dismiss" data-id="${esc(s.id)}" aria-label="${esc(T('先放一放', 'Set aside'))}">${icon('x', 'i-xs')}</button>` : ''}</div>`;
}

/** The section, or nothing when nobody needs you. `fresh` ids play their arrival once. */
export function needsYou(signals: Signal[], people: SignalPeople, fresh: Set<string>) {
  const list = signals.slice(0, MAX);
  if (!list.length) return '';
  return `<section class="needs-you" aria-labelledby="needs-h"><h3 class="mini-title" id="needs-h">${T('需要你回应', 'Needs you')}</h3>${list
    .map((s) => {
      const html = s.source === 'person' ? note(s, people) : line(s);
      return fresh.has(s.id)
        ? html.replace('data-signal-id=', 'data-arriving data-signal-id=')
        : html;
    })
    .join('')}</section>`;
}
