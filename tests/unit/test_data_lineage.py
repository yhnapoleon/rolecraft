import json

import pytest

from career_lab.datasets.release import build_release, audit_release, audit_records


def test_build_real_release_with_gold_sidecars(tmp_path):
    manifest = build_release(tmp_path / "v1")
    report = audit_release(manifest)
    assert report["valid"]
    assert report["samples"] == 90
    assert report["templates"] == 6
    test = (manifest.parent / "splits/test.inputs.jsonl").read_text(encoding="utf-8")
    assert "acceptable_evidence_sets" not in test
    assert '"label"' not in test


def test_template_and_parent_cannot_cross_splits():
    rows = [{"item_id": "a", "template_id": "t", "root_case_id": "r", "split": "train", "parent_id": None},
            {"item_id": "b", "template_id": "t", "root_case_id": "r", "split": "test", "parent_id": "a"}]
    with pytest.raises(ValueError, match="split"):
        audit_records(rows)
