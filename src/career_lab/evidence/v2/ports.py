"""Private typed adapter ports, not replacement W01 public schemas.

Facts must come from deterministic/historical services. Neither a learner request
nor a Judge completion can populate these trusted ports directly.
"""
from dataclasses import dataclass
from typing import Protocol, Any

from career_lab.contracts.v2.core import AuthContext, EvidenceRefV2, ObjectRef, VersionPoint
from career_lab.contracts.v2.world import TestResultV2


@dataclass(frozen=True)
class SourceRecord:
    ref: EvidenceRefV2
    text: str
    created_at: VersionPoint


@dataclass(frozen=True)
class VerifiedFact:
    name: str
    value: Any
    sources: tuple[EvidenceRefV2, ...]


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


# Implementation defaults, supplied through the evaluation adapter in production.
# They are not a claim that W02's final rubric has already been frozen.
DEFAULT_POLICIES = (
    CriterionPolicy('R3.capacity','正式开放人数是否符合当时有效容量','capacity',('commitment','result'),True),
    CriterionPolicy('R3.resources','正式承诺的资源和时间是否有依据','resources',('commitment','result'),True),
    CriterionPolicy('R4.functional_tests','是否在相关配置下实际运行过验证；覆盖质量另行核验','tests',('commitment','result'),True),
    CriterionPolicy('R6.comparison','比较内容是否说明方案、替代和取舍；不依赖作品模板',purposes=('option','plan','commitment','result')),
    CriterionPolicy('decision.rationale','判断是否有目标、证据和风险/价值依据；结论枚举不决定质量'),
    CriterionPolicy('decision.follow_up','决定之后的处理、责任和补证安排是否清楚',purposes=('plan','commitment','result')),
    CriterionPolicy('result.claims','结果报告中的声明是否由实际记录支持',purposes=('result',)),
)
