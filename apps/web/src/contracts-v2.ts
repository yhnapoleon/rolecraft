// Generated from frozen manifest SHA256 f9edfe270e6bb39ef3661061ca37be65827bb99cae96a1ca4abadea736e53952. Do not edit.
// Includes the approved optional FeedbackV2 provenance extension.
export type ActionBoundary = {
  end_seq: number;
  request_id: string;
  schema_version?: 2;
  start_seq: number;
  storage_revision: number;
  transaction_id: string;
};
export type ActionInput = {
  config?: AssistantConfig | null;
  evidence_refs?: EvidenceRefV2[];
  material?: ObjectRef | null;
  reason?: string;
  request?: ObjectRef | null;
  schema_version?: 2;
  terms?: Record<string, number>;
  tool:
    | 'apply_config'
    | 'refresh_index'
    | 'request_business'
    | 'accept_counteroffer'
    | 'pause'
    | 'resume'
    | 'read_material';
};
export type Adoption = {
  adopted_at?: string | null;
  adopter?: Executor | null;
  schema_version?: 2;
  status?: 'unadopted' | 'adopted' | 'rejected';
};
export type ApprovalInput = {
  expected_request_revision: number;
  request: ObjectRef;
  schema_version?: 2;
};
export type AssistantConfig = {
  chunk_size?: number;
  config_version?: number;
  domains: string[];
  fallback?: 'human' | 'none';
  freshness_guard?: 'none' | 'warn' | 'fallback';
  id: string;
  launch_day?: number;
  manual_domains?: string[];
  min_score?: number;
  min_score_calibration?: FileRef | null;
  participants?: number;
  prohibited_topics?: string[];
  retrieval_limit?: number;
  schema_version?: 2;
  scope_filter?: boolean;
  session_id: string;
  update_strategy?: 'daily' | 'realtime' | 'manual_policy';
  version?: number;
  work_items?: string[];
};
export type BeginRevisionInput = {
  parent_submission: ObjectRef;
  reason: string;
  schema_version?: 2;
};
export type Budget = {
  actions: number;
  currency_limit?: number | null;
  model_calls: number;
  schema_version?: 2;
  tokens?: number | null;
  wall_seconds: number;
};
export type BusinessBasis = {
  based_on?: ObjectRef | null;
  config: AssistantConfig;
  config_ref?: ObjectRef | null;
  content_hash: string;
  mode: 'proposed' | 'applied';
  schema_version?: 2;
};
export type BusinessDecision = {
  as_of: VersionPoint;
  countered?: Record<string, number>;
  decider: string;
  evidence_refs?: EvidenceRefV2[];
  granted?: Record<string, number>;
  id: string;
  reason: string;
  reason_code: string;
  request: ObjectRef;
  rule_revision: string;
  schema_version?: 2;
  session_id: string;
  status: 'approved' | 'rejected' | 'countered' | 'accepted';
  version: number;
};
export type BusinessRequest = {
  as_of: VersionPoint;
  basis: BusinessBasis;
  evidence_refs?: EvidenceRefV2[];
  executor: Executor;
  id: string;
  previous_request?: ObjectRef | null;
  reason: string;
  requested: Record<string, number>;
  schema_version?: 2;
  session_id: string;
  status?: 'pending' | 'approved' | 'rejected' | 'countered' | 'accepted' | 'withdrawn';
  version: number;
};
export type CodeIdentity = {
  status?: 'clean' | 'modified' | 'not_recorded';
  commit?: string | null;
  snapshot?: string | null;
};
export type Command = {
  expected_version: number;
  expected_workspace_revision: number;
  operation: string;
  payload?: Record<string, JsonValue>;
  request_id: string;
  schema_version: 2;
};
export type DelegationGrant = {
  actor_id: string;
  allowed_actions?: string[] | null;
  allowed_objects?: string[] | null;
  capabilities?: ('read' | 'act' | 'submit')[];
  create_under_tasks?: string[];
  executor: Executor;
  expires_at: string;
  id: string;
  revoked?: boolean;
  schema_version?: 2;
  session_id: string;
};
export type DelegationInput = {
  agent_label: string;
  allowed_actions?: string[] | null;
  allowed_objects?: string[] | null;
  capabilities?: ('read' | 'act' | 'submit')[];
  create_under_tasks?: string[];
  expires_at: string;
  schema_version?: 2;
};
export type DelegationListPage = {
  checked_at: string;
  complete?: true;
  items: DelegationSummary[];
  next_cursor?: null;
  schema_version?: 2;
};
export type DelegationListResult = { result: DelegationListPage; schema_version?: 2 };
export type DelegationRevoke = { delegation_id: string; schema_version?: 2 };
export type DelegationSummary = {
  allowed_actions: string[] | null;
  allowed_objects: string[] | null;
  capabilities: string[];
  create_under_tasks: string[];
  effective_status: 'active' | 'expired' | 'revoked';
  executor: Executor;
  expires_at: string | null;
  id: string;
  revoked: boolean;
  session_id: string;
};
export type DisclosedFragment = {
  channel: string;
  fact_ids?: string[];
  ref: EvidenceRefV2;
  schema_version?: 2;
  text: string;
  verification?: 'unverified' | 'model_extracted' | 'verified' | 'rejected';
};
export type EffectiveConfig = {
  differences?: Record<string, string>;
  effective: AssistantConfig;
  requested: AssistantConfig;
  schema_version?: 2;
};
export type EvidenceRefV2 = {
  config_version?: number | null;
  kind: string;
  object_id: string;
  observed_at_seq: number;
  quote?: string | null;
  schema_version?: 2;
  session_id: string;
  span_end?: number | null;
  span_start?: number | null;
  valid_from_seq?: number;
  valid_until_seq?: number | null;
  version: number;
};
export type Executor = {
  delegation_id?: string | null;
  id: string;
  kind: 'human' | 'external_agent' | 'reference_agent' | 'system';
  schema_version?: 2;
};
export type FeedbackActivity = {
  schema_version?: 2;
  kind: 'material_read' | 'test_run' | 'question_sent' | 'reply_received' | 'learner_displayed';
  ref: EvidenceRefV2;
  occurred_at: VersionPoint;
  executor: Executor;
  actor_id: string;
  target?: ObjectRef | null;
  counterparty?: string | null;
};
export type FeedbackActivityCount = {
  schema_version?: 2;
  status?: 'complete' | 'unknown';
  count?: number | null;
  verified_records?: number;
};
export type FeedbackActivityWindow = {
  schema_version?: 2;
  covered_from: VersionPoint;
  covered_through: VersionPoint;
  captured_at: VersionPoint;
};
export type FeedbackInput = { retry?: boolean; schema_version?: 2; subject: ObjectRef };
export type FeedbackItem = {
  schema_version?: 2;
  criterion: string;
  label: 'MET' | 'PARTIAL' | 'NOT_MET' | 'INSUFFICIENT' | 'NOT_APPLICABLE';
  applicability: 'applicable' | 'not_applicable' | 'undetermined';
  source: 'verified_rule' | 'model_advice' | 'pending';
  explanation: string;
  citations: EvidenceRefV2[];
  rule_bound?: RuleBound | null;
};
export type FeedbackProvenance = {
  code: CodeIdentity;
  evaluation_version: string;
  rules_version: string;
  prompt_version: string;
  provider: string;
  model: string;
  retries?: 0;
  registered_model?: RegisteredModelIdentity | null;
};
export type FeedbackReadBoundary = {
  schema_version?: 2;
  path: string;
  content_hash: string;
  dependencies: ObjectRef[];
  attestation?: 'common_store_trace_v1';
};
export type FeedbackReferenceCheck = {
  schema_version?: 2;
  submitted_reference_hash: string | null;
  status:
    | 'exact_reference_verified'
    | 'unavailable'
    | 'future_evidence'
    | 'evidence_version_mismatch'
    | 'evidence_quote_mismatch'
    | 'evidence_time_mismatch'
    | 'source_time_unknown';
  verified_ref?: EvidenceRefV2 | null;
  valid_at_subject?: boolean | null;
  semantic_support?: 'not_established';
};
export type FeedbackResponseCreate = {
  criterion?: string | null;
  evidence?: EvidenceRefV2[];
  feedback_id: string;
  feedback_version: number;
  kind: 'objection' | 'supplement';
  schema_version?: 2;
  section?:
    | 'general'
    | 'verified_facts'
    | 'historical_responsibilities'
    | 'rule_items'
    | 'model_advice';
  text: string;
};
export type FeedbackResponseRecord = {
  criterion?: string | null;
  evidence?: EvidenceRefV2[];
  evidence_status?: 'none_submitted' | 'user_submitted_unverified' | null;
  executor: Executor;
  feedback: ObjectRef;
  id: string;
  kind: 'objection' | 'supplement';
  read_boundaries?: FeedbackReadBoundary[] | null;
  read_projection?: 'partial' | null;
  recorded_at: VersionPoint;
  schema_version?: 2;
  section?:
    | 'general'
    | 'verified_facts'
    | 'historical_responsibilities'
    | 'rule_items'
    | 'model_advice';
  session_id: string;
  text: string;
  version?: 1;
};
export type FeedbackV2 = {
  schema_version?: 2;
  model_advice?: RegisteredModelAdvice[] | null;
  provenance?: FeedbackProvenance | null;
  read_boundaries?: FeedbackReadBoundary[] | null;
  read_projection?: 'partial' | null;
  id: string;
  session_id: string;
  version?: number;
  subject: ObjectRef;
  evaluation: FileRef;
  as_of: VersionPoint;
  mode?: 'advisory' | 'scoring';
  adoption_record?: FileRef | null;
  items: FeedbackItem[];
  business_response: string;
  next_options: string[];
  verified_coverage: number;
  model_coverage: number;
  independent_understanding?: 'unobserved' | 'observed_with_evidence';
  verified_facts?: VerifiedFactsSnapshot[] | null;
  historical_responsibilities?: HistoricalResponsibilitiesSnapshot[] | null;
  rule_items?: FeedbackItem[] | null;
  basis_refs?: ObjectRef[] | null;
  conditions?: string[] | null;
  available_actions?: _OutcomeAction[] | null;
  outcomes?: _OutcomeItem[] | null;
  preview_language?: 'zh' | 'en' | null;
  preview_kind?: 'rules' | 'advisory' | null;
  input_refs?: ObjectRef[] | null;
  evaluation_as_of?: VersionPoint | null;
  missing_inputs?: string[] | null;
  clarification?: string[] | null;
  generation_status?: 'rules_verified' | 'waiting_model' | 'advisory' | 'failed' | 'unknown' | null;
};
export type FileRef = { media_type?: string; path: string; schema_version?: 2; sha256: string };
export type HistoricalResponsibilitiesSnapshot = {
  schema_version?: 2;
  subject: ObjectRef;
  as_of: VersionPoint | null;
  requested_at: VersionPoint;
  captured_at: VersionPoint;
  source_snapshot_hash: string | null;
  completeness?: 'complete' | 'partial' | 'unknown';
  coverage?: FeedbackActivityWindow | null;
  entries?: HistoricalResponsibilityFinding[];
};
export type HistoricalResponsibilityFinding = {
  schema_version?: 2;
  criterion: string;
  kind: 'actual_action' | 'commitment' | 'completion_claim' | 'unknown';
  state: 'active' | 'withdrawn' | 'unknown';
  occurred_at: VersionPoint | null;
  evaluated_at: VersionPoint;
  scope: ObjectRef[];
  finding:
    | 'unknown'
    | 'recorded_commitment'
    | 'verified_breach'
    | 'verified_within_limit'
    | 'claim_matches_record'
    | 'verified_claim_mismatch'
    | 'claim_has_run_records'
    | 'recorded_action';
  explanation: string;
  sources?: EvidenceRefV2[];
  actor_id?: string | null;
  executor?: Executor | null;
};
export type ImportConflict = {
  existing?: ObjectRef | null;
  original_id: string;
  original_version?: number | null;
  reason:
    | 'missing_history'
    | 'version_conflict'
    | 'content_conflict'
    | 'foreign_session'
    | 'unresolved_reference';
  schema_version?: 2;
  source_content_hash?: string | null;
};
export type ImportReference = {
  original_id: string;
  original_session_id: string;
  resolved?: ObjectRef | null;
  schema_version?: 2;
  status: 'resolved' | 'missing' | 'foreign_session' | 'unverified_local';
};
export type ImportResult = {
  applied: boolean;
  as_of: VersionPoint;
  conflicts?: ImportConflict[];
  id_map: Record<string, ObjectRef>;
  mode: 'preview' | 'apply';
  package_id: string;
  schema_version?: 2;
  unresolved: ImportReference[];
  version_map?: ImportVersionMap[];
};
export type ImportVersionMap = {
  original_id: string;
  original_session_id: string;
  original_version: number;
  schema_version?: 2;
  status: 'resolved' | 'unresolved' | 'unverified_local';
  target?: ObjectRef | null;
};
export type ImportedTaskSource = { schema_version?: 2; source: LegacyProvenance; task: ObjectRef };
export type InvestigationBlock = {
  id: string;
  revision?: number;
  schema_version?: 2;
  source_ref?: EvidenceRefV2 | null;
  test_ref?: ObjectRef | null;
  test_refs?: ObjectRef[];
  text?: string;
  title?: string;
  type: 'text' | 'note' | 'source_check' | 'retest' | 'test_compare';
};
export type InvestigationPayload = {
  blocks?: InvestigationBlock[];
  question?: string;
  review_direction?: 'unknown' | 'supports' | 'contradicts' | 'mixed';
  review_focus?: 'index' | 'source' | 'uncertain' | 'other';
  review_note?: string;
  schema_version?: 2;
  type?: 'investigation';
};
export type JobRefreshRecord = {
  attempt: number;
  parked_at?: string | null;
  previous_as_of: VersionPoint;
  queued_at?: string | null;
  reason: string;
  refreshed_at: string;
  schema_version?: 2;
  started_at?: string | null;
};
export type JsonValue = unknown;
export type LegacyProvenance = {
  original_hash: string;
  original_id: string;
  original_kind: string;
  original_purpose?: string | null;
  raw: Record<string, JsonValue>;
  schema_version?: 2;
  source_schema: string;
  source_session_id: string;
};
export type MaterialMetadata = {
  domain: string;
  id: string;
  schema_version?: 2;
  title: string;
  version: number;
};
export type ModelAttemptUsage = {
  attempt_id: string;
  cost?: number | null;
  elapsed_seconds: number;
  expected_model_revision?: string | null;
  expected_provider?: string | null;
  input_tokens?: number | null;
  model_revision: string | null;
  output_tokens?: number | null;
  provider: string | null;
  request_id: string;
  schema_version?: 2;
  status: 'success' | 'failed' | 'timeout' | 'unknown';
  usage_known: boolean;
};
export type ObjectRead = { as_of?: VersionPoint | null; ref: ObjectRef; schema_version?: 2 };
export type ObjectRef = {
  config_version?: number | null;
  kind: string;
  object_id: string;
  schema_version?: 2;
  session_id: string;
  version: number;
};
export type Observation = {
  actor: Executor;
  actual_disclosures?: PublicDisclosureRecord[];
  as_of: VersionPoint;
  budget?: Budget | null;
  catalog?: MaterialMetadata[];
  events?: ObjectRef[];
  next_seq: number;
  products?: ObjectRef[];
  read_versions?: ObjectRef[];
  schema_version?: 2;
  session_id: string;
  tests?: ObjectRef[];
  tools?: ToolSchema[];
  visible_sources: ObservedFragment[];
};
export type ObservedFragment = {
  acquired_at_seq: number;
  acquired_via: 'material_read' | 'tool_result' | 'role_reply' | 'displayed';
  audience: 'learner' | 'role_private' | 'model_only';
  channel: string;
  disclosure_ref?: ObjectRef | null;
  fact_ids?: string[];
  ref: EvidenceRefV2;
  schema_version?: 2;
  text: string;
  verification?: 'unverified' | 'model_extracted' | 'verified' | 'rejected';
};
export type Option = {
  id: string;
  rationale?: string;
  schema_version?: 2;
  title: string;
  tradeoffs?: string[];
};
export type OptionsPayload = { options?: Option[]; schema_version?: 2; type?: 'options' };
export type PlanPayload = { schema_version?: 2; sections: Record<string, string>; type?: 'plan' };
export type ProductAdopt = {
  expected_head: number;
  product_id: string;
  product_version: number;
  schema_version?: 2;
  status: 'unadopted' | 'adopted' | 'rejected';
};
export type ProductCreate = {
  content?: string;
  evidence_refs?: EvidenceRefV2[];
  kind: 'text' | 'plan' | 'test_plan' | 'options' | 'investigation';
  legacy?: LegacyProvenance | null;
  purpose?: string;
  schema_version?: 2;
  source_return_id?: string | null;
  structured_payload?:
    | (TextPayload | PlanPayload | TestPlanPayload | OptionsPayload | InvestigationPayload)
    | null;
  task?: ObjectRef | null;
  title?: string;
};
export type ProductEdit = {
  content?: string;
  evidence_refs?: EvidenceRefV2[];
  expected_head: number;
  kind: 'text' | 'plan' | 'test_plan' | 'options' | 'investigation';
  legacy?: LegacyProvenance | null;
  product_id: string;
  purpose?: string;
  removed?: boolean;
  schema_version?: 2;
  source_return_id?: string | null;
  structured_payload?:
    | (TextPayload | PlanPayload | TestPlanPayload | OptionsPayload | InvestigationPayload)
    | null;
  task?: ObjectRef | null;
  title?: string;
};
export type ProductShare = {
  id: string;
  product: ObjectRef;
  purpose?: string;
  question?: string;
  recipient_role: string;
  revoked_at?: VersionPoint | null;
  schema_version?: 2;
  session_id: string;
  shared_at: VersionPoint;
  version: number;
};
export type PublicDisclosureRecord = {
  displayed_at_seq: number;
  fact_id: string;
  quote: string;
  reply_ref: ObjectRef;
  schema_version?: 2;
  source: PublicDisclosureSource;
  verification: 'model_extracted' | 'verified' | 'rejected';
};
export type PublicDisclosureSource = {
  config_version?: number | null;
  kind: string;
  object_id: string;
  observed_at_seq: number;
  quote?: null;
  schema_version?: 2;
  session_id: string;
  span_end?: null;
  span_start?: null;
  valid_from_seq?: number;
  valid_until_seq?: number | null;
  version: number;
};
export type PublicEvent = {
  data?: Record<string, JsonValue>;
  executor: Executor;
  id: string;
  refs?: ObjectRef[];
  schema_version?: 2;
  seq: number;
  session_id: string;
  transaction_id: string;
  type: string;
};
export type PublicState = {
  business_seq: number;
  config_version: number;
  cycle_id: string;
  schema_version?: 2;
  session_id: string;
  status: 'active' | 'paused' | 'submitted';
  storage_revision: number;
  workspace_revision: number;
};
export type PublicTransactionResult = {
  boundary: ActionBoundary;
  events: PublicEvent[];
  executor: Executor;
  objects: ObjectRef[];
  replayed?: boolean;
  result: Record<string, JsonValue>;
  schema_version?: 2;
  state: PublicState;
  transaction_id: string;
};
export type RegisteredModelAdvice = {
  schema_version?: 2;
  criterion?: 'R2.support';
  request_id: string;
  job_id: string;
  input_hash: string | null;
  registration: RegisteredModelIdentity | null;
  status: 'completed' | 'failed' | 'unavailable' | 'synthetic_mechanism_only';
  label?: 'SUPPORTED' | 'CONTRADICTED' | 'INSUFFICIENT' | null;
  evidence_ids?: string[];
  citations?: EvidenceRefV2[];
  error_code?:
    | 'model_unavailable'
    | 'model_load_failed'
    | 'pretrained_encoder_dependencies_unavailable'
    | 'model_timeout'
    | 'model_infrastructure_failed'
    | 'model_files_changed'
    | 'model_reference_invalid'
    | 'evidence_unavailable'
    | 'model_result_unconfirmed'
    | 'model_prediction_invalid'
    | 'claim_not_available'
    | 'synthetic_mechanism_only'
    | null;
  mode?: 'advisory';
  affects_score?: false;
};
export type RegisteredModelIdentity = {
  id: string;
  model_revision: string;
  scope: 'synthetic_fixture' | 'external_candidate';
  quality_validated?: false;
};
export type RequestJobResult = {
  effect?: PublicTransactionResult | null;
  effect_request_id: string;
  error_code?: string | null;
  job_id: string;
  origin_request_id: string;
  refresh_count?: number;
  refresh_history?: JobRefreshRecord[];
  schema_version?: 2;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'needs_context';
};
export type RequestResult = {
  executor: Executor;
  jobs?: RequestJobResult[];
  operation: string;
  read_only?: true;
  request_id: string;
  response: PublicTransactionResult;
  schema_version?: 2;
  session_id: string;
  status: 'completed' | 'pending' | 'failed' | 'unresolved' | 'needs_context';
};
export type RetrievedChunk = {
  id: string;
  material_id: string;
  ref: EvidenceRefV2;
  schema_version?: 2;
  score: number;
  version: number;
};
export type ReviewInput = {
  candidate_config?: AssistantConfig | null;
  decision?: 'launch' | 'launch_narrow' | 'defer_with_conditions' | 'no_go' | null;
  followup_of?: ObjectRef[];
  preview_kind?: 'rules' | 'advisory' | null;
  preview_on_save?: boolean | null;
  purpose: string;
  question?: string;
  requested_outcomes?: string[] | null;
  schema_version?: 2;
  scope: string[];
  subjects: ObjectRef[];
};
export type ReviewRequest = {
  as_of: VersionPoint;
  available_operations?: string[] | null;
  candidate_config?: AssistantConfig | null;
  decision?: 'launch' | 'launch_narrow' | 'defer_with_conditions' | 'no_go' | null;
  evaluation: FileRef;
  executor: Executor;
  followup_of?: ObjectRef[];
  id: string;
  preview_kind?: 'rules' | 'advisory' | null;
  preview_on_save?: boolean | null;
  purpose: string;
  question?: string;
  requested_outcomes?: string[] | null;
  schema_version?: 2;
  scope: string[];
  session_id: string;
  subjects: ObjectRef[];
  version?: number;
};
export type RuleBound = {
  schema_version?: 2;
  lower: 'NOT_MET' | 'PARTIAL' | 'MET';
  upper: 'NOT_MET' | 'PARTIAL' | 'MET';
};
export type ShareCreate = {
  product_id: string;
  product_version: number;
  purpose?: string;
  question?: string;
  recipient_role: string;
  schema_version?: 2;
};
export type ShareUpdate = {
  expected_revision: number;
  operation: 'revoke' | 'restore';
  product_id: string;
  schema_version?: 2;
  share_id: string;
};
export type SubmissionV2 = {
  as_of: VersionPoint;
  config?: ObjectRef | null;
  cycle: ObjectRef;
  decision: 'launch' | 'launch_narrow' | 'defer_with_conditions' | 'no_go';
  evaluation: FileRef;
  evidence_refs?: EvidenceRefV2[];
  executor: Executor;
  id: string;
  products: ObjectRef[];
  rules_revision?: 'rules-v4';
  scenario: FileRef;
  schema_version?: 2;
  session_id: string;
  version?: number;
};
export type SubmitInput = {
  config?: ObjectRef | null;
  decision: 'launch' | 'launch_narrow' | 'defer_with_conditions' | 'no_go';
  evidence_refs?: EvidenceRefV2[];
  products: ObjectRef[];
  schema_version?: 2;
};
export type TaskBatch = { creates?: TaskCreate[]; schema_version?: 2; updates?: TaskPatch[] };
export type TaskCreate = {
  goal?: string;
  order?: number;
  parent?: ObjectRef | null;
  priority?: number;
  relations?: ObjectRef[];
  schema_version?: 2;
  title: string;
};
export type TaskPatch = {
  clear_parent?: boolean;
  expected_revision: number;
  goal?: string | null;
  item_id: string;
  order?: number | null;
  parent?: ObjectRef | null;
  priority?: number | null;
  relations?: ObjectRef[] | null;
  schema_version?: 2;
  status?: 'open' | 'active' | 'paused' | 'blocked' | 'done' | 'removed' | null;
  title?: string | null;
};
export type TestCase = {
  declared_category?: string | null;
  declared_expected?: string | null;
  id: string;
  intent?: string;
  query: string;
  refs?: EvidenceRefV2[];
  revision?: number;
  run?: ObjectRef | null;
  schema_version?: 2;
};
export type TestExecutionMetadata = {
  attempts?: ModelAttemptUsage[];
  chunks: RetrievedChunk[];
  cost_complete?: boolean;
  executed_at: string;
  executor: Executor;
  indexed_versions: Record<string, number>;
  projection_actor: string;
  schema_version?: 2;
  source_versions: Record<string, number>;
  used_versions: Record<string, number>;
};
export type TestPlanPayload = { cases?: TestCase[]; schema_version?: 2; type?: 'test_plan' };
export type TestRequestV2 = {
  config_version: number;
  declared_category?: string | null;
  declared_expected?: string | null;
  query: string;
  schema_version?: 2;
};
export type TestResultV2 = {
  answer: string;
  as_of: VersionPoint;
  citations: EvidenceRefV2[];
  config: EffectiveConfig;
  config_ref: ObjectRef;
  declared_category?: string | null;
  declared_expected?: string | null;
  error_code?: string | null;
  execution: TestExecutionMetadata;
  id: string;
  observed_coverage?: string[];
  query: string;
  schema_version?: 2;
  session_id: string;
  status: 'answered' | 'answered_with_warning' | 'fallback' | 'failed';
  version?: number;
};
export type TextPayload = { body: string; schema_version?: 2; type?: 'text' };
export type ToolSchema = {
  available: boolean;
  capability: 'read' | 'act' | 'submit';
  name: string;
  parameters: Record<string, JsonValue>;
  parameters_hash: string;
  schema_version?: 2;
  unavailable_code?: string | null;
};
export type TurnInput = {
  role_id: string;
  schema_version?: 2;
  shares?: ObjectRef[];
  task?: ObjectRef | null;
  text: string;
};
export type VerifiedFactsSnapshot = {
  schema_version?: 2;
  subject: ObjectRef;
  status: 'verified' | 'partial' | 'unknown';
  as_of: VersionPoint | null;
  requested_at: VersionPoint;
  captured_at: VersionPoint;
  source_snapshot_hash: string | null;
  references?: FeedbackReferenceCheck[];
  activity_records?: FeedbackActivity[];
  activity_totals?: Record<string, FeedbackActivityCount>;
  activity_window?: FeedbackActivityWindow | null;
  declared_source_count?: number | null;
  declared_citation_count?: number | null;
  verified_source_count?: number | null;
  author?: Executor | null;
  executor?: Executor | null;
  adopter?: Executor | null;
  actor_id?: string | null;
  summary?: string[];
  independent_understanding?: 'unobserved';
  conclusion_quality?: 'not_scored';
};
export type VersionPoint = {
  business_seq: number;
  schema_version?: 2;
  storage_revision: number;
  workspace_revision: number;
};
export type WorkProductVersion = {
  adoption?: Adoption;
  author: Executor;
  content?: string;
  content_hash: string;
  created_at: string;
  cycle: ObjectRef;
  draft?: boolean;
  evidence_refs?: EvidenceRefV2[];
  executor: Executor;
  kind?: 'text' | 'plan' | 'test_plan' | 'options' | 'investigation';
  legacy?: LegacyProvenance | null;
  product_id: string;
  purpose?: string;
  removed_at?: string | null;
  schema_version?: 2;
  session_id: string;
  shares?: ObjectRef[];
  source_return_id?: string | null;
  structured_payload?:
    | (TextPayload | PlanPayload | TestPlanPayload | OptionsPayload | InvestigationPayload)
    | null;
  task?: ObjectRef | null;
  title?: string;
  version: number;
  visibility?: 'private' | 'shared';
};
export type WorkspaceImport = {
  items: LegacyProvenance[];
  mode: 'preview' | 'apply';
  package_hash: string;
  package_id: string;
  preview_storage_revision?: number | null;
  references?: ImportReference[];
  schema_version?: 2;
  source_schema: string;
  source_session_id: string;
};
export type WorkspaceImportReceipt = {
  created_at: string;
  executor: Executor;
  fingerprint: string;
  id: string;
  package_hash: string;
  package_id: string;
  result: ImportResult;
  schema_version?: 2;
  session_id: string;
  source_schema: string;
  source_session_id: string;
  task_sources?: ImportedTaskSource[];
  version?: number;
};
export type WorkspaceProductPage = {
  as_of: VersionPoint;
  items: WorkspaceProductRead[];
  next_cursor?: number | null;
  previews?: FeedbackV2[] | null;
  schema_version?: 2;
  shares: ProductShare[];
  sharing_complete: boolean;
};
export type WorkspaceProductRead = {
  adoption?: Adoption;
  author: Executor;
  content?: string;
  content_hash: string;
  created_at: string;
  cycle: ObjectRef;
  draft?: boolean;
  evidence_refs?: EvidenceRefV2[];
  executor: Executor;
  kind?: 'text' | 'plan' | 'test_plan' | 'options' | 'investigation';
  legacy?: LegacyProvenance | null;
  product_id: string;
  purpose?: string;
  removed_at?: string | null;
  schema_version?: 2;
  session_id: string;
  shares?: ObjectRef[];
  source_return_id?: string | null;
  structured_payload?:
    | (TextPayload | PlanPayload | TestPlanPayload | OptionsPayload | InvestigationPayload)
    | null;
  task?: ObjectRef | null;
  title?: string;
  version: number;
  visibility?: 'private' | 'shared' | null;
};
export type WorkspaceSharePage = {
  as_of: VersionPoint;
  items: ProductShare[];
  next_cursor?: number | null;
  schema_version?: 2;
  sharing_complete: boolean;
};
export type WorkspaceTask = {
  created_at: string;
  goal?: string;
  id: string;
  order?: number;
  parent?: ObjectRef | null;
  priority?: number;
  relations?: ObjectRef[];
  revision: number;
  schema_version?: 2;
  session_id: string;
  status?: 'open' | 'active' | 'paused' | 'blocked' | 'done' | 'removed';
  title: string;
  updated_at: string;
};
export type _OutcomeAction = {
  schema_version?: 2;
  operation:
    | 'reviews.create'
    | 'work_products.shares.create'
    | 'configuration.apply'
    | 'tests.create';
  objects: ObjectRef[];
};
export type _OutcomeItem = {
  schema_version?: 2;
  id: string;
  kind: 'fact' | 'conditional_prediction' | 'pending_verification' | 'unsupported';
  summary: string;
  basis_refs?: EvidenceRefV2[];
  conditions?: string[];
  missing_inputs?: string[];
  values?: Record<string, JsonValue>;
};
