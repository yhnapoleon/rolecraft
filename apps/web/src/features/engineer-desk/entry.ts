/** What the workbench (ui.js) needs from the engineer role, kept light: the home card and its
 * style come with the main bundle; the screens load on first use and then mount synchronously,
 * so a redraw never loses the person's place.
 *
 * The engineer's screens live inside the workspace (shell `registerRoute`): the top bar (hat
 * switch, the engineer's scale, agent lamp, primary key) and the right rail (people, what needs
 * you) stay; the intro, the desk, a report and "nothing to fix" are the main screen (#ws-stage).
 * `#/engineer/<ticket>[?intro|?step=…]`, `#/engineer/?intro&revise`, `#/engineer/?nothing`,
 * `#/engineer-review/<review>`. */
import './entry.css';
export {
  ENGINEER_NOTHING_ID,
  ENGINEER_REVISE_ID,
  engineerEntryId,
  takeInPractice,
} from './wire';
import { PRODUCT_NAME } from '../../app/product.js';
import type { GatewayTransport } from '../../gateway-transport';
import { registerRoute } from '../../shell';
import { engineerApi, failureText, type LearnerRole, type TicketSource } from './api';
import './grace-signal';
import type { AgentHost } from './desk';
import type { HandoverTest, TicketDetail } from './model';
import { practiceFacts } from './need';
import type { ScreenContext, ScreenKey } from './screens';
import { setEngineerNavigator, setEngineerPorts } from './wire';

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

/** A route id as the hash carries it: `<ticket>?intro`, `<ticket>?step=fix`, `?nothing`. */
export function engineerRouteParts(routeId: string | null): {
  id: string | null;
  intro: boolean;
  revise: boolean;
  nothing: boolean;
  step: 'reproduce' | 'fix' | 'signoff' | null;
} {
  if (!routeId) return { id: null, intro: false, revise: false, nothing: false, step: null };
  const [id, query = ''] = routeId.split('?');
  const params = new URLSearchParams(query);
  const step = params.get('step');
  return {
    id: id || null,
    intro: params.has('intro'),
    revise: params.has('revise'),
    nothing: params.has('nothing'),
    step: step === 'reproduce' || step === 'fix' || step === 'signoff' ? step : null,
  };
}

/** What the workbench hands the engineer's screens once, at boot. */
export interface EngineerHost {
  // biome-ignore lint/suspicious/noExplicitAny: the engine's attempt is untyped JavaScript
  current(): any;
  language(): 'zh' | 'en';
  // biome-ignore lint/suspicious/noExplicitAny: the engine's attempt is untyped JavaScript
  native(a: any): boolean;
  // biome-ignore lint/suspicious/noExplicitAny: the engine's attempt is untyped JavaScript
  transport(a: any): GatewayTransport;
  // biome-ignore lint/suspicious/noExplicitAny: the engine's attempt is untyped JavaScript
  agentHost(a: any): AgentHost | null;
  /** Go to a screen; `transition` plays the main screen's change (only #ws-stage moves). */
  navigate(route: string, id?: string | null, transition?: boolean): void;
  refresh(parts: ('toolbar' | 'stage' | 'rail')[]): void;
  notify(text: string): void;
  download(data: unknown, name: string): void;
}
let host: EngineerHost | null = null;

export function installEngineer(h: EngineerHost) {
  host = h;
  setEngineerPorts({ current: h.current, transport: h.transport, refresh: h.refresh });
  setEngineerNavigator((route, id) => navigateStage(route, id));
}

/** Engineer screens move only the main screen: while their view transition runs, the top bar and
 * the rail keep their place (desk.css names #ws-stage under html.ed-vt-stage). */
export function navigateStage(route: string, id?: string | null) {
  const root = document.documentElement;
  root.classList.add('ed-vt-stage');
  host?.navigate(route, id ?? null, true);
  setTimeout(() => root.classList.remove('ed-vt-stage'), 900);
}

function mountRoute(route: 'engineer' | 'engineer-review') {
  return (stage: HTMLElement) => {
    const a = host?.current();
    const root = stage.querySelector<HTMLElement>('[data-engineer-screen]');
    if (!host || !a || !root) return;
    if (!host.native(a)) {
      root.textContent = '';
      return;
    }
    const routeId = decodeHashId(route);
    const parts = engineerRouteParts(routeId);
    const h = host;
    mountEngineerRoute(
      root,
      {
        route,
        id: parts.id,
        intro: parts.intro,
        revise: parts.revise,
        nothing: route === 'engineer' && parts.nothing,
        step: parts.step,
        sessionId: a.id,
        language: h.language(),
      },
      () => ({
        transport: h.transport(a),
        agentHost: h.agentHost(a),
        navigate: (to, id) => navigateStage(to === 'home' ? '' : to, id),
        notify: h.notify,
        download: h.download,
        facts: () => practiceFacts(h.current() ?? a),
        // The tab's name: after the workspace has set its own (it names the case).
        title: (short) => {
          queueMicrotask(() => {
            document.title = `${short} · ${PRODUCT_NAME}`;
          });
        },
      }),
    );
  };
}

/** The route id from the address (`#/engineer/<id>`), as ui.js decodes it. */
function decodeHashId(route: string): string | null {
  const [r, id] = location.hash.replace(/^#\/?/, '').split('/');
  return r === route && id ? decodeURIComponent(id) : null;
}

registerRoute(
  'engineer',
  () => '<div class="ed-stage" data-engineer-screen></div>',
  mountRoute('engineer'),
);
registerRoute(
  'engineer-review',
  () => '<div class="ed-stage" data-engineer-screen></div>',
  mountRoute('engineer-review'),
);

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
  colleague?: { taskId: string | null; done(ticket: TicketDetail): void };
}) {
  return (await screens()).openTestHandover(options);
}

/* ---------- one role per practice (phase 2) ---------- */
export async function colleagueReported(
  ...args: Parameters<typeof import('./colleague').colleagueReported>
) {
  return (await import('./colleague')).colleagueReported(...args);
}
export async function handToGrace(...args: Parameters<typeof import('./colleague').handToGrace>) {
  return (await import('./colleague')).handToGrace(...args);
}
/** Writes the practice's role on the server, retrying a dropped request twice. */
export async function writeLearnerRole(
  transport: GatewayTransport,
  sessionId: string,
  role: LearnerRole,
): Promise<void> {
  let last: unknown;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      await engineerApi(transport, sessionId).setRole(role);
      return;
    } catch (error) {
      last = error;
    }
  }
  throw new Error(failureText(last));
}
export async function readLearnerRole(
  transport: GatewayTransport,
  sessionId: string,
): Promise<LearnerRole | null> {
  return engineerApi(transport, sessionId).learnerRole();
}
