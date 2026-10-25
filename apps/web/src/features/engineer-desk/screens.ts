/** The engineer's screens, kept across the workbench's re-renders: the intro (first time the hat
 * goes on, `#/engineer/<ticket>?intro`), the sign-off desk (`#/engineer/<ticket>[?step=…]`) and a
 * review's report (`#/engineer-review/<review>`). Each is built once per practice, ticket or review
 * and interface language, then re-attached, so inputs, open rows and the candidate survive a
 * redraw and a round trip to a report. Entering any of them puts on the engineer's hat. */
import './desk.css';
import type { GatewayTransport } from '../../gateway-transport';
import { setHat, setLastTicket } from '../../shell';
import type { EngineerReviewRecord } from '../engineer-report';
import { engineerApi, failureText, type TicketSource } from './api';
import { EngineerDesk, type AgentHost } from './desk';
import { openHandover } from './handover';
import { IntroScreen } from './intro';
import { updateEngineerLocal } from './local-state';
import type { HandoverTest, TicketDetail } from './model';
import type { PracticeFacts } from './need';
import { NothingScreen } from './nothing';
import { EngineerReviewScreen } from './review-screen';
import type { StepId } from './stage';
import { ENGINEER_NOTHING_ID, rememberSession, setEngineerNavigator } from './wire';

export type EngineerRoute = 'engineer' | 'engineer-review';
export interface ScreenKey {
  readonly route: EngineerRoute;
  readonly id: string | null;
  readonly sessionId: string;
  readonly language: 'zh' | 'en';
  /** `?intro`: the first time this practice puts on the engineer's hat. */
  readonly intro?: boolean;
  /** `?intro&revise`: a delivered practice; the intro opens a revision first. */
  readonly revise?: boolean;
  /** `?step=fix`: open that step (from the report's "fix it again", "see the sheet"). */
  readonly step?: StepId | null;
  /** `?nothing`: this practice has nothing to fix (189); shown in the intro's place. */
  readonly nothing?: boolean;
}
export interface ScreenContext {
  readonly transport: GatewayTransport;
  readonly agentHost: AgentHost | null;
  navigate(route: EngineerRoute | 'work' | 'bench' | 'home', id?: string): void;
  notify(text: string): void;
  download(data: unknown, name: string): void;
  title(short: string): void;
  /** The practice's own facts (policy, index, warning setting), read now. */
  facts(): PracticeFacts;
}

type Screen = (EngineerDesk | EngineerReviewScreen | IntroScreen | NothingScreen) & {
  resume?: (step?: StepId | null) => void;
  suspend?: () => void;
};
/** Every kept screen but the one coming on goes quiet (a kept desk no longer takes actions). */
const quietOthers = (on: Screen) => {
  for (const s of screens.values()) if (s !== on) s.suspend?.();
};
const screens = new Map<string, Screen>();
/** The address each kept screen was last shown at: a redraw at the same address is not an arrival. */
const shownAt = new WeakMap<Screen, string>();
function arrived(screen: Screen): boolean {
  const at = typeof location === 'undefined' ? '' : location.hash;
  const fresh = shownAt.get(screen) !== at;
  shownAt.set(screen, at);
  return fresh;
}
const KEEP = 6;
const reviewTickets = new Map<string, string>();
const tickets = new Map<string, TicketDetail>();
let justSigned: { record: EngineerReviewRecord; ticket: TicketDetail } | null = null;

const keyOf = (k: ScreenKey) =>
  [
    k.nothing ? 'nothing' : k.revise ? 'revise' : k.intro ? 'intro' : k.route,
    k.sessionId,
    k.id ?? '',
    k.language,
  ].join('|');

export function mountEngineerScreen(
  root: HTMLElement,
  key: ScreenKey,
  context: () => ScreenContext,
) {
  const id = keyOf(key);
  let screen = screens.get(id);
  // The workspace mounts its main screen after every redraw, also when only the top bar changed:
  // the screen already in place stays as it is (no second read, no lost step).
  if (screen && screen.element.parentElement === root && root.isConnected) return;
  if (!key.nothing) setHat(key.sessionId, 'engineer');
  if (key.route === 'engineer' && key.id && !key.intro) setLastTicket(key.sessionId, key.id);
  const ctx = context();
  setEngineerNavigator((route, target) => ctx.navigate(route, target));
  rememberSession(key.sessionId, ctx.transport);
  if (screen) {
    screens.delete(id);
    screens.set(id, screen);
    quietOthers(screen);
    root.replaceChildren(screen.element);
    // The address's step (`?step=fix`) is a way in: applied when the person arrives, not again on
    // every redraw of the main screen (a poll or a signal must not close the step they are in).
    screen.resume?.(arrived(screen) ? (key.step ?? null) : null);
    return;
  }
  const doc = root.ownerDocument;
  const api = engineerApi(ctx.transport, key.sessionId);
  const remember = (reviewId: string, ticketId: string) => reviewTickets.set(reviewId, ticketId);
  if (key.nothing) {
    screen = new NothingScreen({
      doc,
      facts: ctx.facts(),
      notify: ctx.notify,
      toBench: () => {
        setHat(key.sessionId, 'pm');
        ctx.navigate('bench');
      },
    });
  } else if (key.intro && (key.id || key.revise)) {
    const ticketId = key.id;
    screen = new IntroScreen(
      {
        doc,
        sessionId: key.sessionId,
        api,
        ticket: ticketId ? (tickets.get(ticketId) ?? null) : null,
        keep: (t) => tickets.set(t.id, t),
        take: (t) => {
          tickets.set(t.id, t);
          // The problem flies into Daniel's ticket (desk.css names both only during this).
          doc.documentElement.classList.add('ed-vt-take');
          setTimeout(() => doc.documentElement.classList.remove('ed-vt-take'), 900);
          ctx.navigate('engineer', t.id);
        },
        backToProduct: () => {
          updateEngineerLocal(key.sessionId, { introSeen: true });
          setHat(key.sessionId, 'pm');
          ctx.navigate('work');
        },
        home: () => ctx.navigate('home'),
        facts: ctx.facts,
        nothing: () => ctx.navigate('engineer', ENGINEER_NOTHING_ID),
      },
      ticketId,
      !!key.revise,
    );
  } else if (key.route === 'engineer')
    screen = new EngineerDesk(
      {
        doc,
        sessionId: key.sessionId,
        api,
        agentHost: ctx.agentHost,
        navigate: ctx.navigate,
        notify: ctx.notify,
        download: ctx.download,
        remember,
        title: ctx.title,
        cacheReview: (record, ticket) => {
          justSigned = { record, ticket };
          tickets.set(ticket.id, ticket);
        },
      },
      key.id,
      key.id ? (tickets.get(key.id) ?? null) : null,
    );
  else {
    const cached = justSigned?.record.review_id === key.id ? justSigned : null;
    justSigned = null;
    screen = new EngineerReviewScreen(
      {
        doc,
        sessionId: key.sessionId,
        api,
        cached,
        navigate: ctx.navigate,
        remember,
        title: ctx.title,
      },
      key.id ?? '',
    );
  }
  screens.set(id, screen);
  while (screens.size > KEEP) {
    const [oldest, old] = screens.entries().next().value as [string, Screen];
    old.destroy();
    screens.delete(oldest);
  }
  quietOthers(screen);
  root.replaceChildren(screen.element);
  arrived(screen);
  screen.resume?.(key.step ?? null);
  (root.querySelector('#ed-title') as HTMLElement | null)?.focus({ preventScroll: true });
}

/** The situation's ticket if one was opened earlier in this practice (reading opens nothing), for
 * a delivered practice whose own facts cannot say whether there is still something to fix. */
export async function seededTicket(
  transport: GatewayTransport,
  sessionId: string,
): Promise<TicketDetail | null> {
  try {
    const api = engineerApi(transport, sessionId);
    const seeded = (await api.tickets()).find((t) => t.source === 'seeded');
    if (!seeded) return null;
    const ticket = await api.ticket(seeded.id);
    tickets.set(ticket.id, ticket);
    return ticket;
  } catch {
    return null;
  }
}

/** Open (or reopen: the same input returns the same ticket) a ticket in this practice. Failures
 * come back as one plain sentence. */
export async function openTicket(
  transport: GatewayTransport,
  sessionId: string,
  source: TicketSource,
) {
  try {
    const ticket = (await engineerApi(transport, sessionId).createTicket(source)).ticket;
    tickets.set(ticket.id, ticket);
    return ticket;
  } catch (error) {
    throw new Error(failureText(error));
  }
}

export function openTestHandover(options: {
  transport: GatewayTransport;
  sessionId: string;
  tests: readonly HandoverTest[];
  open(ticketId: string): void;
  colleague?: { taskId: string | null; done(ticket: TicketDetail): void };
}) {
  return openHandover({
    api: engineerApi(options.transport, options.sessionId),
    tests: options.tests,
    open: options.open,
    colleague: options.colleague,
  });
}
