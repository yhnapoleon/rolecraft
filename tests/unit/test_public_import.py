import pytest

from career_lab.datasets.import_contractnli import import_contractnli


def source():
    return {"labels": {"nda-1": {"hypothesis": "Secrets must remain private."}}, "documents": [{"id": 1, "text": "Keep secrets. Public info is exempt.", "spans": [[0,13],[14,36]], "annotation_sets": [{"annotations": {"nda-1": {"choice": "Entailment", "spans": [0]}}}]}]}


def test_offsets_mapping_and_not_minimal_sets():
    data = source()
    data["documents"][0]["spans"][1][1] = len(data["documents"][0]["text"])
    rows = import_contractnli(data, "train", "train")
    assert rows[0]["input"]["candidate_evidence"][0]["text"] == "Keep secrets."
    assert rows[0]["gold"]["label"] == "SUPPORTED"
    assert rows[0]["gold"]["evidence_evaluable"] is False
    assert rows[0]["gold"]["acceptable_evidence_sets"] == []
    assert rows[0]["source_span_ids"] == [0]


def test_source_test_cannot_be_training():
    with pytest.raises(ValueError, match="source split"):
        import_contractnli(source(), "test", "train")


def test_original_whitespace_spans_preserve_offsets():
    data = source()
    data["documents"][0]["spans"] = [[0,13], [13,14]]
    rows = import_contractnli(data, "train", "train")
    assert rows[0]["input"]["candidate_evidence"][1]["text"] == " "
