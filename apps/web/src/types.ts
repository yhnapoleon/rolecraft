export type RoleId = 'supervisor' | 'tech_lead' | 'business_lead';
export type Scenario = 'pm_pilot' | 'pm_pilot_urgent' | 'pm_pilot_capacity15';
export interface Pilot {
  participants: number;
  knowledge_domains: string[];
  launch_day: number;
  update_strategy: 'daily' | 'realtime' | 'manual_policy';
  fallback: 'human' | 'none';
  work_items: string[];
}
export interface World {
  session_id: string;
  version: number;
  logical_time: number;
  resources: Record<string, number>;
  configs: { pilot?: Pilot };
  material_versions: Record<string, number>;
  indexed_versions: Record<string, number>;
  applied_rules: string[];
  pending_requests: string[];
  action_count: number;
  config_version: number;
  status: 'active' | 'paused' | 'submitted';
}
export interface Material {
  id: string;
  version: number;
  title: string;
  content: string;
}
export interface TurnContext {
  task_id?: string;
  work_id?: string;
  attachments?: { type: 'work' | 'test'; id: string; version?: number }[];
}
export interface ApprovalDenial {
  id: string;
  rule_id: string;
  request_id: string;
  code: string;
  details: Record<string, any>;
  created_at?: string | null;
}
export interface Turn {
  text: string;
  status: string;
  role_id: RoleId;
  model_revision: string;
  as_of_seq: number;
  trace_id: string;
  created_at?: string | null;
  question?: string | null;
  context?: TurnContext;
}
export interface EventRecord {
  seq: number;
  event_type: string;
  actor_id: string;
  payload: Record<string, unknown>;
  created_at?: string | null;
}
export interface Timeline {
  events: EventRecord[];
  turns: Turn[];
  mode: string;
  approval_denials?: ApprovalDenial[];
}
export interface TestRun {
  id: string;
  query: string;
  answer: string;
  fallback: boolean;
  mode: string;
  citations: { material_id: string; version: number }[];
  source_versions: Record<string, number>;
  indexed_versions: Record<string, number>;
  config_version: number;
  as_of_seq: number;
  stale: boolean;
  created_at?: string | null;
}
// Browser-owned provenance. These fields never enter the backend TestRequest.
export interface TestRunOrigin {
  taskId: string | null;
  workId?: string;
  workRevision?: number;
  caseId?: string;
  caseRevision?: number;
  investigationId?: string;
  investigationRevision?: number;
  blockId?: string;
  blockRevision?: number;
  baselineRunId?: string;
  intent?: string;
  refs?: { id: string; version: number }[];
}
export interface LocalTestRun extends TestRunOrigin {
  sessionId: string;
  requestId: string;
  query: string;
  expectation: string;
  config: Pilot | null;
  createdAt: string;
}
export interface Deliverable {
  goal: string;
  owner: string;
  metrics: string;
  observation_window: string;
  exit_condition: string;
  rationale: string;
}
export interface Artifact {
  id: string;
  content: Deliverable;
  config_version: number;
  version: number;
  created_at?: string | null;
  as_of_seq?: number;
}
export interface Submission {
  id: string;
  artifact_id: string;
  config_version: number;
  as_of_seq: number;
  created_at?: string | null;
}
export interface Feedback {
  submission_id: string;
  as_of_seq: number;
  model_revision: string;
  summary: { status: string; lower: number | null; upper: number | null; coverage: number };
  items: {
    criterion_id: string;
    label: string;
    reason: string;
    evidence_ids: string[];
    review_required: boolean;
    completeness?: 'complete' | 'missing' | 'overflow';
  }[];
  overflow?: boolean;
  sources: Record<string, Record<string, unknown>>;
  practice: string[];
}
export interface Job {
  id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  attempt: number;
  result: Turn | Feedback | null;
  error: string | null;
  kind?: 'turn' | 'feedback';
  role_id?: RoleId | null;
  queued_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}
export type OperationKind =
  | 'action'
  | 'turn'
  | 'test'
  | 'artifact'
  | 'submission'
  | 'feedback'
  | 'approval'
  | 'relation';
export interface Operation {
  path: string;
  body: Record<string, unknown>;
  kind: OperationKind;
  label: string;
  created: string;
  jobId?: string;
  job?: Job;
  localExpected?: string;
  localRun?: LocalTestRun;
}
export interface LocalSession {
  /** Missing means the original v1 record; never infer protocol from URL or UI language. */
  protocol?: 1 | 2;
  v2NativeWorkspace?: true;
  v2ReadOnly?: boolean;
  v2Workspace?: { tasks: any[]; products: any[] };
  v2Domains?: string[];
  v2MaterialTitles?: Record<string, string>;
  v2Binding?: Extract<import('./v4-host').V4SessionBinding, { protocol: 2 }>;

  id: string;
  token: string;
  scenario: Scenario;
  created: string;
  world: World;
  materials: Material[];
  timeline: Timeline;
  draft: Deliverable;
  configDraft?: Pilot;
  tests: TestRun[];
  testNotes: Record<string, { expected: string; diagnosis: string }>;
  testRunMeta?: Record<string, LocalTestRun>;
  inputs: {
    question: string;
    expected: string;
    messages: Partial<Record<RoleId, string>>;
    capacityReason: string;
    resourceReason: string;
  };
  questions: Record<string, string>;
  artifact?: Artifact;
  submission?: Submission;
  feedback?: Feedback;
  pending?: Operation;
  failedTurn?: Operation;
  feedbackFailure?: Job;
  turnContexts?: Partial<Record<RoleId, TurnContext>>;
  approvalError?: { rule_id: string; code?: string; details?: Record<string, any>; error: string };
  relationResult?: Record<string, any>;
}
export interface Workspace {
  schema: 1;
  active?: string;
  sessions: LocalSession[];
}
