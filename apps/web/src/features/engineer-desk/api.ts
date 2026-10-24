/** The engineer operations of one practice session (`/sessions/{sid}/engineer/...`, kept out of the
 * public OpenAPI; shapes from `src/career_lab/engineer/session.py`). Writes use the standard command
 * envelope; the engineer operations do not check its version point, but it is filled in from the
 * session's current state like every other write. */
import { ApiError } from '../../api';
import type { AssistantConfig } from '../../contracts-v2';
import type { GatewayTransport } from '../../gateway-transport';
import type { SettingsInput } from '../../v4-host-operations';
import { engineerErrorText } from './copy';
import type {
  DraftInput,
  DraftView,
  Experiment,
  ReviewSummary,
  Settings,
  TicketDetail,
} from './model';
import type { EngineerReviewRecord } from '../engineer-report';

export type TicketSource = { from: 'seeded' } | { from: 'tests'; test_ids: readonly string[] };
export interface SignResult {
  readonly signoff: { readonly review_id: string; readonly already_signed: boolean };
  readonly review: EngineerReviewRecord;
  readonly review_budget: { readonly used: number; readonly limit: number };
}

type Wrapped<T> = { result: T };
type WorkbenchRead = { timeline?: { workspace?: { config?: unknown } } };

export function engineerApi(transport: GatewayTransport, sessionId: string) {
  const base = `/sessions/${encodeURIComponent(sessionId)}`;
  const ticketPath = (id: string) => `${base}/engineer/tickets/${encodeURIComponent(id)}`;
  async function read<T>(path: string): Promise<T> {
    return ((await transport(path)) as Wrapped<T>).result;
  }
  async function command<T>(path: string, operation: string, payload: object): Promise<T> {
    const { state } = (await transport(base)) as {
      state: { business_seq: number; workspace_revision: number };
    };
    const body = {
      schema_version: 2,
      request_id: crypto.randomUUID(),
      expected_version: state.business_seq,
      expected_workspace_revision: state.workspace_revision,
      operation,
      payload,
    };
    return ((await transport(path, body)) as Wrapped<T>).result;
  }
  return {
    createTicket: (source: TicketSource) =>
      command<{ ticket: TicketDetail; created: boolean }>(
        `${base}/engineer/tickets`,
        'engineer.tickets.create',
        source,
      ),
    tickets: async () =>
      (
        await read<{
          tickets: { id: string; created_at: string; title: string; source: string }[];
        }>(`${base}/engineer/tickets`)
      ).tickets,
    ticket: async (id: string) => (await read<{ ticket: TicketDetail }>(ticketPath(id))).ticket,
    reproduce: async (id: string) =>
      (
        await command<{ reproduction: Experiment }>(
          `${ticketPath(id)}/reproductions`,
          'engineer.reproduce',
          { ticket_id: id },
        )
      ).reproduction,
    trial: async (id: string, changes: Settings) =>
      (
        await command<{ trial: Experiment }>(`${ticketPath(id)}/trials`, 'engineer.trial', {
          ticket_id: id,
          changes,
        })
      ).trial,
    draft: async (id: string, input: DraftInput) =>
      (
        await command<{ draft: DraftView }>(
          `${ticketPath(id)}/drafts`,
          'engineer.submissions.draft',
          { ticket_id: id, ...input },
        )
      ).draft,
    sign: (id: string, draftId: string, impactNote: string) =>
      command<SignResult>(`${ticketPath(id)}/signoffs`, 'engineer.submissions.sign', {
        ticket_id: id,
        draft_id: draftId,
        impact_note: impactNote,
      }),
    /** The practice's state: 'active', or 'submitted' once delivered. */
    status: async () => ((await transport(base)) as { state: { status: string } }).state.status,
    /** The latest delivery of the practice, as the reference a revision starts from. */
    latestSubmission: async () => {
      const value = (await transport(`${base}/submissions`)) as {
        result: {
          items?: { id: string; version: number }[];
          result?: { items?: { id: string; version: number }[] };
        };
      };
      const items = value.result.result?.items ?? value.result.items ?? [];
      const last = items.at(-1);
      return last
        ? { session_id: sessionId, kind: 'submission', object_id: last.id, version: last.version }
        : null;
    },
    /** Reopen a delivered practice (a revision): the delivery and its feedback stay. */
    beginRevision: (
      parent: { session_id: string; kind: string; object_id: string; version: number },
      reason: string,
    ) =>
      command<{ cycle: unknown }>(`${base}/revision-cycles`, 'begin_revision', {
        parent_submission: parent,
        reason,
      }),
    /** The pilot's configuration as it is now (the workbench read). */
    pilotConfig: async () => {
      const value = (await transport(`${base}/workbench`)) as {
        result: { result?: WorkbenchRead } & WorkbenchRead;
      };
      const read = value.result.result ?? value.result;
      return (read.timeline?.workspace?.config ?? null) as AssistantConfig | null;
    },
    /** The product manager's update of the pilot (existing configuration.apply). */
    applyConfig: (input: SettingsInput) =>
      command<{ config: AssistantConfig }>(`${base}/configuration`, 'configuration.apply', input),
    reviews: async (ticketId: string) =>
      (
        await read<{ reviews: (ReviewSummary & { ticket_id: string })[] }>(
          `${base}/engineer/reviews?ticket_id=${encodeURIComponent(ticketId)}`,
        )
      ).reviews,
    review: async (reviewId: string) =>
      (
        await read<{ review: EngineerReviewRecord }>(
          `${base}/engineer/reviews/${encodeURIComponent(reviewId)}`,
        )
      ).review,
  };
}
export type EngineerApi = ReturnType<typeof engineerApi>;

/** Any failure as one plain sentence: a known refusal by its code, anything else generally. */
export function failureText(error: unknown): string {
  return engineerErrorText(error instanceof ApiError ? error.code : undefined);
}
