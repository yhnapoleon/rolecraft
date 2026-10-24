/** EngineerPublicReport as published by the trusted reviewer (contract engineer-review-v1,
 * `src/career_lab/contracts/v2/engineer.py`; schema in docs/contracts/engineer-review-v1/).
 * Field names follow the contract exactly. Only `hidden_comparison` is ahead of the published
 * schema: it is optional and absent (or null) until the reviewer adds it. */

export type EngineerProbeStatus = 'answered' | 'answered_with_warning' | 'fallback' | 'failed';
export type EngineerProbeOutcome = 'pass' | 'fail' | 'error';
export type EngineerReviewStatus = 'verified' | 'report_mismatch' | 'incomplete';
export type EngineerClaimCheck = 'matched' | 'mismatch' | 'not_provided' | 'unverified';
export type EngineerFindingKind =
  | 'target_fix'
  | 'new_regression'
  | 'claim_consistency'
  | 'unresolved';
export type EngineerFindingStatus = 'pass' | 'fail' | 'unverified';
export type EngineerAdviceStatus =
  | 'waiting_model'
  | 'success'
  | 'unavailable'
  | 'invalid'
  | 'timeout';
export type EngineerPublicErrorCode =
  | 'engineer_probe_execution_failed'
  | 'engineer_baseline_execution_failed'
  | 'engineer_review_interrupted'
  | 'engineer_verification_failed';

export interface EngineerArtifactIdentity {
  readonly kind: 'submission' | 'scenario' | 'configuration' | 'model';
  readonly sha256: string;
  readonly schema_version?: 2;
}

export interface EngineerObjectRef {
  readonly session_id: string;
  readonly kind: string;
  readonly object_id: string;
  readonly version: number;
  readonly config_version?: number | null;
  readonly schema_version?: 2;
}

export interface EngineerExecutor {
  readonly id: string;
  readonly kind: 'human' | 'external_agent' | 'reference_agent' | 'system';
  readonly delegation_id?: string | null;
  readonly schema_version?: 2;
}

export interface EngineerVersionPoint {
  readonly business_seq: number;
  readonly workspace_revision: number;
  readonly storage_revision: number;
  readonly schema_version?: 2;
}

export interface EngineerPublicProbeResult {
  readonly probe_id: string;
  readonly visibility: 'public';
  readonly query: string;
  readonly expected_status: EngineerProbeStatus;
  readonly actual_status: EngineerProbeStatus | null;
  readonly result: EngineerProbeOutcome;
  readonly config_hash: string;
  readonly citations: readonly EngineerObjectRef[];
  readonly source_versions: Readonly<Record<string, number>>;
  readonly indexed_versions: Readonly<Record<string, number>>;
  readonly elapsed_seconds: number;
  readonly error_code: EngineerPublicErrorCode | null;
  readonly schema_version?: 2;
}

export interface EngineerProbeSummary {
  readonly passed: number;
  readonly failed: number;
  readonly errors: number;
  readonly schema_version?: 2;
}

/** Hidden probes compared with the original configuration; counts only, never IDs or text.
 * new_failures: passed before, fails now. fixed: failed before, passes now.
 * still_failing: fails on both. unverified: either side errored. */
export interface EngineerHiddenComparison {
  readonly new_failures: number;
  readonly fixed: number;
  readonly still_failing: number;
  readonly unverified: number;
}

export interface EngineerFinding {
  readonly kind: EngineerFindingKind;
  readonly status: EngineerFindingStatus;
  readonly visibility: 'public' | 'hidden';
  /** Authored rule text in the work language. Rendered from the component's own copy instead. */
  readonly description: string;
  readonly probe_ids: readonly string[];
  readonly schema_version?: 2;
}

export interface EngineerPublicAdvice {
  readonly status: EngineerAdviceStatus;
  /** Always null in engineer-review-v1; shown only if a later contract supplies it on success. */
  readonly text?: string | null;
  readonly model: EngineerArtifactIdentity | null;
  readonly affects_score: false;
  readonly visibility: 'public';
  readonly schema_version?: 2;
}

export interface EngineerReportApplicability {
  readonly scenario: EngineerArtifactIdentity;
  readonly config: EngineerArtifactIdentity;
  readonly base_config_hash: string;
  readonly probe_suite_hash: string;
  readonly reviewer_version_hash: string;
  readonly effective_config_hash: string;
  readonly effective_settings_hash: string;
  readonly source_versions_hash: string | null;
  readonly indexed_versions_hash: string | null;
  readonly source_as_of: EngineerVersionPoint;
  readonly schema_version?: 2;
}

export interface EngineerPublicReport {
  readonly contract_version: 'engineer-review-v1';
  readonly id: string;
  readonly submission: EngineerArtifactIdentity;
  readonly input_hash: string;
  readonly reviewer: EngineerExecutor;
  readonly created_at: string;
  readonly work_language: 'zh' | 'en';
  readonly status: EngineerReviewStatus;
  readonly claim_check: EngineerClaimCheck;
  readonly applicability: EngineerReportApplicability;
  readonly public_results: readonly EngineerPublicProbeResult[];
  readonly hidden: EngineerProbeSummary;
  /** Optional; null or missing until the reviewer publishes it. */
  readonly hidden_comparison?: EngineerHiddenComparison | null;
  readonly findings: readonly EngineerFinding[];
  readonly unresolved: readonly never[];
  readonly advice: EngineerPublicAdvice | null;
  readonly affects_score: false;
  readonly schema_version?: 2;
}

/** One engineer rubric conclusion (E1–E5), returned beside the report by the engineer API. */
export type EngineerEvaluationLabel =
  | 'MET'
  | 'PARTIAL'
  | 'NOT_MET'
  | 'INSUFFICIENT'
  | 'NOT_APPLICABLE';
export interface EngineerEvaluationItem {
  /** e.g. 'E1.target_fixed'; known IDs get their rubric title, never shown raw. */
  readonly id: string;
  readonly label: EngineerEvaluationLabel | null;
  readonly basis: 'rule' | string;
  readonly status?: 'waiting_model' | string;
  /** Localized rubric title for an ID this component does not know. */
  readonly title?: string;
}
