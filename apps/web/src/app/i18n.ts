// Interface language. The default follows the system language; a manual choice
// is remembered per browser. Strings are written as Chinese/English pairs next to
// the code that uses them, so a missing translation is visible in review.
export type Locale = 'zh' | 'en';
export type Preference = Locale | 'auto';

const KEY = 'rolecraft.locale';
let current: Locale = 'zh';
let preference: Preference = 'auto';
const listeners = new Set<(l: Locale) => void>();

export function detect(
  languages: readonly string[] = typeof navigator === 'undefined'
    ? []
    : navigator.languages || [navigator.language],
): Locale {
  for (const raw of languages) {
    const l = String(raw || '').toLowerCase();
    if (l.startsWith('zh')) return 'zh';
    if (l.startsWith('en')) return 'en';
  }
  // Any other system language falls back to English, the course's presentation language.
  return 'en';
}

function apply() {
  if (typeof document === 'undefined') return;
  document.documentElement.lang = current === 'zh' ? 'zh-CN' : 'en';
}

export function initLocale(storage?: Pick<Storage, 'getItem'>) {
  try {
    const saved = storage?.getItem(KEY);
    if (saved === 'zh' || saved === 'en' || saved === 'auto') preference = saved;
  } catch {
    /* storage blocked: follow the system */
  }
  current = preference === 'auto' ? detect() : preference;
  apply();
  if (typeof window !== 'undefined') {
    window.addEventListener('languagechange', () => {
      if (preference === 'auto') setLocale(detect());
    });
  }
  return current;
}

function setLocale(next: Locale) {
  if (next === current) return;
  current = next;
  apply();
  listeners.forEach((l) => l(current));
}

export function setPreference(next: Preference, storage?: Pick<Storage, 'setItem'>) {
  preference = next;
  try {
    storage?.setItem(KEY, next);
  } catch {
    /* keep the choice for this page only */
  }
  setLocale(next === 'auto' ? detect() : next);
}

export const locale = () => current;
export const getPreference = () => preference;
export const onLocaleChange = (fn: (l: Locale) => void) => {
  listeners.add(fn);
  return () => listeners.delete(fn);
};

/** Pick the string for the current interface language. */
export const T = (zh: string, en: string) => (current === 'en' ? en : zh);

/** Locale-aware number formatting with tabular output where it matters. */
export const num = (n: number) =>
  new Intl.NumberFormat(current === 'en' ? 'en-US' : 'zh-CN').format(n);

/** Relative time for things this page saw happen. Empty when the time is unknown. */
export function when(iso?: string | null) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.valueOf())) return '';
  const minutes = (Date.now() - d.valueOf()) / 60000;
  if (minutes < 1) return T('刚刚', 'just now');
  if (minutes < 60) {
    const m = Math.floor(minutes);
    return T(m + ' 分钟前', m + ' min ago');
  }
  const tag = current === 'en' ? 'en-US' : 'zh-CN';
  const hm = d.toLocaleTimeString(tag, { hour: '2-digit', minute: '2-digit', hour12: false });
  if (d.toDateString() === new Date().toDateString()) return T('今天 ' + hm, 'Today ' + hm);
  return d.toLocaleDateString(tag, { month: 'short', day: 'numeric' }) + ' ' + hm;
}

/** True when a string is mostly Chinese, used to mark untranslated server text. */
export const isChinese = (s: string) => {
  const text = String(s || '');
  const cjk = (text.match(/[一-鿿]/g) || []).length;
  return cjk > 0 && cjk / Math.max(1, text.replace(/\s/g, '').length) > 0.2;
};
