/** The engineer hat's scale and its one key, as plain data (plan §13.2).
 *
 * The shell's `registerStage('engineer', fn)` will take this as it is; until the shell lands, the
 * desk draws the key itself (top bar) and the step heads read the same states. Labels come as
 * [Chinese, English] pairs so the shell can pick by interface language. */
import type { ExperimentSummary, JsonValue, Settings, TicketDetail } from './model';

export type StepId = 'reproduce' | 'fix' | 'signoff';
export type StepState = 'done' | 'current' | 'todo';
type Pair = [zh: string, en: string];
export interface Stage {
  readonly steps: { id: StepId; label: Pair; state: StepState }[];
  readonly primary?: { label: Pair; action: string; id?: string; disabledReason?: Pair };
}
/** How a signed review came out: the target fixed and nothing newly failing, or not. */
export type ReviewOutcome = 'clean' | 'regressed';
export interface StageInput {
  /** The person's candidate: settings that differ from the baseline (field: value). */
  readonly candidate: Settings;
  /** Outcomes of reviews already read, by review ID. */
  readonly outcomes?: Readonly<Record<string, ReviewOutcome>>;
  /** Why the person's own candidate can't be run now (e.g. a value out of range). */
  readonly blocked?: Pair;
}

export const STEP_LABELS: Readonly<Record<StepId, Pair>> = {
  reproduce: ['复现', 'Reproduce'],
  fix: ['修复与试跑', 'Fix & trial'],
  signoff: ['签字', 'Sign off'],
};

const same = (a: JsonValue | undefined, b: JsonValue | undefined) => {
  if (Array.isArray(a) && Array.isArray(b))
    return JSON.stringify([...a].map(String).sort()) === JSON.stringify([...b].map(String).sort());
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
};
const sameKeys = (a: readonly string[], b: readonly string[]) =>
  a.length === b.length && a.every((k) => b.includes(k));

/** The settings a run tried, as field: value (values when the server gives them, else names). */
function triedFields(run: ExperimentSummary): readonly string[] {
  return run.changes ? Object.keys(run.changes) : (run.changed_fields ?? []);
}

/** Whether the person's candidate is other than what the latest trial ran. An untouched candidate
 * is not an edit: the Agent's trial does not write into the person's candidate. */
export function candidateEdited(candidate: Settings, trial: ExperimentSummary | undefined) {
  const keys = Object.keys(candidate);
  if (!keys.length || !trial) return false;
  if (!sameKeys(keys, triedFields(trial))) return true;
  if (!trial.changes) return false;
  return keys.some((k) => !same(candidate[k], trial.changes?.[k]?.after));
}

/** The draft holds the settings the latest trial ran (same configuration). */
function draftMatchesTrial(ticket: TicketDetail, trial: ExperimentSummary | undefined) {
  const draft = ticket.latest_draft;
  if (!draft || !trial) return false;
  if (draft.config_hash && trial.config_hash) return draft.config_hash === trial.config_hash;
  const keys = Object.keys(draft.changes);
  if (!sameKeys(keys, triedFields(trial))) return false;
  return (
    !trial.changes || keys.every((k) => same(draft.changes[k].after, trial.changes?.[k]?.after))
  );
}

export function engineerStage(ticket: TicketDetail, input: StageInput): Stage {
  const reproduced = ticket.trials.some((t) => t.kind === 'reproduce');
  const trials = ticket.trials.filter((t) => t.kind === 'trial');
  const trial = trials.at(-1);
  const draft = ticket.latest_draft;
  const edited = candidateEdited(input.candidate, trial);
  const matches = draftMatchesTrial(ticket, trial);
  const newerTrial = !!(trial && draft && trial.created_at > draft.created_at);
  const signedReview = draft ? ticket.reviews.find((r) => r.draft_id === draft.id) : undefined;
  const outcome = signedReview ? input.outcomes?.[signedReview.review_id] : undefined;

  const fixDone = !!trial && !!draft && matches && !edited;
  const signDone = fixDone && !!signedReview && outcome === 'clean';
  const steps: Stage['steps'] = [
    { id: 'reproduce', label: STEP_LABELS.reproduce, state: reproduced ? 'done' : 'current' },
    {
      id: 'fix',
      label: STEP_LABELS.fix,
      state: fixDone ? 'done' : reproduced ? 'current' : 'todo',
    },
    {
      id: 'signoff',
      label: STEP_LABELS.signoff,
      state: signDone ? 'done' : reproduced && fixDone ? 'current' : 'todo',
    },
  ];

  const reviewsLeft = ticket.review_budget.limit - ticket.review_budget.used;
  let primary: Stage['primary'];
  if (!reproduced)
    primary = { label: ['复现问题', 'Reproduce the problem'], action: 'engineer.reproduce' };
  else if (!trial || edited) {
    primary = { label: ['试跑', 'Run a trial'], action: 'engineer.trial' };
    if (ticket.experiment_budget.used >= ticket.experiment_budget.limit)
      primary.disabledReason = [
        `这份委托已经试满 ${ticket.experiment_budget.limit} 次。可以直接起草签字。`,
        `This ticket has used all ${ticket.experiment_budget.limit} runs. You can draft a sign-off now.`,
      ];
    else if (input.blocked) primary.disabledReason = input.blocked;
  } else if (!draft || (newerTrial && !matches)) {
    primary = { label: ['起草提交', 'Draft a sign-off'], action: 'engineer.draft.open' };
    if (ticket.draft_budget.used >= ticket.draft_budget.limit)
      primary.disabledReason = ['这份委托的草稿数已经用完。', 'This ticket has no drafts left.'];
  } else if (!signedReview) {
    primary = { label: ['去签字', 'Go to sign-off'], action: 'engineer.signoff.focus' };
    if (reviewsLeft <= 0)
      primary.disabledReason = [
        `这份委托的 ${ticket.review_budget.limit} 次复核已经用完。`,
        `This ticket’s ${ticket.review_budget.limit} reviews are used up.`,
      ];
  } else if (outcome === 'regressed')
    primary = { label: ['再修一轮', 'Fix it again'], action: 'engineer.fix-again' };
  else if (outcome === 'clean')
    primary = {
      label: ['交回产品经理', 'Back to the product manager'],
      action: 'engineer.hand-back',
      id: signedReview.review_id,
    };
  else
    primary = {
      label: ['看复核报告', 'See the review'],
      action: 'engineer.review.open',
      id: signedReview.review_id,
    };
  return { steps, primary };
}

/** Where an engineer action pressed away from the desk (a report, the board) opens the desk: this
 * practice's ticket at the step the action belongs to; without a known ticket, the desk finds one. */
export function deskTarget(action: string, ticketId: string | undefined): string | undefined {
  if (!ticketId) return undefined;
  const step: StepId =
    action === 'engineer.fix-again' || action === 'engineer.trial'
      ? 'fix'
      : action === 'engineer.reproduce'
        ? 'reproduce'
        : 'signoff';
  return `${ticketId}?step=${step}`;
}
