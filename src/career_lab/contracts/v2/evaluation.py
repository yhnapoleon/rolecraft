from typing import Annotated, Literal

from pydantic import Field, model_validator

from . import provenance as _provenance
from .core import *
from .core import (
    V2,
    EvidenceRefV2,
    Hash,
    Identifier,
    JsonValue,
    NonNegativeInt,
    ObjectRef,
    PositiveInt,
    VersionPoint,
)
from .recognition import RecognitionRecord

Applicability = Literal["applicable", "not_applicable", "undetermined"]
CriterionLabel = Literal["MET", "PARTIAL", "NOT_MET", "INSUFFICIENT", "NOT_APPLICABLE"]
# Weighted score ranges are stored as floats from exact fractions.
_SCORE_TOLERANCE = 1e-6
RelationLabel = Literal["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"]


class CandidateEvidenceV2(V2):
    id: Identifier
    text: str
    ref: EvidenceRefV2


class RuleBound(V2):
    lower: Literal["NOT_MET", "PARTIAL", "MET"]
    upper: Literal["NOT_MET", "PARTIAL", "MET"]

    @model_validator(mode="after")
    def ordered(self):
        order = ["NOT_MET", "PARTIAL", "MET"]
        if order.index(self.lower) > order.index(self.upper):
            raise ValueError("inverted rule bound")
        return self


class EvidencePackageV2(V2):
    item_id: Identifier
    task_type: Literal["relation", "criterion"]
    criterion: str | None = None
    claim: str
    subjects: tuple[EvidenceRefV2, ...]
    purpose: str
    as_of: VersionPoint
    applicability: Applicability
    candidate_evidence: tuple[CandidateEvidenceV2, ...]
    rule_context: dict[str, JsonValue]
    rule_bound: RuleBound | None = None
    completeness: Literal["complete", "missing", "text_overflow"]
    dropped_refs: tuple[ObjectRef, ...] = ()
    missing_refs: tuple[ObjectRef, ...] = ()
    input_hash: Hash

    @model_validator(mode="after")
    def consistent(self):
        if self.applicability != "applicable" and self.rule_bound is not None:
            raise ValueError("inapplicable/undetermined cannot be scored")
        ids = [x.id for x in self.candidate_evidence]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate candidate id")
        if any(x.observed_at_seq > self.as_of.business_seq for x in self.subjects) or any(
            x.ref.observed_at_seq > self.as_of.business_seq for x in self.candidate_evidence
        ):
            raise ValueError("future evidence")
        data = self.model_dump(mode="json", exclude={"input_hash"})
        if digest(data) != self.input_hash:
            raise ValueError("evidence input hash mismatch")
        return self


class FeedbackItem(V2):
    criterion: Identifier
    label: CriterionLabel
    applicability: Applicability
    source: Literal["verified_rule", "model_advice", "pending"]
    explanation: str
    citations: tuple[EvidenceRefV2, ...]
    rule_bound: RuleBound | None = None

    @model_validator(mode="after")
    def score(self):
        if (
            self.label in {"NOT_APPLICABLE", "INSUFFICIENT"} or self.source != "verified_rule"
        ) and self.rule_bound:
            raise ValueError("unknown/advisory labels cannot tighten score bounds")
        return self


ActivityKind = Literal[
    "material_read", "test_run", "question_sent", "reply_received", "learner_displayed"
]


def feedback_point_before(left, right):
    return all(
        getattr(left, key) <= getattr(right, key)
        for key in ("business_seq", "workspace_revision", "storage_revision")
    )


class FeedbackReferenceCheck(V2):
    # An unavailable source is represented only by a digest of the submitted reference.
    submitted_reference_hash: Hash | None
    status: Literal[
        "exact_reference_verified",
        "unavailable",
        "future_evidence",
        "evidence_version_mismatch",
        "evidence_quote_mismatch",
        "evidence_time_mismatch",
        "source_time_unknown",
    ]
    verified_ref: EvidenceRefV2 | None = None
    valid_at_subject: bool | None = None
    semantic_support: Literal["not_established"] = "not_established"

    @model_validator(mode="after")
    def evidence(self):
        if (self.status == "exact_reference_verified") != (self.verified_ref is not None):
            raise ValueError("verified reference status mismatch")
        if self.verified_ref is None and self.valid_at_subject is not None:
            raise ValueError("unavailable reference validity is unknown")
        return self


class FeedbackActivity(V2):
    kind: ActivityKind
    ref: EvidenceRefV2
    occurred_at: VersionPoint
    executor: Executor
    actor_id: Identifier
    target: ObjectRef | None = None
    counterparty: str | None = None


class FeedbackActivityCount(V2):
    status: Literal["complete", "unknown"] = "unknown"
    count: NonNegativeInt | None = None
    verified_records: NonNegativeInt = 0

    @model_validator(mode="after")
    def completeness(self):
        if self.status == "unknown" and self.count is not None:
            raise ValueError("unknown log cannot assert a count")
        if self.status == "complete" and self.count != self.verified_records:
            raise ValueError("complete count must match verified records")
        return self


class FeedbackActivityWindow(V2):
    covered_from: VersionPoint
    covered_through: VersionPoint
    captured_at: VersionPoint

    @model_validator(mode="after")
    def order(self):
        if not feedback_point_before(
            self.covered_from, self.covered_through
        ) or not feedback_point_before(self.covered_through, self.captured_at):
            raise ValueError("invalid activity window")
        return self


class VerifiedFactsSnapshot(V2):
    subject: ObjectRef
    status: Literal["verified", "partial", "unknown"]
    as_of: VersionPoint | None
    requested_at: VersionPoint
    captured_at: VersionPoint
    source_snapshot_hash: Hash | None
    references: tuple[FeedbackReferenceCheck, ...] = ()
    activity_records: tuple[FeedbackActivity, ...] = ()
    activity_totals: dict[ActivityKind, FeedbackActivityCount] = {}
    activity_window: FeedbackActivityWindow | None = None
    declared_source_count: NonNegativeInt | None = None
    declared_citation_count: NonNegativeInt | None = None
    verified_source_count: NonNegativeInt | None = None
    author: Executor | None = None
    executor: Executor | None = None
    adopter: Executor | None = None
    actor_id: Identifier | None = None
    summary: tuple[str, ...] = ()
    independent_understanding: Literal["unobserved"] = "unobserved"
    conclusion_quality: Literal["not_scored"] = "not_scored"

    @model_validator(mode="after")
    def historical(self):
        if not feedback_point_before(self.requested_at, self.captured_at):
            raise ValueError("feedback capture precedes request")
        if self.as_of is None:
            if (
                self.status != "unknown"
                or self.references
                or self.activity_records
                or self.activity_totals
                or any(
                    v is not None
                    for v in (
                        self.declared_source_count,
                        self.declared_citation_count,
                        self.verified_source_count,
                    )
                )
            ):
                raise ValueError("unknown subject point cannot assert historical facts")
        elif not feedback_point_before(self.as_of, self.requested_at):
            raise ValueError("future subject point")
        refs = (
            [r.verified_ref for r in self.references if r.verified_ref is not None]
            + [r.ref for r in self.activity_records]
            + [r.target for r in self.activity_records if r.target is not None]
        )
        if any(r.session_id != self.subject.session_id for r in refs):
            raise ValueError("cross-session factual evidence")
        if self.as_of is not None and any(
            r.observed_at_seq > self.as_of.business_seq
            for r in refs
            if isinstance(r, EvidenceRefV2)
        ):
            raise ValueError("future factual reference")
        hashes = [
            r.submitted_reference_hash
            for r in self.references
            if r.submitted_reference_hash is not None
        ]
        if len(set(hashes)) != len(hashes):
            raise ValueError("duplicate submitted reference")
        if any(not feedback_point_before(r.occurred_at, self.as_of) for r in self.activity_records):
            raise ValueError("future activity fact")
        if len({canonical(r.ref) for r in self.activity_records}) != len(self.activity_records):
            raise ValueError("duplicate activity record")
        for kind, total in self.activity_totals.items():
            if total.verified_records != sum(r.kind == kind for r in self.activity_records):
                raise ValueError("activity total mismatch")
            if total.status == "complete":
                zero = VersionPoint(business_seq=0, workspace_revision=0, storage_revision=0)
                if (
                    self.as_of is None
                    or self.activity_window is None
                    or self.activity_window.covered_from != zero
                    or not feedback_point_before(self.as_of, self.activity_window.covered_through)
                ):
                    raise ValueError("complete activity count needs full historical window")
        if self.activity_window and not feedback_point_before(
            self.activity_window.captured_at, self.captured_at
        ):
            raise ValueError("activity window exceeds captured snapshot")
        if self.declared_citation_count is not None and self.declared_citation_count != len(
            self.references
        ):
            raise ValueError("declared citation count mismatch")
        known = {
            (
                x.verified_ref.session_id,
                x.verified_ref.kind,
                x.verified_ref.object_id,
                x.verified_ref.version,
                x.verified_ref.config_version,
            )
            for x in self.references
            if x.verified_ref is not None
        }
        if self.verified_source_count is not None and self.verified_source_count != len(known):
            raise ValueError("verified source count mismatch")
        if (
            self.declared_source_count is not None
            and self.verified_source_count is not None
            and self.verified_source_count > self.declared_source_count
        ):
            raise ValueError("verified sources exceed declared sources")
        return self


class HistoricalResponsibilityFinding(V2):
    criterion: Identifier
    kind: Literal["actual_action", "commitment", "completion_claim", "unknown"]
    state: Literal["active", "withdrawn", "unknown"]
    occurred_at: VersionPoint | None
    evaluated_at: VersionPoint
    scope: tuple[ObjectRef, ...] = Field(min_length=1)
    finding: Literal[
        "unknown",
        "recorded_commitment",
        "verified_breach",
        "verified_within_limit",
        "claim_matches_record",
        "verified_claim_mismatch",
        "claim_has_run_records",
        "recorded_action",
    ]
    explanation: str
    sources: tuple[EvidenceRefV2, ...] = ()
    actor_id: Identifier | None = None
    executor: Executor | None = None

    @model_validator(mode="after")
    def basis(self):
        if self.occurred_at is not None and not feedback_point_before(
            self.occurred_at, self.evaluated_at
        ):
            raise ValueError("future responsibility")
        if self.occurred_at is None and self.finding != "unknown":
            raise ValueError("known responsibility requires occurrence point")
        if self.finding != "unknown" and not self.sources:
            raise ValueError("known responsibility needs verified sources")
        if self.kind == "commitment" and self.finding not in {"unknown", "recorded_commitment"}:
            raise ValueError("commitment does not prove action")
        if self.kind == "unknown" and self.finding != "unknown":
            raise ValueError("unknown responsibility cannot be assessed")
        return self


class HistoricalResponsibilitiesSnapshot(V2):
    subject: ObjectRef
    as_of: VersionPoint | None
    requested_at: VersionPoint
    captured_at: VersionPoint
    source_snapshot_hash: Hash | None
    completeness: Literal["complete", "partial", "unknown"] = "unknown"
    coverage: FeedbackActivityWindow | None = None
    entries: tuple[HistoricalResponsibilityFinding, ...] = ()

    @model_validator(mode="after")
    def historical(self):
        if not feedback_point_before(self.requested_at, self.captured_at):
            raise ValueError("responsibility capture precedes request")
        if self.as_of is None and (self.entries or self.completeness != "unknown"):
            raise ValueError("unknown subject point cannot assert responsibilities")
        if self.as_of is not None and not feedback_point_before(self.as_of, self.requested_at):
            raise ValueError("future subject point")
        if self.completeness == "complete":
            if (
                self.as_of is None
                or self.coverage is None
                or self.coverage.covered_from
                != VersionPoint(business_seq=0, workspace_revision=0, storage_revision=0)
                or not feedback_point_before(self.as_of, self.coverage.covered_through)
            ):
                raise ValueError("complete responsibilities need trusted full coverage")
        if self.coverage and not feedback_point_before(self.coverage.captured_at, self.captured_at):
            raise ValueError("responsibility coverage exceeds capture")
        for item in self.entries:
            if item.evaluated_at != self.as_of or self.subject not in item.scope:
                raise ValueError("responsibility subject anchor mismatch")
            if any(r.session_id != self.subject.session_id for r in (*item.scope, *item.sources)):
                raise ValueError("cross-session responsibility")
            if any(r.observed_at_seq > self.as_of.business_seq for r in item.sources):
                raise ValueError("future responsibility source")
        return self


class FeedbackReadBoundary(V2):
    # Installed by the common store from a server-only complete input trace.
    path: str
    content_hash: Hash
    dependencies: tuple[ObjectRef, ...] = Field(min_length=1)
    attestation: Literal["common_store_trace_v1"] = "common_store_trace_v1"

    @model_validator(mode="after")
    def unique(self):
        if not self.path.startswith("/") or "~" in self.path:
            raise ValueError("invalid feedback segment path")
        if len({canonical(r) for r in self.dependencies}) != len(self.dependencies):
            raise ValueError("duplicate boundary dependency")
        return self


class FeedbackResponseRecord(V2):
    read_boundaries: tuple[FeedbackReadBoundary, ...] | None = None
    evidence_status: Literal["none_submitted", "user_submitted_unverified"] | None = None
    read_projection: Literal["partial"] | None = None
    id: Identifier
    session_id: Identifier
    version: Literal[1] = 1
    feedback: ObjectRef
    kind: Literal["objection", "supplement"]
    section: Literal[
        "general", "verified_facts", "historical_responsibilities", "rule_items", "model_advice"
    ] = "general"
    criterion: Identifier | None = None
    text: Annotated[str, Field(min_length=1, max_length=12000)]
    evidence: tuple[EvidenceRefV2, ...] = ()
    recorded_at: VersionPoint
    executor: Executor

    @model_validator(mode="after")
    def linked(self):
        if self.feedback.kind != "feedback" or self.feedback.session_id != self.session_id:
            raise ValueError("invalid feedback link")
        if (
            self.evidence_status is not None
            and self.read_projection is None
            and self.evidence_status
            != ("user_submitted_unverified" if self.evidence else "none_submitted")
        ):
            raise ValueError("invalid submitted evidence status")
        if not self.text.strip():
            raise ValueError("response text is empty")
        if self.kind == "supplement" and not self.evidence and self.read_projection is None:
            raise ValueError("supplement needs exact evidence")
        if any(
            r.session_id != self.session_id or r.observed_at_seq > self.recorded_at.business_seq
            for r in self.evidence
        ):
            raise ValueError("invalid response evidence")
        if len({canonical(r) for r in self.evidence}) != len(self.evidence):
            raise ValueError("duplicate response evidence")
        return self


class _OutcomeAction(V2):
    operation: Literal[
        "reviews.create",
        "work_products.shares.create",
        "configuration.apply",
        "tests.create",
        "actions",
        "submissions.create",
    ]
    objects: tuple[ObjectRef, ...]


class _OutcomeItem(V2):
    id: Identifier
    kind: Literal["fact", "conditional_prediction", "pending_verification", "unsupported"]
    summary: str
    basis_refs: tuple[EvidenceRefV2, ...] = ()
    conditions: tuple[str, ...] = ()
    missing_inputs: tuple[str, ...] = ()
    values: dict[str, JsonValue] = {}

    @model_validator(mode="after")
    def grounded(self) -> "_OutcomeItem":
        if self.kind in {"fact", "conditional_prediction"} and not self.basis_refs:
            raise ValueError("verified outcomes require exact sources")
        if self.kind == "conditional_prediction" and not self.conditions:
            raise ValueError("predictions require explicit conditions")
        return self


class _PreviewConditions(V2):
    """Key business conditions read when a preview was formed; None means not a key condition."""

    config_version: NonNegativeInt | None = None
    resources: dict[str, NonNegativeInt] | None = None
    source_versions: dict[str, PositiveInt] | None = None


class _PreviewChange(V2):
    """A key condition that differs from the recorded one at a later read."""

    condition: Literal["input", "configuration", "resources", "materials"]
    before: JsonValue = None
    after: JsonValue = None
    ref: ObjectRef | None = None


class _PreviewActual(V2):
    """A business action recorded after the preview; never merged into the prediction."""

    operation: Literal[
        "configuration.apply",
        "actions",
        "tests.create",
        "submissions.create",
        "work_products.shares.create",
    ]
    ref: ObjectRef
    status: Identifier
    at: VersionPoint | None = None
    values: dict[str, JsonValue] = {}


class _PreviewState(V2):
    """Read-time freshness of one immutable preview record; the record itself is unchanged."""

    feedback: ObjectRef
    status: Literal["current", "stale"]
    changes: tuple[_PreviewChange, ...] = ()
    superseded_by: ObjectRef | None = None
    actual: tuple[_PreviewActual, ...] = ()
    checked_at: VersionPoint

    @model_validator(mode="after")
    def consistent(self) -> "_PreviewState":
        if (self.status == "stale") != bool(self.changes):
            raise ValueError("stale previews name their changed conditions")
        if self.feedback.kind != "feedback":
            raise ValueError("preview state belongs to a feedback record")
        return self


class _RuleScoreCriterion(V2):
    """One criterion's frozen weight and how the rules anchor it.

    Points appear only where a verified rule bound fixes them; pending, undetermined and
    not-applicable criteria carry a weight but never a per-criterion score.
    """

    criterion: Identifier
    weight: Annotated[float, Field(gt=0, le=100)]
    status: Literal["anchored", "bounded", "pending", "undetermined", "not_applicable"]
    lower: Annotated[float, Field(ge=0, le=100)] | None = None
    upper: Annotated[float, Field(ge=0, le=100)] | None = None

    @model_validator(mode="after")
    def rule_points_only(self) -> "_RuleScoreCriterion":
        ruled = self.status in {"anchored", "bounded"}
        if self.lower is None or self.upper is None:
            if ruled or self.lower is not None or self.upper is not None:
                raise ValueError("only rule-verified criteria carry points")
            return self
        if not ruled:
            raise ValueError("only rule-verified criteria carry points")
        if self.lower > self.upper or self.upper > self.weight + _SCORE_TOLERANCE:
            raise ValueError("rule points must lie within the criterion weight")
        if (self.status == "anchored") != (self.upper - self.lower <= _SCORE_TOLERANCE):
            raise ValueError("anchored criteria have one rule outcome; bounded ones a range")
        return self


class _RuleScoreRange(V2):
    """Advisory weighted range of the rule-anchored rubric part; never a single total.

    Weights come from the rubric file installed with the evaluation that produced the
    feedback. Verified rule bounds tighten the range; pending, model-advice and undetermined
    criteria span their full weight; not-applicable criteria leave the denominator, which is
    reported as it is rather than rescaled. No range exists when nothing applies.
    """

    rubric_revision: Identifier
    rubric_sha256: Hash
    denominator: Annotated[float, Field(ge=0, le=100)]
    lower: Annotated[float, Field(ge=0, le=100)] | None = None
    upper: Annotated[float, Field(ge=0, le=100)] | None = None
    criteria: tuple[_RuleScoreCriterion, ...]

    @model_validator(mode="after")
    def consistent(self) -> "_RuleScoreRange":
        names = [row.criterion for row in self.criteria]
        if not names or len(set(names)) != len(names):
            raise ValueError("a score range lists every criterion exactly once")
        if abs(sum(row.weight for row in self.criteria) - 100) > _SCORE_TOLERANCE:
            raise ValueError("criterion weights must keep the full rubric weight of 100")
        applicable = [row for row in self.criteria if row.status != "not_applicable"]
        if abs(sum(row.weight for row in applicable) - self.denominator) > _SCORE_TOLERANCE:
            raise ValueError("the denominator is the weight of criteria that apply")
        if not applicable:
            if self.lower is not None or self.upper is not None:
                raise ValueError("no criterion applies, so there is no range")
            return self
        if self.lower is None or self.upper is None:
            raise ValueError("an applicable rubric part reports both ends of its range")
        lower = sum(row.lower or 0 for row in applicable)
        upper = sum(row.weight if row.upper is None else row.upper for row in applicable)
        if max(abs(lower - self.lower), abs(upper - self.upper)) > _SCORE_TOLERANCE:
            raise ValueError("the range must follow its criteria")
        return self


# Relation labels, then the criterion labels not already listed; checked per task_type.
_AdviceLabel = Literal[
    "SUPPORTED", "CONTRADICTED", "INSUFFICIENT", "MET", "PARTIAL", "NOT_MET", "NOT_APPLICABLE"
]
_RELATION_LABELS = frozenset(("SUPPORTED", "CONTRADICTED", "INSUFFICIENT"))
_CRITERION_LABELS = frozenset(("MET", "PARTIAL", "NOT_MET", "INSUFFICIENT", "NOT_APPLICABLE"))


def _selected_evidence(evidence_ids, citations) -> None:
    if len(set(evidence_ids)) != len(evidence_ids):
        raise ValueError("duplicate selected evidence")
    if len(evidence_ids) != len(citations):
        raise ValueError("selected evidence needs exact citations")


class _AdviceUnit(V2):
    """One sentence of the learner's work: where it is, its own result and evidence."""

    index: NonNegativeInt
    # The work version, the sentence's span in that version and the sentence text.
    subject: EvidenceRefV2
    unit_hash: Hash
    status: Literal["completed", "abstained", "failed"]
    label: RelationLabel | None = None
    evidence_ids: tuple[Identifier, ...] = ()
    citations: tuple[EvidenceRefV2, ...] = ()
    reason_code: Identifier | None = None
    # Recognition layer (demo edition): the relation probabilities behind the label.
    probabilities: dict[str, float] | None = Field(default=None, exclude_if=lambda v: v is None)
    confidence: float | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def consistent(self) -> "_AdviceUnit":
        _selected_evidence(self.evidence_ids, self.citations)
        if self.subject.span_start is None:
            raise ValueError("a sentence unit names its span in the work")
        if (self.status == "completed") != (self.label is not None):
            raise ValueError("only a completed sentence carries a label")
        if self.label is None and self.evidence_ids:
            raise ValueError("an unlabelled sentence selects no evidence")
        return self


class _AdviceUnitCounts(V2):
    supported: NonNegativeInt = 0
    contradicted: NonNegativeInt = 0
    insufficient: NonNegativeInt = 0
    abstained: NonNegativeInt = 0
    failed: NonNegativeInt = 0
    # Sentences never sent to the model: too short to judge, or beyond the per-work budget.
    skipped_short: NonNegativeInt = 0
    over_budget: NonNegativeInt = 0


class _AdviceAggregation(V2):
    policy: Identifier
    counts: _AdviceUnitCounts


class _AdviceReconciliation(V2):
    """How a criterion result relates to the verified rule bound and applicability."""

    rule_conflict: bool
    applicability_established: bool


class RegisteredModelAdvice(V2):
    # Any identifier on the wire; the runtime accepts only the canonical rubric criteria.
    criterion: Identifier = "R2.support"
    request_id: Identifier
    job_id: Identifier
    input_hash: Hash | None
    registration: _provenance.RegisteredModelIdentity | None
    status: Literal["completed", "failed", "unavailable", "synthetic_mechanism_only"]
    label: _AdviceLabel | None = None
    evidence_ids: tuple[Identifier, ...] = ()
    citations: tuple[EvidenceRefV2, ...] = ()
    error_code: (
        Literal[
            "model_unavailable",
            "model_load_failed",
            "pretrained_encoder_dependencies_unavailable",
            "model_timeout",
            "model_infrastructure_failed",
            "model_files_changed",
            "model_reference_invalid",
            "evidence_unavailable",
            "model_result_unconfirmed",
            "model_prediction_invalid",
            "claim_not_available",
            "synthetic_mechanism_only",
            "verified_rule_conflict",
            "applicability_not_established",
            "criterion_not_supported_by_model",
            "criterion_rubric_version_mismatch",
            "all_units_abstained",
        ]
        | None
    ) = None
    mode: Literal["advisory"] = "advisory"
    affects_score: Literal[False] = False
    # Relation is the historical task and is not serialized.
    task_type: Literal["relation", "criterion"] = Field(
        default="relation", exclude_if=lambda value: value == "relation"
    )
    units: tuple[_AdviceUnit, ...] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    aggregation: _AdviceAggregation | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    reconciliation: _AdviceReconciliation | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def consistent(self) -> "RegisteredModelAdvice":
        _selected_evidence(self.evidence_ids, self.citations)
        synthetic = self.status == "synthetic_mechanism_only"
        if self.status == "completed":
            if (
                self.registration is None
                or self.registration.scope != "external_candidate"
                or self.input_hash is None
                or self.label is None
                or self.error_code is not None
            ):
                raise ValueError("completed advice needs a registered external result")
        elif not synthetic and (
            self.label is not None
            or self.evidence_ids
            or self.citations
            or any(unit.label is not None for unit in self.units or ())
        ):
            raise ValueError("unavailable or failed advice cannot expose semantic results")
        if synthetic and (
            self.registration is None or self.registration.scope != "synthetic_fixture"
        ):
            raise ValueError("mechanism result needs a synthetic registration")
        domain = _CRITERION_LABELS if self.task_type == "criterion" else _RELATION_LABELS
        if self.label is not None and self.label not in domain:
            raise ValueError("advice label outside its task's label domain")
        if self.registration is not None and self.registration.task_type != self.task_type:
            raise ValueError("advice task differs from its registration task")
        if self.task_type == "criterion":
            if self.units is not None or self.aggregation is not None:
                raise ValueError("sentence units belong to relation advice")
        elif self.reconciliation is not None:
            raise ValueError("rule reconciliation belongs to criterion advice")
        if (self.units is None) != (self.aggregation is None):
            raise ValueError("sentence units and their aggregation occur together")
        if self.units is not None:
            if len({unit.index for unit in self.units}) != len(self.units):
                raise ValueError("duplicate sentence unit")
            observed = {
                "supported": "SUPPORTED",
                "contradicted": "CONTRADICTED",
                "insufficient": "INSUFFICIENT",
            }
            counts = self.aggregation.counts
            if any(
                getattr(counts, name) != sum(unit.label == label for unit in self.units)
                for name, label in observed.items()
            ) or any(
                getattr(counts, name) != sum(unit.status == name for unit in self.units)
                for name in ("abstained", "failed")
            ):
                raise ValueError("aggregation counts must follow the sentence units")
        reconciled = self.reconciliation
        if reconciled is not None and reconciled.rule_conflict and self.label is not None:
            raise ValueError("a result outside the verified rule bound is not adopted")
        if self.error_code == "verified_rule_conflict" and not (
            reconciled is not None and reconciled.rule_conflict
        ):
            raise ValueError("a rule conflict is recorded in its reconciliation")
        if self.error_code == "applicability_not_established" and not (
            reconciled is not None and not reconciled.applicability_established
        ):
            raise ValueError("unestablished applicability is recorded in its reconciliation")
        return self


class FeedbackV2(V2):
    model_advice: tuple[RegisteredModelAdvice, ...] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    # Recognizer records that shaped this feedback (demo edition, contract not re-exported).
    recognition: tuple[RecognitionRecord, ...] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    provenance: _provenance.FeedbackProvenance | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    read_boundaries: tuple[FeedbackReadBoundary, ...] | None = None
    read_projection: Literal["partial"] | None = None
    id: Identifier
    session_id: Identifier
    version: PositiveInt = 1
    subject: ObjectRef
    evaluation: FileRef
    as_of: VersionPoint
    mode: Literal["advisory", "scoring"] = "advisory"
    adoption_record: FileRef | None = None
    items: tuple[FeedbackItem, ...]
    business_response: str
    next_options: tuple[str, ...]
    verified_coverage: Annotated[float, Field(ge=0, le=1)]
    model_coverage: Annotated[float, Field(ge=0, le=1)]
    independent_understanding: Literal["unobserved", "observed_with_evidence"] = "unobserved"
    # None means the historical feedback never recorded this section.
    verified_facts: tuple[VerifiedFactsSnapshot, ...] | None = None
    historical_responsibilities: tuple[HistoricalResponsibilitiesSnapshot, ...] | None = None
    rule_items: tuple[FeedbackItem, ...] | None = None
    basis_refs: tuple[ObjectRef, ...] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    conditions: tuple[str, ...] | None = Field(default=None, exclude_if=lambda value: value is None)
    available_actions: tuple[_OutcomeAction, ...] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    outcomes: tuple[_OutcomeItem, ...] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    preview_language: Literal["zh", "en"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    preview_kind: Literal["rules", "advisory"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    input_refs: tuple[ObjectRef, ...] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    evaluation_as_of: VersionPoint | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    missing_inputs: tuple[str, ...] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    clarification: tuple[str, ...] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    generation_status: (
        Literal["rules_verified", "waiting_model", "advisory", "failed", "unknown"] | None
    ) = Field(default=None, exclude_if=lambda value: value is None)
    preview_conditions: _PreviewConditions | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    # 2026-10-11 decision 5: a range of the rule-anchored part, never a single total.
    score_range: _RuleScoreRange | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def advice_scope(self) -> "FeedbackV2":
        for advice in self.model_advice or ():
            refs = [
                *advice.citations,
                *(ref for unit in advice.units or () for ref in (unit.subject, *unit.citations)),
            ]
            if any(
                ref.session_id != self.session_id or ref.observed_at_seq > self.as_of.business_seq
                for ref in refs
            ):
                raise ValueError("advice citation scope or time mismatch")
        return self

    @model_validator(mode="after")
    def score_range_scope(self) -> "FeedbackV2":
        if self.score_range is not None and sorted(
            row.criterion for row in self.score_range.criteria
        ) != sorted(item.criterion for item in self.rule_items or ()):
            raise ValueError("a score range covers exactly the recorded rule results")
        return self

    @model_validator(mode="after")
    def adoption(self):
        if self.mode == "scoring" and not self.adoption_record:
            raise ValueError("scoring requires independent adoption record")
        if self.read_projection is None:
            if any(
                x.source_snapshot_hash is None
                for x in (*(self.verified_facts or ()), *(self.historical_responsibilities or ()))
            ):
                raise ValueError("stored feedback needs snapshot identity")
            if any(
                r.submitted_reference_hash is None
                for facts in self.verified_facts or ()
                for r in facts.references
            ):
                raise ValueError("stored feedback needs submitted reference identity")
        for section in (self.verified_facts, self.historical_responsibilities):
            if section is None:
                continue
            if len({canonical(x.subject) for x in section}) != len(section):
                raise ValueError("duplicate subject feedback section")
            if any(
                x.subject.session_id != self.session_id
                or not feedback_point_before(x.requested_at, self.as_of)
                for x in section
            ):
                raise ValueError("feedback section scope or time mismatch")
        return self


class TerminalEvaluation(V2):
    subject: ObjectRef
    evaluation: FileRef
    outcome: Literal["satisfied", "unsatisfied", "undetermined"]
    decision: str
    verified_facts: tuple[EvidenceRefV2, ...]
    pending_questions: tuple[str, ...]
    reason: str
