"""Private typed adapter ports, not replacement W01 public schemas.

Facts must come from deterministic/historical services. Neither a learner request
nor a Judge completion can populate these trusted ports directly.
"""
from dataclasses import dataclass
from typing import Protocol, Any, Literal

from career_lab.contracts.v2.core import AuthContext, EvidenceRefV2, ObjectRef, VersionPoint, Executor
from career_lab.contracts.v2.world import TestResultV2


@dataclass(frozen=True)
class StructuredDecision:
    """Trusted structured-field declaration bound to this exact work version.

    This is an adapter input, never inferred from free text or model output.
    """
    value: str
    subject: ObjectRef
    declared_at: VersionPoint
    source: EvidenceRefV2


@dataclass(frozen=True)
class SourceRecord:
    ref: EvidenceRefV2
    text: str
    created_at: VersionPoint | None
    declared_refs: tuple[EvidenceRefV2, ...] = ()
    author: Executor | None = None
    executor: Executor | None = None
    adopter: Executor | None = None
    activity_kind: str | None = None
    activity_target: ObjectRef | None = None
    actor_id: str | None = None
    structured_decision: StructuredDecision | None = None


@dataclass(frozen=True)
class VerifiedFact:
    name: str
    value: Any
    sources: tuple[EvidenceRefV2, ...]


@dataclass(frozen=True)
class ResponsibilityFact:
    """Source-backed historical record, not a launch obligation flag.

    scope binds exact subject versions. Occurrence and validity are checked at
    the subject anchor, never at a later review-request time. Actual values must
    use actual_* facts; intended configuration does not prove actual execution.
    """
    criterion: str
    kind: Literal['actual_action', 'commitment', 'completion_claim', 'unknown']
    occurred_at: VersionPoint
    valid_from: VersionPoint
    scope: tuple[ObjectRef, ...]
    sources: tuple[EvidenceRefV2, ...]
    facts: tuple[VerifiedFact, ...] = ()
    valid_until: VersionPoint | None = None
    state: Literal['active', 'withdrawn', 'unknown'] = 'active'
    actor_id: str | None = None
    executor: Executor | None = None


@dataclass(frozen=True)
class ActivityRecord:
    ref: EvidenceRefV2
    kind: Literal['material_read', 'test_run', 'question_sent', 'reply_received', 'learner_displayed']
    occurred_at: VersionPoint
    executor: Executor
    actor_id: str
    target: ObjectRef | None = None
    counterparty: str | None = None


@dataclass(frozen=True)
class ActivityLedger:
    records: tuple[ActivityRecord, ...] = ()
    # Completeness is an assertion of the trusted ledger adapter for this exact
    # authorized history window, not inferred from an empty returned list.
    completeness: tuple[tuple[str, bool], ...] = ()
    covered_from: VersionPoint | None = None
    covered_through: VersionPoint | None = None
    captured_at: VersionPoint | None = None


@dataclass(frozen=True)
class RuleSnapshot:
    as_of: VersionPoint
    facts: tuple[VerifiedFact, ...] = ()
    logs_complete: bool = False
    tests: tuple[TestResultV2, ...] = ()
    test_refs: tuple[EvidenceRefV2, ...] = ()
    config_version: int | None = None
    technical_failures: tuple[str, ...] = ()
    business_response: str = ''
    business_response_refs: tuple[EvidenceRefV2, ...] = ()
    responsibilities: tuple[ResponsibilityFact, ...] = ()


class EvidenceReader(Protocol):
    def read(self, auth: AuthContext, ref: ObjectRef, as_of: VersionPoint) -> SourceRecord:
        """Return exact authorized historical content, without gold/future data.

        Missing records raise KeyError; forbidden/cross-session/version conflicts
        raise ProtocolError. Do not replace an unavailable old version by latest.
        """


@dataclass(frozen=True)
class CriterionPolicy:
    id: str
    description: str
    mechanism: str = 'semantic'
    purposes: tuple[str, ...] = ('exploration','option','plan','commitment','result')
    launch_only: bool = False

    def to_dict(self):
        return {'id':self.id,'description':self.description,'mechanism':self.mechanism,
                'purposes':list(self.purposes),'launch_only':self.launch_only}


# Legacy seven-item policy set retained for existing fixtures and bindings.
# New rubric-v2 sessions must explicitly install/load rubrics.v4.rubric_v2;
# never substitute this set for that 14-item frozen candidate.
DEFAULT_POLICIES = (
    CriterionPolicy('R3.capacity','正式开放人数是否符合当时有效容量','capacity',('commitment','result'),True),
    CriterionPolicy('R3.resources','正式承诺的资源和时间是否有依据','resources',('commitment','result'),True),
    CriterionPolicy('R4.functional_tests','是否在相关配置下实际运行过验证；覆盖质量另行核验','tests',('commitment','result'),True),
    CriterionPolicy('R6.comparison','比较内容是否说明方案、替代和取舍；不依赖作品模板',purposes=('option','plan','commitment','result')),
    CriterionPolicy('decision.rationale','判断是否有目标、证据和风险/价值依据；结论枚举不决定质量'),
    CriterionPolicy('decision.follow_up','决定之后的处理、责任和补证安排是否清楚',purposes=('plan','commitment','result')),
    CriterionPolicy('result.claims','结果报告中的声明是否由实际记录支持',purposes=('result',)),
)
