/** The engineer hat plugged into the shell (main bundle, light): the scale and its one key
 * (`registerStage`), the actions behind them (`registerActions`), and "needs you" signals
 * (`registerSignals`): the Agent's draft waiting for the engineer, and a review handed back to the
 * product manager. The desk publishes what it knows here; the stage is computed from that. */
import { T } from '../../app/i18n';
import {
  hatOf,
  lastTicket,
  registerActions,
  registerSignals,
  registerStage,
  roleOf,
  setHat,
  signalsChanged,
  toast,
  type Signal,
  type Stage,
} from '../../shell';
import type { GatewayTransport } from '../../gateway-transport';
import { handToGrace } from './colleague';
import { handedToGrace } from './grace-signal';
import { engineerHatTitlePair } from './copy';
import { handBackSignal, outcomeClean, type ReviewResult } from './hand-back';
import { engineerLocal, recordHandBack, updateEngineerLocal, type HatOrigin } from './local-state';
import type { Settings, TicketDetail } from './model';
import { fixNeed, fixNeedFromPractice, practiceFacts } from './need';
import { deskTarget, engineerStage, STEP_LABELS, type ReviewOutcome } from './stage';

type Pair = [string, string];
export interface DeskLive {
  readonly ticket: TicketDetail;
  readonly candidate: Settings;
  readonly blocked?: Pair;
  /** The sign-off sheet is on screen (open and at least 40% in view): the paper's own key is
   * the one to press, so the top bar's key steps back (plan §13.1). */
  readonly sheetInView?: boolean;
}

/** What the engineer line needs from the workbench (ui.js hands it over once, at boot). */
export interface EngineerPorts {
  // biome-ignore lint/suspicious/noExplicitAny: the engine's attempt is untyped JavaScript
  current(): any;
  // biome-ignore lint/suspicious/noExplicitAny: the engine's attempt is untyped JavaScript
  transport(a: any): GatewayTransport;
  /** Redraw parts of the workspace (after the desk's stage changed: the top bar's scale and key). */
  refresh(parts: ('toolbar' | 'stage' | 'rail')[]): void;
}
let ports: EngineerPorts | null = null;
export function setEngineerPorts(p: EngineerPorts) {
  ports = p;
}
export interface ReviewFacts {
  readonly ticketId: string;
  readonly outcome: ReviewOutcome;
  readonly newFailures: number;
  /** What the review came to (the same reading as the report's headline). */
  readonly result: ReviewResult;
  /** The ticket's source, when known: the signal's subject. */
  readonly source?: 'seeded' | 'tests';
}

const live = new Map<string, DeskLive>();
const outcomes = new Map<string, ReviewFacts>();
const listeners = new Set<() => void>();
/** The desk on screen handles its own actions (it knows the candidate and the open step). Its
 * `run` answers false once its element has left the page. */
let desk: { sessionId: string; run(action: string, id?: string): boolean } | null = null;
let navigate: ((route: 'engineer' | 'engineer-review' | 'work', id?: string) => void) | null = null;

/** What the "needs you" signals read from a desk: its latest draft and which drafts are signed. */
const signalKey = (s: DeskLive | undefined) =>
  s
    ? JSON.stringify([
        s.ticket.latest_draft?.id ?? null,
        s.ticket.latest_draft?.executor.kind ?? null,
        s.ticket.reviews.map((r) => r.draft_id),
      ])
    : '';
const changed = (signals: boolean) => {
  for (const cb of listeners) cb();
  if (signals) signalsChanged();
};
const stageKey = (sessionId: string) => JSON.stringify(deskStage(sessionId));

/** The desk says what it knows. The top bar is redrawn only when the scale or the key changed
 * (the bar's redraw mounts the desk again, which publishes again: same stage, nothing more). */
export function publishDesk(sessionId: string, snapshot: DeskLive) {
  const before = signalKey(live.get(sessionId));
  const stageBefore = stageKey(sessionId);
  live.set(sessionId, snapshot);
  const bar = stageBefore !== stageKey(sessionId);
  changed(before !== signalKey(snapshot));
  if (bar && ports?.current()?.id === sessionId) ports.refresh(['toolbar']);
}
export function publishReview(reviewId: string, facts: ReviewFacts) {
  const old = outcomes.get(reviewId);
  if (
    old?.outcome === facts.outcome &&
    old.newFailures === facts.newFailures &&
    (old.source ?? null) === (facts.source ?? old.source ?? null)
  )
    return;
  outcomes.set(reviewId, { ...facts, source: facts.source ?? old?.source });
  changed(false);
}
export function reviewFacts(reviewId: string) {
  return outcomes.get(reviewId);
}
export function onDeskChange(cb: () => void) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}
export function attachDesk(handler: typeof desk) {
  desk = handler;
}
export function detachDesk(handler: typeof desk) {
  if (desk === handler) desk = null;
}
/** The practice whose engineer screens were last on screen (before the ports are installed). */
let lastSession: { sessionId: string; transport: GatewayTransport } | null = null;
export function rememberSession(sessionId: string, transport: GatewayTransport) {
  lastSession = { sessionId, transport };
}
export function setEngineerNavigator(fn: typeof navigate) {
  navigate = fn;
}

export function go(route: 'engineer' | 'engineer-review' | 'work', id?: string) {
  if (navigate) navigate(route, id);
  else location.hash = `#/${route}${id ? `/${encodeURIComponent(id)}` : ''}`;
}

/** The engineer's scale and key for a practice, from what its desk last published, with the
 * top bar's name for this hat (`Stage.title`). */
export function deskStage(sessionId: string): Stage {
  const state = live.get(sessionId);
  if (!state) return deskScale(undefined);
  const stage = deskScale(state);
  // An engineer's practice: the clean report goes to Grace, the product side (phase 2).
  const handed =
    stage.primary?.id && roleOf(sessionId) === 'engineer'
      ? handedToGrace(sessionId, stage.primary.id)
      : null;
  const primary =
    stage.primary?.action === 'engineer.hand-back' && roleOf(sessionId) === 'engineer'
      ? handed?.result === 'applied'
        ? {
            ...stage.primary,
            label: ['已交回 Grace', 'Handed to Grace'] as Pair,
            disabledReason: ['Grace 已经按这份报告应用了', 'Grace applied this report'] as Pair,
          }
        : { ...stage.primary, label: ['交回 Grace', 'Hand to Grace'] as Pair }
      : stage.primary;
  return { ...stage, primary, title: engineerHatTitlePair(state.ticket) };
}

/** While the sheet is in view its own ink key ("hold to sign") is the one: the shell's key has no
 * secondary look, so "go to sign-off" stays visible but steps back as a key with its reason. */
const ON_THE_SHEET: Pair = ['签字单就在下面', 'The sheet is right here'];

function deskScale(state: DeskLive | undefined): Stage {
  if (!state)
    return {
      steps: (['reproduce', 'fix', 'signoff'] as const).map((id) => ({
        id,
        label: STEP_LABELS[id],
        state: id === 'reproduce' ? 'current' : 'todo',
      })),
    };
  const known: Record<string, ReviewOutcome> = {};
  for (const r of state.ticket.reviews) {
    const facts = outcomes.get(r.review_id);
    if (facts) known[r.review_id] = facts.outcome;
  }
  const stage = engineerStage(state.ticket, {
    candidate: state.candidate,
    outcomes: known,
    blocked: state.blocked,
  });
  const p = stage.primary;
  if (state.sheetInView && p?.action === 'engineer.signoff.focus' && !p.disabledReason)
    return { ...stage, primary: { ...p, disabledReason: ON_THE_SHEET } };
  return stage;
}

/** Hand a review back to the product manager: noted here (no server call), the hat changes, and the
 * product board shows the signal. */
export function handBack(sessionId: string, reviewId: string) {
  if (roleOf(sessionId) === 'engineer') {
    void graceDecides(sessionId, reviewId);
    return;
  }
  const facts = outcomes.get(reviewId);
  const ticket = live.get(sessionId)?.ticket;
  const ticketId = facts?.ticketId ?? ticket?.id ?? '';
  // The subject follows the review's own ticket (after a reload the desk may not be published).
  const source =
    facts?.source ?? (ticket && ticket.id === ticketId ? ticket.source : undefined) ?? 'seeded';
  recordHandBack(sessionId, reviewId, {
    at: new Date().toISOString(),
    ticketId,
    clean: facts ? outcomeClean(facts.result) : false,
    newFailures: facts?.newFailures ?? 0,
    title: source,
    result: facts?.result,
  });
  setHat(sessionId, 'pm');
  signalsChanged();
  go('work');
}

/** An engineer's practice: the signed report goes to Grace, who decides by rule on the server.
 * Her reply comes back in her words (a toast now, her note in Needs you); the person stays on the
 * desk, still an engineer. */
async function graceDecides(sessionId: string, reviewId: string) {
  const a = practiceNow();
  const transport = a?.id === sessionId ? transportOf(a) : lastSession?.transport;
  const ticketId = outcomes.get(reviewId)?.ticketId ?? live.get(sessionId)?.ticket.id;
  if (!transport || !ticketId) return;
  try {
    const decision = await handToGrace(transport, sessionId, ticketId, reviewId);
    toast(decision.reply || T('已交回 Grace', 'Handed to Grace'));
  } catch (error) {
    toast(error instanceof Error ? error.message : String(error));
  }
}

/** The intro for a delivered practice: it opens a revision before taking the ticket. */
export const ENGINEER_REVISE_ID = '?intro&revise';
/** "Nothing to fix in this practice" (189): shown in the intro's place, no ticket opened. */
export const ENGINEER_NOTHING_ID = '?nothing';

/** Where to go when the hat goes on: the intro the first time in this practice, else the desk.
 * Puts the hat on and remembers how it was first put on (the intro's words depend on it). */
export function engineerEntryId(sessionId: string, ticketId: string, origin: HatOrigin): string {
  setHat(sessionId, 'engineer');
  const local = engineerLocal(sessionId);
  if (!local.origin) updateEngineerLocal(sessionId, { origin });
  return local.introSeen ? ticketId : `${ticketId}?intro`;
}

// The practice on screen: the workbench's own (ports), else the one the shell last asked about.
// biome-ignore lint/suspicious/noExplicitAny: the engine's attempt is untyped JavaScript
let asked: any = null;
// biome-ignore lint/suspicious/noExplicitAny: the engine's attempt is untyped JavaScript
const practiceNow = (): any => ports?.current() ?? asked;
registerStage('engineer', (attempt) => {
  asked = attempt ?? asked;
  return deskStage(attempt?.id);
});

// biome-ignore lint/suspicious/noExplicitAny: the engine's attempt is untyped JavaScript
function transportOf(a: any): GatewayTransport {
  if (ports) return ports.transport(a);
  const wb = (
    window as unknown as { PracticeLive: { gatewayTransport(a: unknown): GatewayTransport } }
  ).PracticeLive;
  return wb.gatewayTransport(a);
}

/** Put on the engineer's hat in a practice already under way (the top bar's switch, home's "take
 * the ticket in this practice"). Back to the desk's last ticket when there is one. Otherwise the
 * ticket that comes with the situation, but only while its problem exists here (189): judged from
 * this practice before opening anything (a delivered one would have to open a revision first);
 * without those facts, from the ticket once opened (or, delivered, from one opened earlier).
 * Nothing to fix → the "nothing to fix" screen in the intro's place. Throws one plain sentence. */
// biome-ignore lint/suspicious/noExplicitAny: the engine's attempt is untyped JavaScript
export async function takeInPractice(a: any): Promise<void> {
  const known = knownTicket(a.id);
  if (known && a.backend?.status !== 'submitted') {
    go('engineer', engineerEntryId(a.id, known, 'same'));
    return;
  }
  let facts = practiceFacts(a);
  let fromPractice = fixNeedFromPractice(facts);
  if (fromPractice === null) {
    // Just after a page load the practice may not have been read from the server yet: read it
    // once before falling back to opening the ticket (which a delivered practice cannot do).
    const wb = (window as unknown as { PracticeLive?: { load(a: unknown): Promise<unknown> } })
      .PracticeLive;
    await wb?.load(a).catch(() => {});
    const now = ports?.current() ?? a;
    facts = practiceFacts(now);
    fromPractice = fixNeedFromPractice(facts);
  }
  if (fromPractice === 'clear') {
    go('engineer', ENGINEER_NOTHING_ID);
    return;
  }
  const delivered = (ports?.current() ?? a).backend?.status === 'submitted';
  const screens = await import('./screens');
  const transport = transportOf(a);
  if (delivered) {
    engineerEntryId(a.id, '', 'same');
    const earlier = fromPractice ? null : await screens.seededTicket(transport, a.id);
    const need = fixNeed(facts, earlier?.target_tests[0]);
    setHat(a.id, 'engineer');
    go('engineer', need === 'clear' ? ENGINEER_NOTHING_ID : ENGINEER_REVISE_ID);
    return;
  }
  const ticket = await screens.openTicket(transport, a.id, { from: 'seeded' });
  if (fixNeed(facts, ticket.target_tests[0]) === 'clear') {
    go('engineer', ENGINEER_NOTHING_ID);
    return;
  }
  go('engineer', engineerEntryId(a.id, ticket.id, 'same'));
}

/** Put on a hat from the top bar's switch (registered over the shell's default): the product
 * manager goes to the board; the engineer goes where `takeInPractice` says. */
async function switchHat(to: 'pm' | 'engineer') {
  const a = practiceNow();
  if (!a?.id) return;
  if (to === 'pm') {
    setHat(a.id, 'pm');
    go('work');
    return;
  }
  try {
    await takeInPractice(a);
  } catch (error) {
    toast(error instanceof Error ? error.message : String(error));
  }
}

/** The desk's last ticket as the shell remembers it (only real ticket ids count; a screen such as
 * `?nothing` or an intro's `?intro` suffix is not a ticket). */
export function knownTicket(sessionId: string): string | null {
  const t = lastTicket(sessionId);
  return t?.startsWith('ticket-') ? t.split('?')[0] : null;
}

const sessionNow = (): string | undefined => practiceNow()?.id ?? lastSession?.sessionId;
const run = (action: string) => (el: HTMLElement) => {
  const id = el.dataset.id || undefined;
  if (desk?.run(action, id)) return;
  // No desk on screen (a report, the product board): this practice's desk, at the right step.
  const sessionId = sessionNow();
  go('engineer', deskTarget(action, sessionId ? (knownTicket(sessionId) ?? undefined) : undefined));
};
registerActions({
  'hat-switch': (el) => switchHat(el.dataset.hat === 'engineer' ? 'engineer' : 'pm'),
  // A step on the engineer's scale: that step opens on the desk.
  'stage-engineer': (el) => {
    const step = el.dataset.step === 'sign' ? 'signoff' : el.dataset.step;
    if (desk?.run('engineer.step', step)) return;
    const sessionId = sessionNow();
    const ticket = sessionId ? knownTicket(sessionId) : null;
    go('engineer', ticket ? `${ticket}?step=${step}` : undefined);
  },
  'engineer.reproduce': run('engineer.reproduce'),
  'engineer.trial': run('engineer.trial'),
  'engineer.draft.open': run('engineer.draft.open'),
  'engineer.signoff.focus': run('engineer.signoff.focus'),
  'engineer.fix-again': run('engineer.fix-again'),
  // A review: on the product side it opens as a sheet over the board (S9); as the engineer, the
  // report page.
  'engineer.review.open': async (el) => {
    const id = el.dataset.id;
    if (!id) return;
    const a = practiceNow();
    const sessionId: string | undefined = a?.id ?? lastSession?.sessionId;
    if (sessionId && hatOf(sessionId) === 'pm') {
      const live = (
        window as unknown as {
          PracticeLive: {
            gatewayTransport(a: unknown): GatewayTransport;
            load(a: unknown): Promise<unknown>;
          };
        }
      ).PracticeLive;
      const transport = a?.id ? transportOf(a) : lastSession?.transport;
      if (!transport) return;
      const { openHandBackSheet } = await import('./hand-back-ui');
      openHandBackSheet({
        transport,
        sessionId,
        reviewId: id,
        // The board's own read (as a poll does): its configuration version follows at once.
        reread: a?.id === sessionId ? () => live.load(a) : undefined,
      });
      return;
    }
    go('engineer-review', id);
  },
  'engineer.hand-back': (el) => {
    // The practice the key belongs to (the desk writes it), else the one on screen.
    const sessionId = el.dataset.session || practiceNow()?.id || '';
    if (sessionId && el.dataset.id) handBack(sessionId, el.dataset.id);
  },
});

// Needs you: the Agent's draft (engineer hat) and reviews handed back (product hat).
registerSignals((attempt): Signal[] => {
  asked = attempt ?? asked;
  const sessionId: string | undefined = attempt?.id;
  if (!sessionId) return [];
  const out: Signal[] = [];
  const state = live.get(sessionId);
  const draft = state?.ticket.latest_draft;
  if (
    hatOf(sessionId) === 'engineer' &&
    draft &&
    draft.executor.kind !== 'human' &&
    !state?.ticket.reviews.some((r) => r.draft_id === draft.id)
  )
    out.push({
      id: `engineer-draft-${draft.id}`,
      source: 'agent',
      text: T('你的 Agent 交来一份草稿', 'Your agent handed in a draft'),
      action: { label: T('去签字单', 'Go to sign-off'), action: 'engineer.signoff.focus' },
      at: draft.created_at,
    });
  if (hatOf(sessionId) === 'pm')
    for (const [reviewId, back] of Object.entries(engineerLocal(sessionId).handedBack ?? {})) {
      const { kicker, text, tone } = handBackSignal(back);
      // `kicker` and `tone` are drawn by the board line (204); the shell's Signal type adds them later.
      out.push({
        id: `engineer-review-${reviewId}`,
        source: 'system',
        kicker,
        text,
        tone,
        action: {
          label: T('看报告', 'See the report'),
          action: 'engineer.review.open',
          id: reviewId,
        },
        dismissible: true,
        at: back.at,
      } as Signal);
    }
  return out;
});
