/** The engineer's two screens, kept across the workbench's re-renders: the sign-off desk
 * (#/engineer/<ticket>) and a review's report (#/engineer-review/<review>). Each screen is built
 * once per practice, ticket or review and interface language, then re-attached, so inputs, open
 * rows and the candidate survive a redraw and a round trip to a report. */
import './desk.css';
import type { GatewayTransport } from '../../gateway-transport';
import { engineerApi, failureText, type TicketSource } from './api';
import { EngineerDesk, type AgentHost } from './desk';
import { openHandover } from './handover';
import type { HandoverTest } from './model';
import { EngineerReviewScreen } from './review-screen';

export type EngineerRoute = 'engineer' | 'engineer-review';
export interface ScreenKey {
  readonly route: EngineerRoute;
  readonly id: string | null;
  readonly sessionId: string;
  readonly language: 'zh' | 'en';
}
export interface ScreenContext {
  readonly caseTitle: string;
  readonly transport: GatewayTransport;
  readonly agentHost: AgentHost | null;
  navigate(route: EngineerRoute | 'work', id?: string): void;
  notify(text: string): void;
  download(data: unknown, name: string): void;
}

type Screen = (EngineerDesk | EngineerReviewScreen) & { resume?: () => void };
const screens = new Map<string, Screen>();
const KEEP = 6;
const reviewTickets = new Map<string, string>();

const keyOf = (k: ScreenKey) => [k.route, k.sessionId, k.id ?? '', k.language].join('|');

/** Where the report's back key leads: the desk of the review's ticket once it is known. */
export function engineerBackHref(reviewId: string | null): string {
  const ticket = reviewId ? reviewTickets.get(reviewId) : undefined;
  return ticket ? `#/engineer/${encodeURIComponent(ticket)}` : '#/engineer';
}

export function mountEngineerScreen(
  root: HTMLElement,
  key: ScreenKey,
  context: () => ScreenContext,
) {
  const id = keyOf(key);
  let screen = screens.get(id);
  if (screen) {
    screens.delete(id);
    screens.set(id, screen);
    root.replaceChildren(screen.element);
    screen.resume?.();
    return;
  }
  const ctx = context();
  const doc = root.ownerDocument;
  const api = engineerApi(ctx.transport, key.sessionId);
  const remember = (reviewId: string, ticketId: string) => reviewTickets.set(reviewId, ticketId);
  screen =
    key.route === 'engineer'
      ? new EngineerDesk(
          {
            doc,
            sessionId: key.sessionId,
            caseTitle: ctx.caseTitle,
            api,
            agentHost: ctx.agentHost,
            navigate: ctx.navigate,
            notify: ctx.notify,
            download: ctx.download,
            remember,
          },
          key.id,
        )
      : new EngineerReviewScreen(
          {
            doc,
            caseTitle: ctx.caseTitle,
            api,
            navigate: ctx.navigate,
            remember,
            backTo: (ticketId) => {
              const back = doc.querySelector<HTMLAnchorElement>('a[data-engineer-back]');
              if (back) back.href = `#/engineer/${encodeURIComponent(ticketId)}`;
            },
          },
          key.id ?? '',
        );
  screens.set(id, screen);
  while (screens.size > KEEP) {
    const [oldest, old] = screens.entries().next().value as [string, Screen];
    old.destroy();
    screens.delete(oldest);
  }
  root.replaceChildren(screen.element);
}

/** Open (or reopen: the same input returns the same ticket) a ticket in this practice. Failures
 * come back as one plain sentence. */
export async function openTicket(
  transport: GatewayTransport,
  sessionId: string,
  source: TicketSource,
) {
  try {
    return (await engineerApi(transport, sessionId).createTicket(source)).ticket;
  } catch (error) {
    throw new Error(failureText(error));
  }
}

export function openTestHandover(options: {
  transport: GatewayTransport;
  sessionId: string;
  tests: readonly HandoverTest[];
  open(ticketId: string): void;
}) {
  return openHandover({
    api: engineerApi(options.transport, options.sessionId),
    tests: options.tests,
    open: options.open,
  });
}
