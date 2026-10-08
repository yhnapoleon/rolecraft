from career_lab.contracts.evaluation import CandidateEvidence, EvidencePackage, GoldAnnotation
from career_lab.evidence.serializer import seal_input

TEMPLATES = {
    "capacity": "train",
    "resource_sum": "train",
    "deadline": "train",
    "approved_capacity": "dev",
    "index_version": "dev",
    "scope_membership": "test",
}


def generate_records(per_template=15):
    rows = []
    for template, split in TEMPLATES.items():
        for i in range(per_template):
            n = 20 + i
            label = ("SUPPORTED", "CONTRADICTED", "INSUFFICIENT")[i % 3]
            if template == "capacity":
                claim = f"{n}人试点不超过当前获批上限。"
                evidence = f"当前获批上限为{n if label == 'SUPPORTED' else n - 1}人；批准登记完整且无额外批准。"
            elif template == "resource_sum":
                claim = f"开发{n}人日并测试2人日的方案没有超过预算。"
                evidence = f"有效预算为{n + 2 if label == 'SUPPORTED' else n + 1}人日。开发和测试成本需相加。"
            elif template == "deadline":
                claim = f"第{n}天交付没有超过最新期限。"
                evidence = f"有效交付期限为第{n if label == 'SUPPORTED' else n - 1}天，延期登记完整且没有新批准。"
            elif template == "approved_capacity":
                claim = f"{n}人试点符合扩容后的限制。"
                evidence = f"原上限10人；主管已批准新上限{n + 1 if label == 'SUPPORTED' else n - 1}人，新批准已生效。"
            elif template == "index_version":
                claim = f"源文档v{n}的内容已经包含在索引中。"
                evidence = (
                    f"版本完整且按序递增；当前索引版本为v{n if label == 'SUPPORTED' else n - 1}。"
                )
            else:
                claim = f"编号{n}的政策属于当前可回答范围。"
                evidence = f"范围清单完整，编号{n}的政策{'包含在' if label == 'SUPPORTED' else '被排除出'}当前可回答范围。"
            if label == "INSUFFICIENT":
                evidence = f"案例编号{i}：该判断需要的有效约束或记录尚未提供，现有材料无法确定。"
            iid = f"{template}-{i:03d}"
            package = seal_input(
                EvidencePackage(
                    item_id=iid,
                    task_type="relation",
                    criterion=template,
                    claim=claim,
                    as_of_seq=0,
                    candidate_evidence=(CandidateEvidence(id="e1", version=1, text=evidence),),
                    completeness="complete",
                )
            )
            gold = GoldAnnotation(
                item_id=iid,
                label=label,
                label_tier="G0",
                acceptable_evidence_sets=(("e1",),),
                missing_requirement="required constraint" if label == "INSUFFICIENT" else None,
                annotation_version="programmatic-v1",
                verifier_id=template + "-v1",
            )
            rows.append(
                {
                    "input": package.model_dump(mode="json"),
                    "gold": gold.model_dump(mode="json"),
                    "lineage": {
                        "item_id": iid,
                        "template_id": template,
                        "root_case_id": iid,
                        "parent_id": None,
                        "split": split,
                        "language": "zh",
                        "source": "synthetic-g0",
                        "source_split": split,
                    },
                }
            )
    return rows
