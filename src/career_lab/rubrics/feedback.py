from career_lab.evidence.assembler import EvidenceAssembler
from career_lab.rubrics.aggregate import aggregate_items
from career_lab.rubrics.checks import run_rule_checks, RULES_REVISION

PRACTICE = {
    "R1": "为新用户组定义目标与验收指标",
    "R2": "用材料核验一个事实判断",
    "R3": "练习有批准例外的资源约束",
    "R4": "补做范围外与政策更新测试",
    "R5": "比较事件前后的方案差异",
    "R6": "补全可执行的观察与退出安排",
}


def build_feedback(store, session_id, submission_id):
    submission = store.get_object(session_id, submission_id, "submission")
    if submission["model_revision"] != RULES_REVISION:
        raise ValueError("historical rules engine unavailable; existing feedback remains readable")
    spec = store.get_spec(session_id)
    assembler = EvidenceAssembler(store)
    items, sources = [], {}
    for criterion in spec.rubric.criteria:
        item = assembler.assemble_item(submission_id, criterion.id, "oracle")
        result = run_rule_checks(item)[0]
        items.append(result)
        sources[criterion.id] = {
            eid: item.source_map[eid].model_dump(mode="json") for eid in result.evidence_ids
        }
    summary = aggregate_items(items, spec.rubric)
    return {
        "submission_id": submission_id,
        "as_of_seq": submission["as_of_seq"],
        "model_revision": RULES_REVISION,
        "rubric_hash": submission["rubric_hash"],
        "summary": summary,
        "items": [i.model_dump(mode="json") for i in items],
        "sources": sources,
        "overflow": any(i.completeness == "overflow" for i in items),
        "practice": sorted(
            {
                PRACTICE[i.criterion_id.split(".")[0]]
                for i in items
                if i.label in {"PARTIAL", "NOT_MET"}
            }
        ),
    }
