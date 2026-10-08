from career_lab.contracts.evaluation import CandidateEvidence, EvidencePackage, GoldAnnotation
from career_lab.evidence.serializer import seal_input

LABELS = {
    "Entailment": "SUPPORTED",
    "Contradiction": "CONTRADICTED",
    "NotMentioned": "INSUFFICIENT",
}


def import_contractnli(data, source_split, target_split):
    if source_split not in {"train", "dev", "test"} or target_split not in {"train", "dev", "test"}:
        raise ValueError("unknown split")
    if source_split != "train" and target_split != source_split:
        raise ValueError("source split cannot be moved into another split")
    result = []
    for document in data["documents"]:
        text = document["text"]
        spans = document["spans"]
        evidence = []
        for i, (start, end) in enumerate(spans):
            if not 0 <= start < end <= len(text):
                raise ValueError("invalid source span offset")
            evidence.append(CandidateEvidence(id=f"e{i}", version=1, text=text[start:end]))
        for label_id, annotation in document["annotation_sets"][0]["annotations"].items():
            if any(type(i) is not int or i < 0 or i >= len(spans) for i in annotation["spans"]):
                raise ValueError("annotation span index out of range")
            iid = f"contractnli-{document['id']}-{label_id}"
            item = seal_input(
                EvidencePackage(
                    item_id=iid,
                    task_type="relation",
                    criterion=label_id,
                    claim=data["labels"][label_id]["hypothesis"],
                    as_of_seq=0,
                    candidate_evidence=tuple(evidence),
                    completeness="complete",
                )
            )
            gold = GoldAnnotation(
                item_id=iid,
                label=LABELS[annotation["choice"]],
                label_tier="G1",
                acceptable_evidence_sets=(),
                annotation_version="contractnli-original",
                evidence_evaluable=False,
            )
            result.append(
                {
                    "input": item.model_dump(mode="json"),
                    "gold": gold.model_dump(mode="json"),
                    "source_span_ids": annotation["spans"],
                    "source_spans": spans,
                    "lineage": {
                        "item_id": iid,
                        "template_id": f"contract-document-{document['id']}",
                        "root_case_id": f"contract-document-{document['id']}",
                        "parent_id": None,
                        "split": target_split,
                        "source_split": source_split,
                        "language": "en",
                        "source": "contractnli",
                    },
                }
            )
    return result
