"""Small factual detectors over explicitly adapted event records.

DiagnosticEvent is an internal adapter, not a replacement public trajectory
schema. W09/W01 integration must populate digests and visibility from real logs.
"""
from dataclasses import dataclass, field, asdict
from typing import Literal

from career_lab.contracts.v2 import EvidenceRefV2, FileRef, Diagnosis, ProtocolError, digest


@dataclass(frozen=True)
class DiagnosticEvent:
    id: str
    seq: int
    session_id: str
    actor_id: str
    operation: str
    visible_to: tuple[str, ...]
    outcome: Literal["success", "failed", "unknown"]
    evidence: tuple[EvidenceRefV2, ...] = ()
    input_hash: str | None = None
    visible_state_hash: str | None = None
    error_code: str | None = None
    error_origin: Literal["input", "system", "unknown"] = "unknown"
    purpose: str = ""
    # No prompt facts or hidden-world fields are accepted here.


@dataclass(frozen=True)
class VersionChange:
    object_id: str
    kind: str
    version: int
    seq: int
    source: EvidenceRefV2
    visible_to: tuple[str, ...]


@dataclass(frozen=True)
class Finding:
    id: str
    kind: str
    first_seq: int
    event_ids: tuple[str, ...]
    observation: str
    interpretation: str
    uncertainty: str
    source_refs: tuple[EvidenceRefV2, ...]
    confidence_source: str = "programmatic_log_fact"
    ability_score: None = None
    suggested_intervention: None = None

    def as_diagnosis(self, trajectory: FileRef, evaluation: FileRef):
        return Diagnosis(trajectory=trajectory, event_facts=self.source_refs,
            interpretation=self.interpretation, uncertainty=self.uncertainty,
            alternatives=("核对工作目的及是否存在等价证据；不据此推断个人能力。",),
            evaluation=evaluation)


def diagnose(events, *, session_id, viewer_id, changes=(), failure_threshold=3, logs_complete=True):
    if not 2 <= failure_threshold <= 20:
        raise ValueError("failure threshold must be 2..20")
    events = tuple(events)
    if len({e.id for e in events}) != len(events) or any(e.session_id != session_id for e in events):
        raise ProtocolError("diagnostic_event_identity_mismatch")
    if any(e.seq < 0 for e in events) or [e.seq for e in events] != sorted(e.seq for e in events):
        raise ProtocolError("diagnostic_event_order")
    if any(e.outcome not in {"success", "failed", "unknown"} or e.error_origin not in {"input", "system", "unknown"} for e in events):
        raise ProtocolError("diagnostic_event_invalid")
    findings = []
    visible = [e for e in events if viewer_id in e.visible_to]
    seen = {}
    failures = []
    def emit(kind, group, observation, uncertainty, refs=None):
        group = tuple(group)
        source_refs = tuple(refs) if refs is not None else tuple(r for e in group for r in e.evidence)
        if any(r.session_id != session_id or r.observed_at_seq > group[-1].seq for r in source_refs):
            raise ProtocolError("diagnostic_evidence_identity_mismatch")
        findings.append(Finding(id=digest([kind, [e.id for e in group], [r.model_dump(mode="json") for r in source_refs]]), kind=kind,
            first_seq=group[0].seq, event_ids=tuple(e.id for e in group),
            observation=observation, interpretation="需要结合目的与可获信息核对，未作能力判断。",
            uncertainty=uncertainty, source_refs=source_refs))
    for event in visible:
        if event.operation in {"read_material", "test_assistant"} and event.input_hash and event.visible_state_hash:
            key = (event.actor_id, event.operation, event.input_hash, event.visible_state_hash)
            if key in seen:
                emit("repeated_input", (seen[key], event),
                     "相同可见状态及输入指纹下再次读取或测试。",
                     "可能是来源核对、稳定性复测或恢复；重复事实不等于低效。")
            seen[key] = event
        if event.outcome == "failed" and event.input_hash:
            key = (event.actor_id, event.operation, event.input_hash, event.error_code, event.error_origin)
            if failures and failures[-1][0] != key:
                failures = []
            failures.append((key, event))
            if len(failures) == failure_threshold:
                emit("repeated_failure", [x[1] for x in failures],
                     f"当前可见记录中，相同操作连续失败{failure_threshold}次；错误来源记录为{event.error_origin}。",
                     "系统失败、输入问题和来源未知分别保留，不据失败次数扣用户能力。")
        else:
            failures = []
        for ref in event.evidence:
            relevant = [c for c in changes if c.kind == ref.kind and c.object_id == ref.object_id
                        and viewer_id in c.visible_to and c.seq <= event.seq and c.version > ref.version]
            if relevant:
                change = max(relevant, key=lambda c: (c.seq, c.version))
                emit("older_evidence_version", (event,), "已可见新版本后引用了较早版本。",
                     "只有直接版本关系得到核对；是否影响该测试或是否用于历史比较仍需检查。",
                     refs=(ref, change.source))
    if not logs_complete and visible:
        emit("incomplete_trace", (visible[-1],), "输入明确标记日志不完整。",
             "不能将缺日志解释为用户未行动，也不能据此判断提早交付。")
    return tuple(findings)
