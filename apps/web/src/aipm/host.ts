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
/** design/evaluation: phase-1 panels. worksheet (L2) and review (L3) fill the main screen in v2. */
export type AipmFeatureId = 'design' | 'evaluation' | 'worksheet' | 'review';
export type AipmStepId =
  | 'business'
  | 'stakeholders'
  | 'need'
  | 'boundary'
  | 'solution'
  | 'assurance'
  | 'decision';
/** A worksheet: one of the seven steps, or a free sheet (a plain work product). */
export type AipmSheetId = AipmStepId | `free:${string}`;
export type AipmColleague = 'manager' | 'business' | 'technical';
/** What the main screen shows (v2 §3.2). The workbench is the practice's board. */
export type AipmScreen =
  | { kind: 'workbench'; sheet?: undefined; step?: undefined }
  | { kind: 'worksheet'; sheet: AipmSheetId; material?: string; step?: undefined }
  | { kind: 'review'; step: AipmStepId; reviewRef?: ObjectRef; sheet?: undefined };
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
  /* ---------- v2 main screen (spec §3.2, §10 L1) ---------- */
  /** What the main screen shows now; a mounted worksheet or review reads its target here. */
  currentScreen(): AipmScreen;
  /** Opens that worksheet in the main screen (the worksheet feature remounts per sheet). */
  openWorksheet(sheet: AipmSheetId): void;
  /** Opens a material beside the open worksheet (two columns); alone when the screen is narrow. */
  openMaterialSplit(materialId: string): void;
  /** Shows a section review (L3's feature) for that step; without a ref, its latest one. */
  openReview(step: AipmStepId, reviewRef?: ObjectRef): void;
  openWorkbench(): void;
  /** Opens that colleague's conversation with the message prefilled (never sent for the person).
   * attachPrd defaults to true when that colleague has not been shared the latest PRD version. */
  askColleague(input: {
    colleague: AipmColleague;
    prefill: string;
    attachPrd?: boolean;
  }): Promise<void>;
}
