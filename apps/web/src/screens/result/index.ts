/** The result page's ties to the shell: the topbar's "Revise", and "your feedback is ready" when
 * the review arrives while the person is elsewhere (a toast once, and a signal in "Needs you"
 * until the result has been seen). Nothing here calls a model; it reads the stored feedback. */
import {
  registerActions,
  registerSignals,
  signalsChanged,
  toast,
  type Attempt,
  type Signal,
} from '../../shell';
import type { V4HostAdapter } from '../../v4-host';
import { resultSeen, seenResults } from './seen';

export { resultSeen };

type Deps = {
  /** The practice's v4 host, or null for one without the native workspace. */
  host: (attempt: Attempt) => V4HostAdapter | null;
  /** The practice's session id. */
  sessionOf: (attempt: Attempt) => string | null;
  current: () => Attempt | null;
  route: () => string;
  language: () => 'zh' | 'en';
};

type Ready = { submission: string; at: string };
const ready = new Map<string, Ready>();

const items = (value: unknown): unknown[] => {
  for (let depth = 0, v = value as Record<string, unknown> | null; depth < 4 && v; depth++) {
    if (Array.isArray(v.items)) return v.items;
    v = (v.result as Record<string, unknown>) ?? null;
  }
  return [];
};

let installed = false;
export function registerResultScreen(deps: Deps) {
  if (installed) return;
  installed = true;
  const T = (zh: string, en: string) => (deps.language() === 'en' ? en : zh);

  registerActions({
    // The topbar's primary key on the result page: the revision note at the end of the page.
    'result-revise': () => {
      document.dispatchEvent(new CustomEvent('rolecraft:result-revise'));
    },
  });

  registerSignals((attempt): Signal[] => {
    const sid = deps.sessionOf(attempt);
    const found = sid ? ready.get(sid) : undefined;
    if (!found || seenResults().has(found.submission) || deps.route() === 'review') return [];
    return [
      {
        id: `result-ready-${found.submission}`,
        source: 'system',
        text: T('反馈好了', 'Your feedback is ready'),
        action: { label: T('看结果', 'See the result'), action: 'to-review' },
        at: found.at,
      },
    ];
  });

  // After a delivery, read the stored feedback every few seconds until it is there (the
  // review takes 15–100 s). Reads only; stops after five minutes.
  let watching: string | null = null;
  async function watch(attempt: Attempt) {
    const host = deps.host(attempt);
    const sid = deps.sessionOf(attempt);
    if (!host || !sid || watching === sid) return;
    watching = sid;
    const until = Date.now() + 5 * 60_000;
    try {
      while (Date.now() < until && deps.sessionOf(deps.current()) === sid) {
        await new Promise((r) => setTimeout(r, 3000));
        if (document.hidden) continue;
        const subs = items(
          await host.query('submissions.list', { cursor: 0, limit: 100 } as never),
        );
        const last = subs.at(-1) as { id?: string } | undefined;
        if (!last?.id) continue;
        const reports = items(
          await host.query('feedback.read', {
            submission_id: last.id,
            cursor: 0,
            limit: 100,
          } as never),
        );
        if (!reports.length) continue;
        ready.set(sid, { submission: last.id, at: new Date().toISOString() });
        if (deps.route() === 'review') resultSeen(last.id);
        else {
          toast(T('反馈好了', 'Your feedback is ready'), {
            action: { label: T('看结果', 'See the result'), action: 'to-review' },
          });
          signalsChanged();
        }
        return;
      }
    } catch {
      // A failed read leaves things as they were; the result page still reads it on entry.
    } finally {
      if (watching === sid) watching = null;
    }
  }
  document.addEventListener('rolecraft:delivered', () => {
    const attempt = deps.current();
    if (attempt) void watch(attempt);
  });
}
