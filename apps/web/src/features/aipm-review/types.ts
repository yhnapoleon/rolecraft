/** Local stand-in for L4's `SectionReview` (v2 design spec §9.2) until it lands in
 * `aipm/types.ts`; then this file re-exports L4's types and the view keeps its imports. */
import type {
  EvidenceRefV2,
  ObjectRef,
  ProcessFeedback,
  StepId,
  VersionPoint,
} from '../../aipm/types';

export type { StepId };
export type ReviewStatus = 'draft' | 'based' | 'solid';
export type ReviewColleague = 'manager' | 'business' | 'tech';
export type CoverageMark = 'wrong' | 'missing' | 'to_check' | 'covered';
export type Decision = 'launch' | 'launch_narrow' | 'defer_with_conditions' | 'no_go';

export type CoverageItem = {
  id: string;
  label: string;
  check: 'choice' | 'citation' | 'rule' | 'rubric_rule' | 'sentence' | 'model' | 'self';
  severity: 'high' | 'medium' | 'low';
  mark: CoverageMark;
  /** Where to look again: a topic and its sources, never the answer. */
  pointer?: { text: string; refs: EvidenceRefV2[] } | null;
  owner: ReviewColleague;
  source:
    | 'rule'
    | 'choice'
    | 'citation'
    | 'rubric_rule'
    | 'model_suggestion'
    | 'learner_assessment';
};

export type RubricLine = {
  criterion: string;
  /** MET / PARTIAL / NOT_MET for a verified rule; anything for a pending one. */
  label: string;
  source: 'verified_rule' | 'pending';
  explanation: string;
  citations?: EvidenceRefV2[];
};

export type MentorPrompt = {
  colleague: ReviewColleague;
  question: string;
  pointer?: string | null;
  trigger_id: string;
};

export type SectionReview = {
  schema_version: 1;
  id: string;
  session_id: string;
  step_id: StepId;
  prd_ref: ObjectRef;
  design_ref: ObjectRef | null;
  as_of: VersionPoint;
  created_at: string;
  status: ReviewStatus;
  stale: null | { reason: 'edited' | 'source_changed' | 'policy_changed'; detail: string };
  previous_review_ref?: ObjectRef | null;
  delta?: { citations: [number, number]; gaps: [number, number]; wrong: [number, number] } | null;
  misconceptions: ProcessFeedback[];
  coverage: CoverageItem[];
  rubric: RubricLine[];
  mentor_prompts: MentorPrompt[];
  sentence_labels: null;
  affects_formal_score: false;
};
