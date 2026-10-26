/** One transport, one server projection. The host owns credentials and pending commands. */
import type { AipmGuide, AipmProgress, FeedbackDiscovery, ProcessFeedback, VersionPoint } from './types';
import type { Command } from '../features/workspace/contract-types';

export type AipmTransport = (path: string, body?: unknown, method?: string) => Promise<unknown>;
export type ProcessFeedbackPage = { items: ProcessFeedback[]; as_of: VersionPoint; next_cursor: number | null; complete: boolean };
export class AipmClient {
  constructor(readonly sessionId: string, private readonly transport: AipmTransport) {}
  private path(suffix: string) { return `/sessions/${encodeURIComponent(this.sessionId)}/aipm/${suffix}`; }
  private async read<T>(suffix: string): Promise<T> {
    const response = await this.transport(this.path(suffix), undefined, 'GET') as { result: { result: T } };
    return response.result.result;
  }
  private write(suffix: string, operation: string, command: Command): Promise<unknown> {
    if (command.operation !== operation) throw new Error('operation_route_mismatch');
    // No retry, automatic adoption, enrollment on restore, or replacement request_id.
    return this.transport(this.path(suffix), command, 'POST');
  }
  guide = () => this.read<AipmGuide>('guide');
  progress = () => this.read<AipmProgress>('progress');
  processFeedback = (cursor = 0, limit = 20) => this.read<ProcessFeedbackPage>(`process-feedback?cursor=${cursor}&limit=${limit}`);
  submissionFeedback = (id: string, version: number) => this.read<FeedbackDiscovery>(`submissions/${encodeURIComponent(id)}/versions/${version}/feedback`);
  enroll = (command: Command) => this.write('enrollment', 'aipm.enroll', command);
  setFocus = (command: Command) => this.write('focus', 'aipm.focus.set', command);
  saveStepLink = (command: Command) => this.write('step-links', 'aipm.step_links.save', command);
  saveDesign = (command: Command) => this.write('designs', 'aipm.design.save', command);
  readDesign = <T>(id: string) => this.read<T>(`designs/${encodeURIComponent(id)}`);
  createBatch = (command: Command) => this.write('batches', 'aipm.batch.create', command);
  updateBatch = (id: string, command: Command) => this.write(`batches/${encodeURIComponent(id)}/state`, 'aipm.batch.update', command);
  readBatch = <T>(id: string) => this.read<T>(`batches/${encodeURIComponent(id)}`);
  recordAssessment = (command: Command) => this.write('assessments', 'aipm.assessment.record', command);
}
export const createAipmClient = (sessionId: string, transport: AipmTransport) => new AipmClient(sessionId, transport);
