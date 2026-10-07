/** v4 host contract for module-owned native slots. This declares the seam;
 * it does not provide a mock runtime, credentials or another application root. */
import type { ObjectRef, EvidenceRefV2, VersionPoint } from './features/workspace/contract-types';

export type WorkLanguage = 'zh' | 'en';
export type V4SessionBinding =
  | { protocol: 1; sessionId: string; workLanguage: WorkLanguage | null }
  | { protocol: 2; sessionId: string; workLanguage: WorkLanguage; scenarioHash: string };

export interface V4HostSnapshot {
  session: V4SessionBinding | null;
  uiLanguage: WorkLanguage;
  state: 'active' | 'paused' | 'submitted' | 'unavailable';
  asOf: VersionPoint | null;
  currentTask: ObjectRef | null;
  currentProduct: ObjectRef | null;
  busy: boolean;
  storageError: boolean;
  /** Exact public operation availability, refreshed from the server. */
  available: Readonly<Record<string, boolean>>;
}

export interface V4CommandResult {
  requestId: string;
  status: 'confirmed' | 'pending' | 'failed' | 'needs_context' | 'unconfirmed';
  /** Public server response; the module validates its owned DTO. */
  result: unknown;
}

export interface V4HostAdapter {
  snapshot(): Readonly<V4HostSnapshot>;
  subscribe(changed: () => void): () => void;
  /** Read only, within the bound session and current authorization. */
  query(operation: string, input?: Readonly<Record<string, unknown>>): Promise<unknown>;
  /** Domain input only: no token, raw URL, request key or guessed next version.
   * The host owns the single exact Command journal and server version binding. */
  command(operation: string, input: Readonly<Record<string, unknown>>): Promise<V4CommandResult>;
  /** Read the existing journal/request. Never imply a new model invocation. */
  recover(requestId: string): Promise<V4CommandResult>;
  /** Separate explicit user action; persists a fresh attempt record. */
  retry(requestId: string): Promise<V4CommandResult>;
  draft<T>(slot: V4SlotId, key: string): T | undefined;
  keepDraft<T>(slot: V4SlotId, key: string, value: T): Promise<void>;
  flushDrafts(): Promise<void>;
  openReference(ref: ObjectRef | EvidenceRefV2): Promise<void>;
  chooseEvidence(): Promise<readonly EvidenceRefV2[]>;
  selectTask(ref: ObjectRef): void;
  selectProduct(ref: ObjectRef): void;
  announce(message: string, kind?: 'status' | 'error'): void;
}

export type V4SlotId = 'workspace' | 'roles' | 'resource-requests' | 'feedback' | 'agent';
export interface V4SlotHandle {
  /** Refresh only the provided nodes; do not replace host inputs with unsaved text. */
  update(snapshot: Readonly<V4HostSnapshot>): void;
  /** Unsubscribe and detach listeners only; no implicit business action. */
  destroy(): void;
}

export interface V4SlotContext {
  host: V4HostAdapter;
  /** Only the DOM nodes assigned in the v4 container agreement. */
  nodes: Readonly<Record<string, HTMLElement>>;
  surface?: 'submission' | 'feedback';
}
export type MountV4Slot = (context: V4SlotContext) => V4SlotHandle;
