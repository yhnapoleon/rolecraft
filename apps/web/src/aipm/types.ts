/** G0 extension DTOs. Source: career_lab/aipm/types.py; frozen v2 types are unchanged. */
export type StepId = "business" | "stakeholders" | "need" | "boundary" | "solution" | "assurance" | "decision";
export const STEP_IDS: readonly StepId[] = ["business", "stakeholders", "need", "boundary", "solution", "assurance", "decision"];
export const EXPERIENCE_REVISION = "aipm-phase1-v1" as const;
export type DTO = Record<string, unknown>;

export type Projection = {
  complete?: boolean;
  reason?: string | null;
};

export type ObjectRef = {
  schema_version?: 2;
  session_id: string;
  kind: string;
  object_id: string;
  version: number;
  config_version?: number | null;
};

export type PublicAction = {
  action: "open_step" | "open_work" | "open_material" | "ask_colleague" | "request_review" | "open_settings" | "open_feedback" | "review_agent_draft";
  label: string;
  target?: ObjectRef | null;
  step_id?: "business" | "stakeholders" | "need" | "boundary" | "solution" | "assurance" | "decision" | null;
};

export type PublicGap = {
  code: string;
  message: string;
};

export type EvidenceRefV2 = {
  schema_version?: 2;
  session_id: string;
  kind: string;
  object_id: string;
  version: number;
  config_version?: number | null;
  span_start?: number | null;
  span_end?: number | null;
  quote?: string | null;
  observed_at_seq: number;
  valid_from_seq?: number;
  valid_until_seq?: number | null;
};

export type ProcessFeedback = {
  id: string;
  input_ref: ObjectRef;
  step_id: "business" | "stakeholders" | "need" | "boundary" | "solution" | "assurance" | "decision";
  section_or_row_id?: string | null;
  rule_revision?: string | null;
  content_revision?: string | null;
  source: "rule" | "authored_guidance" | "colleague_opinion" | "model_suggestion" | "learner_assessment";
  finding: "violation" | "improve" | "supported_for_scope" | "unknown";
  message: string;
  basis_refs?: (EvidenceRefV2)[];
  checked_scope: string;
  next_action?: PublicAction | null;
  stale?: boolean;
  affects_formal_score?: false;
};

export type ProcessFeedbackRecord = {
  schema_version?: 2;
  id: string;
  input_ref: ObjectRef;
  step_id: "business" | "stakeholders" | "need" | "boundary" | "solution" | "assurance" | "decision";
  section_or_row_id?: string | null;
  rule_revision?: string | null;
  content_revision?: string | null;
  source: "rule" | "authored_guidance" | "colleague_opinion" | "model_suggestion" | "learner_assessment";
  finding: "violation" | "improve" | "supported_for_scope" | "unknown";
  message: string;
  basis_refs?: (EvidenceRefV2)[];
  checked_scope: string;
  next_action?: PublicAction | null;
  stale?: boolean;
  affects_formal_score?: false;
  session_id: string;
  revision?: number;
};

export type FeedbackSummary = {
  id: string;
  source: "rule" | "authored_guidance" | "colleague_opinion" | "model_suggestion" | "learner_assessment";
  finding: "violation" | "improve" | "supported_for_scope" | "unknown";
  message: string;
  input_ref: ObjectRef;
  stale?: boolean;
};

export type ReadShortcut = {
  tool: "feedback.records.read" | "objects.read";
  arguments: Record<string, unknown>;
};

export type VersionPoint = {
  schema_version?: 2;
  business_seq: number;
  workspace_revision: number;
  storage_revision: number;
};

export type FeedbackDiscovery = {
  schema_version?: 1;
  subject: ObjectRef;
  status: "ready" | "not_ready";
  feedback_ref?: ObjectRef | null;
  read?: ReadShortcut | null;
  exact_read?: ReadShortcut | null;
  reason?: string | null;
  as_of: VersionPoint;
  work_language: "zh" | "en";
  record_ready_is_not_quality_verified?: true;
};

export type GuideStep = {
  id: "business" | "stakeholders" | "need" | "boundary" | "solution" | "assurance" | "decision";
  order: number;
  label: string;
  goal: string;
  expected_outputs?: (string)[];
  suggested_questions?: (string)[];
  help?: (Record<string, unknown>)[];
  segment?: Segment | null;
  /** lucide icon name from the authored guide */
  icon?: string | null;
};

export type AipmGuide = {
  schema_version?: 1;
  experience_revision?: "aipm-phase1-v1";
  content_revision: string;
  work_language: "zh" | "en";
  steps: (GuideStep)[];
};

export type ProgressStep = {
  id: "business" | "stakeholders" | "need" | "boundary" | "solution" | "assurance" | "decision";
  order: number;
  label: string;
  goal: string;
  expected_outputs?: (string)[];
  suggested_questions?: (string)[];
  help?: (Record<string, unknown>)[];
  work_status: "not_started" | "working" | "recorded" | "recheck" | "uncovered";
  completed: boolean;
  completion_meaning?: "work_recorded_not_mastery";
  evidence_refs?: (ObjectRef)[];
  missing?: (PublicGap)[];
  quality_status?: "unverified" | "has_findings" | "checked_for_declared_scope";
  open_feedback?: (FeedbackSummary)[];
  next_actions?: (PublicAction)[];
  sheet?: SheetState;
};

export type Segment = "clarify" | "design" | "verify";
export type Decision = "launch" | "launch_narrow" | "defer_with_conditions" | "no_go";
export type SheetStatus = "not_started" | "draft" | "based" | "solid" | "recheck";
export type Colleague = "manager" | "business" | "tech";
/** The worksheet view of one step: latest section review against the current PRD. */
export type SheetState = {
  status: SheetStatus;
  recheck_reason?: "edited" | "source_changed" | "policy_changed" | null;
  review_ref?: ObjectRef | null;
  prd_version?: number | null;
  edited_since_review: boolean;
  gap_hint?: string | null;
  agent_draft_pending: boolean;
};

export type AipmProgress = {
  schema_version?: 1;
  session_id: string;
  experience_revision?: string;
  content_revision: string;
  work_language: "zh" | "en";
  as_of: VersionPoint;
  focus_step: "business" | "stakeholders" | "need" | "boundary" | "solution" | "assurance" | "decision";
  suggested_step: "business" | "stakeholders" | "need" | "boundary" | "solution" | "assurance" | "decision";
  projection?: Projection;
  steps: (ProgressStep)[];
  submission_feedback?: (FeedbackDiscovery)[];
  unresolved_business_items?: (PublicGap)[];
  /** Agent drafts never count as step records until the owner adopts them. */
  pending_agent_drafts?: (DraftSummary)[];
  /** The pilot PRD's latest visible version. */
  prd_ref?: ObjectRef | null;
  next_cursor?: string | null;
};

export type DraftSummary = {
  ref: ObjectRef;
  author_kind: "human" | "external_agent" | "reference_agent" | "system";
  steps: StepId[];
  status?: "pending_owner_review";
};

export type AipmProfile = {
  schema_version?: 2;
  id?: "aipm-profile";
  session_id: string;
  revision?: 1;
  experience_revision?: "aipm-phase1-v1";
  content_revision: string;
  scenario_hash: string;
  work_language: "zh" | "en";
  enrolled_at: string;
};

export type AipmFocus = {
  schema_version?: 2;
  id?: "aipm-focus";
  session_id: string;
  step_id: "business" | "stakeholders" | "need" | "boundary" | "solution" | "assurance" | "decision";
  revision: number;
  changed_by: string;
  changed_at: string;
};

export type AipmStepLink = {
  schema_version?: 2;
  id: string;
  session_id: string;
  step_id: "business" | "stakeholders" | "need" | "boundary" | "solution" | "assurance" | "decision";
  product_ref: ObjectRef;
  section_key?: string | null;
  linked_by: string;
  source_kind?: "learner_link" | "structured_record";
  revision: number;
};

export type EmptyRead = {
  schema_version?: 2;
};

export type PageRead = {
  schema_version?: 2;
  cursor?: number;
  limit?: number;
  step_id?: "business" | "stakeholders" | "need" | "boundary" | "solution" | "assurance" | "decision" | null;
};

export type FeedbackRead = {
  schema_version?: 2;
  submission_id: string;
  version: number;
};

export type EnrollInput = {
  schema_version?: 2;
};

export type FocusInput = {
  schema_version?: 2;
  step_id: "business" | "stakeholders" | "need" | "boundary" | "solution" | "assurance" | "decision";
};

export type StepLinkInput = {
  schema_version?: 2;
  step_id: "business" | "stakeholders" | "need" | "boundary" | "solution" | "assurance" | "decision";
  product_ref: ObjectRef;
  section_key?: string | null;
};

export type BusinessDeclaration = {
  audience: "internal" | "external" | "both" | "unknown";
  offering_explanation: string;
  task_goal: string;
  source_refs?: (EvidenceRefV2)[];
};

export type StakeholderDeclaration = {
  id: string;
  name_or_role: string;
  relationships: ("user" | "buyer" | "approver" | "operator" | "affected")[];
  responsibility: string;
  fact_or_hypothesis: "fact" | "hypothesis" | "unknown";
  source_refs?: (EvidenceRefV2)[];
};

export type MetricDeclaration = {
  kind: "elapsed_time" | "labor_time" | "case_count" | "other";
  source_field: string;
  unit: string;
  population: string;
  window: string;
  formula_description: string;
  claimed_interpretation: string;
};

export type NeedDeclaration = {
  id: string;
  stakeholder_ids?: (string)[];
  problem: string;
  claim_status: "hypothesis" | "supported" | "unresolved";
  source_refs?: (EvidenceRefV2)[];
  counterevidence_or_unknown: string;
  next_validation: string;
  metric?: MetricDeclaration | null;
};

export type TriageRow = {
  id: string;
  revision?: number;
  need_ref: string;
  source_refs?: (EvidenceRefV2)[];
  user_request: string;
  target_action: "explain" | "calculate" | "prepare_draft" | "execute_change" | "approve" | "unknown";
  route: "deterministic" | "retrieval_generation" | "agent_confirmation" | "human";
  rationale: string;
  final_authority: "learner" | "named_human_role" | "ai" | "unknown";
  confirmation_point?: string | null;
  tool_assumptions?: (string)[];
  unresolved?: (string)[];
  execution_support?: "supported" | "plan_only" | "unknown";
};

export type SolutionIntent = {
  selected_approach: string;
  rationale: string;
  dependencies?: (string)[];
  alternative: string;
  source_refs?: (EvidenceRefV2)[];
};

export type AipmDesign = {
  schema_version?: 2;
  id: string;
  session_id: string;
  revision: number;
  prd_ref?: ObjectRef | null;
  business?: BusinessDeclaration | null;
  stakeholders?: (StakeholderDeclaration)[];
  needs?: (NeedDeclaration)[];
  rows?: (TriageRow)[];
  solution?: SolutionIntent | null;
  /** Exact evidence copied from authorized reads, per PRD section; never rebased. */
  section_refs?: Partial<Record<StepId, EvidenceRefV2[]>>;
  intended_decision?: Decision | null;
};

export type MonitoringPlan = {
  metric: string;
  definition: string;
  observation_window: string;
  owner: string;
  trigger: string;
  response: string;
  rollback_target: string;
  verification_plan: string;
};

export type BatchCase = {
  id: string;
  need_ref: string;
  triage_row_id: string;
  triage_row_revision: number;
  request_id: string;
  test_case_ref: ObjectRef;
  expected_ref: ObjectRef;
  original_command?: Record<string, unknown> | null;
  run_ref?: ObjectRef | null;
  status?: "completed" | "execution_failed" | "unsupported" | "cancelled" | "pending";
};

export type AipmBatch = {
  schema_version?: 2;
  id: string;
  session_id: string;
  revision: number;
  design_ref: ObjectRef;
  plan_ref: ObjectRef;
  config_ref: ObjectRef;
  material_refs?: (ObjectRef)[];
  cases: (BatchCase)[];
  execution_mode: string;
  pause_reason?: string | null;
  monitoring?: (MonitoringPlan)[];
};

export type AipmAssessment = {
  schema_version?: 2;
  id: string;
  session_id: string;
  revision?: 1;
  test_case_ref: ObjectRef;
  expected_ref: ObjectRef;
  run_ref?: ObjectRef | null;
  source: "rule" | "learner_assessment" | "model_suggestion";
  result: "satisfied" | "not_satisfied" | "unknown" | "unsupported";
  reason: string;
  evidence_refs?: (EvidenceRefV2)[];
};

export const DRAFT_PRECHECK = "draft_precheck_pending_owner" as const;

/** What an Agent proposed; shown to the owner as "from your Agent · awaiting you". */
export type AipmDesignDraft = {
  schema_version?: 2;
  id: string;
  session_id: string;
  revision: number;
  author: { id: string; kind: "human" | "external_agent" | "reference_agent" | "system"; delegation_id?: string | null };
  status: "pending_owner_review" | "adopted" | "dismissed";
  base_design_ref?: ObjectRef | null;
  business?: BusinessDeclaration | null;
  stakeholders?: (StakeholderDeclaration)[];
  needs?: (NeedDeclaration)[];
  rows?: (TriageRow)[];
  solution?: SolutionIntent | null;
  prd_sections?: Partial<Record<StepId, string>>;
  section_refs?: Partial<Record<StepId, EvidenceRefV2[]>>;
  note?: string | null;
  resolved_by?: string | null;
  adopted_design_ref?: ObjectRef | null;
};

export type DraftResolve = {
  schema_version?: 2;
  draft_id: string;
  expected_revision: number;
  status: "adopted" | "dismissed";
  adopted_design_ref?: ObjectRef | null;
};

/** Rule output on the draft only, recomputed on read; not formal process feedback. */
export type DraftPrecheck = { label: typeof DRAFT_PRECHECK; findings: ProcessFeedback[] };
export type DraftPage = { items: { ref: ObjectRef; draft: AipmDesignDraft; precheck: DraftPrecheck }[] };

// --- v2 section review (192-AIPM体验层v2 §6, §9.2) ---
export type CheckKind = "choice" | "citation" | "rule" | "rubric_rule" | "sentence" | "model" | "self";
/** Where to look again: a topic and its sources, never the correct statement. */
export type Pointer = { text: string; refs?: EvidenceRefV2[] };
export type CoverageMark = {
  id: string;
  label: string;
  check: CheckKind;
  severity: "high" | "medium" | "low";
  mark: "wrong" | "missing" | "to_check" | "covered";
  pointer?: Pointer | null;
  owner: Colleague;
  source: "rule" | "choice" | "citation" | "rubric_rule" | "model_suggestion" | "learner_assessment";
};
export type RubricLine = {
  criterion: string;
  label: string;
  source: "verified_rule" | "pending";
  explanation: string;
  citations?: EvidenceRefV2[];
};
export type MentorPrompt = { colleague: Colleague; question: string; pointer?: Pointer | null; trigger_id: string };
/** One learner-requested process review of one PRD section. Never a formal score. */
export type SectionReview = {
  schema_version?: 2;
  id: string;
  session_id: string;
  revision?: 1;
  step_id: StepId;
  prd_ref: ObjectRef;
  design_ref?: ObjectRef | null;
  as_of: VersionPoint;
  created_at: string;
  status: "draft" | "based" | "solid";
  stale?: { reason: "edited" | "source_changed" | "policy_changed"; detail: string } | null;
  previous_review_ref?: ObjectRef | null;
  delta?: { citations: [number, number]; gaps: [number, number]; wrong: [number, number] } | null;
  misconceptions?: ProcessFeedback[];
  coverage?: CoverageMark[];
  rubric?: RubricLine[];
  mentor_prompts?: MentorPrompt[];
  /** The intended decision the rubric rule checks ran with, if any. */
  decision_used?: Decision | null;
  basis?: Record<string, string>;
  sentence_labels?: null;
  affects_formal_score?: false;
};
export type SectionReviewInput = { schema_version?: 2; step_id: StepId; prd_ref: ObjectRef; design_ref?: ObjectRef | null };
export type SectionReviewPage = { items: { ref: ObjectRef; review: SectionReview }[]; next_cursor: number | null };
