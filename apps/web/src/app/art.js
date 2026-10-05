// Visual vocabulary: icons, people, the product under test and case covers.
// Covers are drawn from the case's own constraints (launch day, seats), so the
// picture carries information instead of decorating the page.

const P = {
  edit: '<path d="m15.5 4.5 4 4M4.5 19.5l4.5-1L20 7.5a2.8 2.8 0 0 0-4-4L5 14.5z"/>',
  save: '<path d="M5 3.5h11l4.5 4.5v11.5a1 1 0 0 1-1 1h-15a1 1 0 0 1-1-1v-15a1 1 0 0 1 1-1z"/><path d="M7 3.5V9h9V3.5M7 20.5v-7h10v7"/>',
  trash: '<path d="M4 6.5h16M9 6.5v-3h6v3M6 6.5l.9 13h10.2l.9-13M10 10v6M14 10v6"/>',
  back: '<path d="M14.5 5.5 8 12l6.5 6.5"/>',
  chev: '<path d="m9.5 5.5 6.5 6.5-6.5 6.5"/>',
  down: '<path d="m6.5 9.5 5.5 5.5 5.5-5.5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  doc: '<path d="M7 3.5h6.5L18 8v12.5H7z"/><path d="M13.5 3.5V8H18M9.5 12.5h6M9.5 16h4.5"/>',
  note: '<path d="M6 4.5h12v15H6z"/><path d="M9 9h6M9 12.5h6M9 16h3.5"/>',
  flask: '<path d="M9.5 3.5h5M10.5 3.5v5.8L5.3 18.4a1.4 1.4 0 0 0 1.2 2.1h11a1.4 1.4 0 0 0 1.2-2.1l-5.2-9.1V3.5"/><path d="M7.6 14.5h8.8"/>',
  bubble: '<path d="M4.5 11.5c0-3.9 3.4-7 7.5-7s7.5 3.1 7.5 7-3.4 7-7.5 7c-1 0-2-.2-2.9-.5L5 19.5l1-3.6a6.7 6.7 0 0 1-1.5-4.4z"/>',
  check: '<path d="m5.5 12.5 4.2 4.2L18.5 7.8"/>',
  x: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
  bolt: '<path d="M13 3 5.5 13.2h5.6L10.5 21 18 10.8h-5.6z"/>',
  play: '<path d="M8 5.5v13l10.5-6.5z"/>',
  pause: '<path d="M8.5 5.5v13M15.5 5.5v13"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M12 3.5v2.2M12 18.3v2.2M20.5 12h-2.2M5.7 12H3.5M18 6l-1.6 1.6M7.6 16.4 6 18M18 18l-1.6-1.6M7.6 7.6 6 6"/>',
  refresh: '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 4.5v4.2h-4.2"/>',
  send: '<path d="M12 19.5v-15M6 10.5l6-6 6 6"/>',
  quote: '<path d="M5 18.5V13c0-3.6 1.6-6 4.6-7.2M14 18.5V13c0-3.6 1.6-6 4.6-7.2"/><path d="M5 13h4.5v5.5H5zM14 13h4.5v5.5H14z"/>',
  more: '<circle cx="6" cy="12" r="1.4" class="i-fill"/><circle cx="12" cy="12" r="1.4" class="i-fill"/><circle cx="18" cy="12" r="1.4" class="i-fill"/>',
  upload: '<path d="M12 15.5V4.5M7.5 9 12 4.5 16.5 9"/><path d="M5 15v4.5h14V15"/>',
  download: '<path d="M12 4.5v11M7.5 11 12 15.5 16.5 11"/><path d="M5 15v4.5h14V15"/>',
  copy: '<rect x="8.5" y="8.5" width="11" height="11" rx="2.5"/><path d="M15.5 8.5V6a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5"/>',
  branch: '<circle cx="6.5" cy="5.5" r="2"/><circle cx="6.5" cy="18.5" r="2"/><circle cx="17.5" cy="8.5" r="2"/><path d="M6.5 7.5v9M17.5 10.5c0 4-4 3.5-9.5 6.5"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.8h.01"/>',
  circle: '<circle cx="12" cy="12" r="7.5"/>',
  half: '<circle cx="12" cy="12" r="7.5"/><path d="M12 4.5a7.5 7.5 0 0 1 0 15z" class="i-fill"/>',
  done: '<circle cx="12" cy="12" r="8" class="i-fill"/><path d="m8.2 12.3 2.6 2.6 5-5.3" stroke="var(--on-fill, #fff)"/>',
  warn: '<path d="M12 4.5 3.8 19h16.4z"/><path d="M12 10v4.2M12 16.6h.01"/>',
  question: '<circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.5a2.5 2.5 0 1 1 3.4 2.3c-.6.3-1 .8-1 1.5v.4M12 16.8h.01"/>',
  good: '<circle cx="12" cy="12" r="8.5"/><path d="m8.3 12.3 2.6 2.6 4.9-5.2"/>',
  minus: '<circle cx="12" cy="12" r="8.5"/><path d="M8.5 12h7"/>',
  sidebar: '<rect x="3.5" y="4.5" width="17" height="15" rx="3"/><path d="M9.5 4.5v15"/>',
  team: '<circle cx="9" cy="9" r="3"/><path d="M3.8 18.5c.6-2.9 2.6-4.5 5.2-4.5s4.6 1.6 5.2 4.5"/><circle cx="16.5" cy="9.5" r="2.4"/><path d="M15.2 14.1c2.3-.2 4.2 1.2 4.9 4.4"/>',
  stale: '<path d="M18.5 9A7 7 0 0 0 6 7.3"/><path d="M5.5 15A7 7 0 0 0 18 16.7"/><path d="M18.5 4.5V9H14M5.5 19.5V15H10"/>',
  globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.4 2.4 3.4 5.3 3.4 8.5s-1 6.1-3.4 8.5c-2.4-2.4-3.4-5.3-3.4-8.5s1-6.1 3.4-8.5z"/>',
  layers: '<path d="m12 4.5 8 4.2-8 4.2-8-4.2z"/><path d="m4 12.5 8 4.2 8-4.2"/><path d="m4 16.3 8 4.2 8-4.2"/>',
  history: '<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path d="M4.5 4.5v4h4M12 8v4.3l3 1.8"/>',
  lock: '<rect x="5.5" y="10.5" width="13" height="9.5" rx="2.5"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
  seats: '<circle cx="7" cy="8" r="1.6" class="i-fill"/><circle cx="12" cy="8" r="1.6" class="i-fill"/><circle cx="17" cy="8" r="1.6" class="i-fill"/><circle cx="7" cy="13" r="1.6" class="i-fill"/><circle cx="12" cy="13" r="1.6" class="i-fill"/><circle cx="17" cy="13" r="1.6"/><circle cx="7" cy="18" r="1.6"/><circle cx="12" cy="18" r="1.6"/><circle cx="17" cy="18" r="1.6"/>',
  calendar: '<rect x="4.5" y="5.5" width="15" height="14" rx="2.5"/><path d="M4.5 9.5h15M8.5 3.5v4M15.5 3.5v4"/><path d="M15 15.2h.01" stroke-width="2.6"/>',
  hours: '<circle cx="12" cy="12" r="8"/><path d="M12 7.5v4.8l3 1.7"/>',
  sync: '<path d="M5 10a7 7 0 0 1 12.2-3.3L19 8.5M19 14a7 7 0 0 1-12.2 3.3L5 15.5"/><path d="M19 4.5v4h-4M5 19.5v-4h4"/>',
  hand: '<path d="M8 12.5V6.8a1.4 1.4 0 0 1 2.8 0v4.7M10.8 11V5.4a1.4 1.4 0 0 1 2.8 0v5.6M13.6 11V6.4a1.4 1.4 0 0 1 2.8 0v6.8"/><path d="M16.4 10.5a1.4 1.4 0 0 1 2.8 0v3.3a6.7 6.7 0 0 1-6.7 6.7h-.5a6 6 0 0 1-5-2.7L4.8 14.6a1.4 1.4 0 0 1 2.3-1.6L8 14.2"/>',
  spark: '<path d="M12 3.5c.6 3.9 2.2 5.6 6 6.5-3.8.9-5.4 2.6-6 6.5-.6-3.9-2.2-5.6-6-6.5 3.8-.9 5.4-2.6 6-6.5z"/><path d="M18.5 15.5c.2 1.4.8 2 2.2 2.3-1.4.3-2 .9-2.2 2.3-.2-1.4-.8-2-2.2-2.3 1.4-.3 2-.9 2.2-2.3z"/>',
  arrowRight: '<path d="M5 12h13.5M13 6.5l5.5 5.5-5.5 5.5"/>',
  stamp: '<path d="M9.5 4.5h5v4.2c0 1 .8 1.8 1.8 1.8h1.2a1.5 1.5 0 0 1 1.5 1.5v2.5h-14V12a1.5 1.5 0 0 1 1.5-1.5h1.2c1 0 1.8-.8 1.8-1.8z"/><path d="M5.5 18.5h13"/>',
  eye: '<path d="M3.5 12s3-6 8.5-6 8.5 6 8.5 6-3 6-8.5 6-8.5-6-8.5-6z"/><circle cx="12" cy="12" r="2.6"/>',
  filter: '<path d="M4.5 6.5h15M7.5 12h9M10.5 17.5h3"/>'
};

export const icon = (name, cls = '') => `<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true">${P[name] || ''}</svg>`;

/** Priority is a level, so it is drawn as bars (3 先做, 2 随后, 1 暂放) in ink. Hue is kept for state and people. */
export const priMark = p => { const n = p === 'first' ? 3 : p === 'next' ? 2 : 1; return `<svg class="pri-mark ${p}" viewBox="0 0 16 16" aria-hidden="true">${[0, 1, 2].map(i => `<rect x="${1.5 + i * 4.75}" y="${10.5 - i * 3.5}" width="3.25" height="${3.5 + i * 3.5}" rx="1"${i < n ? '' : ' class="off"'}/>`).join('')}</svg>`; };

export const statusMark = s => `<svg class="status-mark ${s}" viewBox="0 0 24 24" aria-hidden="true">${s === 'done' ? P.done : s === 'working' ? P.half : P.circle}</svg>`;

/** People and marks. Each hue names who: Priya violet, Mei magenta, Daniel teal, the assistant blue; your agent is ink like you. */
export const PEOPLE = {
  manager: { name: 'Priya', initial: 'P' },
  business: { name: 'Mei', initial: 'M' },
  technical: { name: 'Daniel', initial: 'D' }
};
export const ROLES = ['manager', 'business', 'technical'];

export function avatar(role, size = 'md', opts = {}) {
  const p = PEOPLE[role];
  if (!p) return '';
  return `<span class="av av-${size} who-${role} ${opts.typing ? 'typing' : ''}" aria-hidden="true"><span class="av-face">${p.initial}</span>${opts.dot ? '<span class="av-dot"></span>' : ''}</span>`;
}
export const agentMark = (size = 'md') => `<span class="mark mark-agent mark-${size}" aria-hidden="true"><svg viewBox="0 0 24 24">${P.spark}</svg></span>`;
export const assistantMark = (size = 'md') => `<span class="mark mark-assistant mark-${size}" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M6.5 6.5h7.5a3.5 3.5 0 0 1 3.5 3.5v0a3.5 3.5 0 0 1-3.5 3.5H11l-3.2 2.8v-2.8H6.5z"/><path d="M9.5 10h4.5"/></svg></span>`;
