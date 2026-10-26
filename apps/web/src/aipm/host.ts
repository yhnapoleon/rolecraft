/** G0 UI seam. L4 owns wire DTOs and the client; the host owns explicit user actions.
 * TProgress/TClient let consumers use L4's exact types without copying them here. */
import type {
  ObjectRef,
  ProductCreate,
  ProductEdit,
  ReviewInput,
  VersionPoint,
} from '../contracts-v2';
import type { V4HostAdapter, WorkLanguage } from '../v4-host';

export type AipmSessionContext = {
  sessionId: string;
  workLanguage: WorkLanguage;
  scenarioHash: string;
  asOf: VersionPoint | null;
  readOnly: boolean;
};
export type AipmFeatureId = 'design' | 'evaluation';
export type AipmContentId = 'company' | 'guide' | 'patterns' | 'design' | 'evaluation';
export type AipmFeature = {
  render(): string;
  mount?(root: HTMLElement): undefined | (() => void);
};
export interface AipmHost<TProgress = unknown, TClient = unknown> {
  getSessionContext(): AipmSessionContext | null;
  /** Existing authenticated data host; components never assemble authorization headers. */
  getDataHost(): V4HostAdapter | null;
  getClient(): TClient | null;
  readProgress(): Promise<TProgress>;
  readGuide(): Promise<unknown>;
  /** The published `public/<id>.<work language>.json` of this experience; rejects when this
   * build does not carry it. */
  readContent(id: AipmContentId): Promise<unknown>;
  /** Explicit writes. The host journals the exact Command before calling the L4 client. */
  command(operation: string, payload: Record<string, unknown>): Promise<unknown>;
  recover(requestId: string): Promise<unknown>;
  /** Sends a `tests.create` Command the caller already persisted, byte for byte: same request_id,
   * no new journal entry, no retry. Used by L3's batches so a resumed case never runs twice. */
  sendPreparedTest(command: Record<string, unknown>): Promise<unknown>;
  openMaterial(id: string): Promise<void>;
  openWork(ref?: ObjectRef): Promise<void>;
  /** Prefill only. Sending remains a separate user action. */
  openColleague(role: 'manager' | 'business' | 'technical', question?: string): Promise<void>;
  openSettings(): Promise<void>;
  requestReview(input: ReviewInput): Promise<unknown>;
  createWorkVersion(input: ProductCreate | ProductEdit): Promise<unknown>;
  refresh(): Promise<void>;
  registerFeature(id: AipmFeatureId, feature: AipmFeature): () => void;
  openFeature(id: AipmFeatureId): void;
}
