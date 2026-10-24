/** What the workbench (ui.js) needs from the engineer role, kept light: the home card and its
 * style come with the main bundle; the screens load on first use and then mount synchronously,
 * so a redraw never loses the person's place. */
import './entry.css';
import type { GatewayTransport } from '../../gateway-transport';
import type { TicketSource } from './api';
import type { HandoverTest } from './model';
import type { ScreenContext, ScreenKey } from './screens';

export { engineerCareerCardHtml, ENGINEER_CASES } from './career-card';

type Screens = typeof import('./screens');
let loaded: Screens | null = null;
let loading: Promise<Screens> | null = null;
function screens(): Promise<Screens> {
  if (loaded) return Promise.resolve(loaded);
  if (!loading)
    loading = import('./screens').then((m) => {
      loaded = m;
      return m;
    });
  return loading;
}

export const ENGINEER_ROUTES: readonly string[] = ['engineer', 'engineer-review'];

/** Mount the desk or a report into the page's main element. */
export function mountEngineerRoute(
  root: HTMLElement,
  key: ScreenKey,
  context: () => ScreenContext,
) {
  if (loaded) {
    loaded.mountEngineerScreen(root, key, context);
    return;
  }
  void screens().then((m) => {
    if (root.isConnected) m.mountEngineerScreen(root, key, context);
  });
}

/** The report page's back key: the desk of its ticket when known. */
export function engineerBackHref(reviewId: string | null): string {
  return loaded ? loaded.engineerBackHref(reviewId) : '#/engineer';
}

/** Open (or reopen) a ticket in a practice; throws one plain sentence on failure. */
export async function openEngineerTicket(
  transport: GatewayTransport,
  sessionId: string,
  source: TicketSource,
) {
  return (await screens()).openTicket(transport, sessionId, source);
}

export async function openEngineerHandover(options: {
  transport: GatewayTransport;
  sessionId: string;
  tests: readonly HandoverTest[];
  open(ticketId: string): void;
}) {
  return (await screens()).openTestHandover(options);
}
