/** Operation-specific public host DTOs. Wire models come from the frozen schema generator. */
import type * as C from './contracts-v2';
import type { SemanticStatus, V4SessionBinding } from './v4-host';

type Empty = Record<string, never>;
export type PageInput = { cursor?: number; limit?: number; since_seq?: number; as_of_seq?: number };
export type Page<T> = { items: T[]; as_of: C.VersionPoint; next_cursor?: number | null };
export type AssistantAnswerMode = {
  mode: 'extractive' | 'llm' | 'unavailable' | 'failed' | 'gate';
  provider: string | null;
  model_revision: string | null;
  config_version: number;
};
export type PublicObject = {
  schema_version?: 2;
  ref: C.ObjectRef;
  content: Record<string, C.JsonValue>;
  /** Present on test objects: the mode saved with that answer. */
  assistant?: AssistantAnswerMode;
  /** objects.read of a test run or work version: the exact citation feedback verifies. */
  evidence_ref?: C.EvidenceRefV2;
};
export type Timeline = {
  as_of: C.VersionPoint;
  objects: PublicObject[];
  events?: Required<C.PublicEvent>[];
  role_mode: 'local_reference' | 'model' | 'unavailable';
  workspace?: {
    resources: Record<string, number>;
    source_versions: Record<string, number>;
    indexed_versions: Record<string, number>;
    config: Required<C.AssistantConfig>;
    /** The configuration the next assistant test uses (saved settings within approved resources). */
    effective_config?: C.EffectiveConfig;
    material_titles: Record<string, string>;
  };
};
export type MaterialPage = {
  materials: C.MaterialMetadata[];
  requested_as_of_seq: number;
  retrieved_at: C.VersionPoint;
  next_cursor: number | null;
  catalog_is_not_acquired_knowledge: true;
};
export type WorkbenchContext = {
  session: Extract<V4SessionBinding, { protocol: 2 }>;
  state: C.PublicState;
  as_of: C.VersionPoint;
  read_only: boolean;
  available: Record<string, boolean>;
  semantic: Record<'roles' | 'feedback' | 'assistant', SemanticStatus>;
  timeline: Timeline & { workspace: NonNullable<Timeline['workspace']> };
  materials: MaterialPage;
  configuration_domains?: string[];
};
export type FeedbackRecord = {
  feedback: C.FeedbackV2;
  sections: Record<
    'verified_facts' | 'historical_responsibilities' | 'rule_items' | 'provenance',
    'recorded' | 'not_recorded'
  >;
};
export type DelegationPage = Omit<C.DelegationListPage, 'items'> & {
  items: (C.DelegationSummary & { agent_label?: string })[];
};

export interface V4Queries {
  'aipm.progress': { input: Empty; output: import('./aipm/types').AipmProgress };
  'session.read': { input: Empty; output: C.PublicState };
  'workbench.read': { input: PageInput; output: WorkbenchContext };
  'materials.list': { input: PageInput; output: MaterialPage };
  timeline: { input: PageInput; output: Timeline };
  'tests.list': { input: PageInput; output: { tests: C.TestResultV2[] } };
  'submissions.list': { input: PageInput; output: Page<C.SubmissionV2> };
  /** Read-only: the rule items submitting this input now would give. Nothing is saved. */
  'submissions.rule_check': { input: C.SubmitInput; output: C.SubmissionRuleCheck };
  /** Read-only, recognition layer (demo edition, outside the contract): the sentence labels of
   * the work this input would submit; `enabled` is false when the layer is off. */
  'submissions.rule_check.recognition': {
    input: C.SubmitInput;
    output: { session_id: string; enabled: boolean; recognition: { [key: string]: unknown } | null };
  };
  /** Read-only: a saved submission checked again at its own point. */
  'submissions.rule_check.read': {
    input: { submission_id: string };
    output: C.SubmissionRuleCheck;
  };
  'work_items.list': { input: PageInput; output: Page<C.WorkspaceTask> };
  'work_products.list': { input: PageInput; output: C.WorkspaceProductPage };
  'work_products.versions.list': {
    input: PageInput & { product_id: string };
    output: C.WorkspaceProductPage;
  };
  'work_products.shares.list': {
    input: PageInput & { product_id: string };
    output: C.WorkspaceSharePage;
  };
  'workspace_imports.list': { input: PageInput; output: Page<C.WorkspaceImportReceipt> };
  'workspace_imports.read': {
    input: PageInput & { import_id: string };
    output: Page<C.WorkspaceImportReceipt>;
  };
  workspace_imports: { input: C.WorkspaceImport & { mode: 'preview' }; output: C.ImportResult };
  observation: { input: PageInput; output: C.Observation };
  tools: { input: PageInput; output: { tools: C.ToolSchema[] } };
  'delegations.list': { input: PageInput; output: DelegationPage };
  agent_activity: { input: { after?: number }; output: C.AgentActivityPage };
  'objects.read': {
    input: Omit<C.ObjectRef, 'session_id'> & { session_id?: string };
    output: PublicObject;
  };
  'feedback.read': {
    input: { submission_id: string } | { review_id: string };
    output: Page<C.FeedbackV2>;
  };
  'feedback.records.read': { input: { feedback_id: string }; output: FeedbackRecord };
  'feedback.responses.list': {
    input: PageInput & { feedback_id: string };
    output: Page<C.FeedbackResponseRecord>;
  };
  'feedback.responses.read': {
    input: { response_id: string };
    output: Page<C.FeedbackResponseRecord>;
  };
  'reviews.read': { input: PageInput & { review_id?: string }; output: Page<C.ReviewRequest> };
}
export type ObjectResult<T> = { object: T; ref: C.ObjectRef; as_of: C.VersionPoint };
export type ScenarioActionResult = {
  config?: C.AssistantConfig;
  request?: C.ObjectRef;
  request_data?: C.BusinessRequest;
  material?: { id: string; version: number };
  fragments?: Omit<C.DisclosedFragment, 'fact_ids'>[];
  read_at?: C.VersionPoint;
};
export type QueuedResult = { status?: 'queued'; queued_jobs?: string[] };
export type SettingsInput = {
  base: C.ObjectRef;
  settings: Partial<
    Pick<
      C.AssistantConfig,
      | 'participants'
      | 'domains'
      | 'launch_day'
      | 'update_strategy'
      | 'fallback'
      | 'work_items'
      | 'scope_filter'
      | 'freshness_guard'
      | 'manual_domains'
      | 'prohibited_topics'
      | 'min_score'
      | 'retrieval_limit'
      | 'chunk_size'
    >
  >;
};
export interface V4Commands {
  'configuration.apply': { input: SettingsInput; output: { config: C.AssistantConfig } };
  actions: { input: C.ActionInput; output: ScenarioActionResult };
  'tests.create': { input: C.TestRequestV2; output: { test: C.TestResultV2 } };
  'turns.create': {
    input: C.TurnInput;
    output: QueuedResult & {
      turn: C.ObjectRef;
      question: string;
      role_id: string;
      executor: C.Executor;
    };
  };
  'turns.display': {
    input: C.ObjectRead;
    output: { display: C.ObjectRef; disclosures: C.PublicDisclosureRecord[] };
  };
  'approvals.resolve': { input: C.ApprovalInput; output: { decision: C.BusinessDecision } };
  'submissions.create': {
    input: C.SubmitInput;
    output: QueuedResult & { submission: C.ObjectRef; feedback_status: 'queued' | 'not_installed' };
  };
  'reviews.create': {
    input: C.ReviewInput;
    output: QueuedResult & { review: C.ObjectRef; feedback_status: 'queued' | 'not_installed' };
  };
  'feedback.responses.create': {
    input: C.FeedbackResponseCreate;
    output: { response: C.ObjectRef; feedback: C.ObjectRef; evidence_status: string };
  };
  'feedback.create': { input: C.FeedbackInput; output: QueuedResult & { subject: C.ObjectRef } };
  begin_revision: { input: C.BeginRevisionInput; output: { cycle: C.ObjectRef } };
  revision_cycles: { input: C.BeginRevisionInput; output: { cycle: C.ObjectRef } };
  'work_items.create': { input: C.TaskCreate; output: ObjectResult<C.WorkspaceTask> };
  'work_items.update': { input: C.TaskPatch; output: ObjectResult<C.WorkspaceTask> };
  'work_items.batch': {
    input: C.TaskBatch;
    output: { objects: C.WorkspaceTask[]; refs: C.ObjectRef[]; as_of: C.VersionPoint };
  };
  'aipm.step_links.save': {
    input: import('./aipm/types').StepLinkInput;
    output: { ref: C.ObjectRef; link: C.JsonValue };
  };
  'work_products.create': { input: C.ProductCreate; output: ObjectResult<C.WorkProductVersion> };
  'work_products.versions.create': {
    input: C.ProductEdit;
    output: ObjectResult<C.WorkProductVersion>;
  };
  'work_products.adopt': { input: C.ProductAdopt; output: ObjectResult<C.WorkProductVersion> };
  'work_products.shares.create': { input: C.ShareCreate; output: ObjectResult<C.ProductShare> };
  'work_products.shares.change': { input: C.ShareUpdate; output: ObjectResult<C.ProductShare> };
  workspace_imports: { input: C.WorkspaceImport & { mode: 'apply' }; output: C.ImportResult };
  'delegations.create': { input: C.DelegationInput; output: { delegation: C.DelegationGrant } };
  'delegations.revoke': {
    input: C.DelegationRevoke;
    output: { delegation_id: string; revoked: true };
  };
  'jobs.refresh': { input: { job_id: string }; output: { refreshed_job: string } };
}
export type V4Query = keyof V4Queries;
export type V4Command = keyof V4Commands;
export type QueryInput<K extends V4Query> = Readonly<V4Queries[K]['input']>;
export type QueryOutput<K extends V4Query> = V4Queries[K]['output'];
export type QueryArguments<K extends V4Query> =
  Empty extends QueryInput<K> ? [input?: QueryInput<K>] : [input: QueryInput<K>];
export type ReadonlyInput<T> = T extends object
  ? { readonly [K in keyof T]: ReadonlyInput<T[K]> }
  : T;
export type CommandInput<K extends V4Command> = ReadonlyInput<V4Commands[K]['input']>;
export type CommandOutput<K extends V4Command> = V4Commands[K]['output'];
export type CommandFailure = {
  code?: string;
  message?: string;
  definitive?: boolean;
  serverAbsent?: boolean;
};
/** Initial commands and recovered requests have intentionally distinct result shapes. */
export type HostResult = Record<string, C.JsonValue> | null;
export type RecoveryResult =
  | C.RequestResult
  | CommandOutput<'delegations.create' | 'delegations.revoke'>
  | CommandFailure
  | null;
