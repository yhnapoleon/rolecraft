"""Incomplete raw exports remain diagnostic; lineage is checked before isolation."""

from dataclasses import replace
import json
import pytest
from test_w07_pipeline import make_case, isolated_record
from career_lab.contracts.v2.core import digest, ProtocolError
from career_lab.contracts.v2.data import RelationInput
from career_lab.contracts.v2.evaluation import EvidencePackageV2
from career_lab.datasets.v3.export import export_snapshot
from career_lab.datasets.v3.release import publish_release, audit_release
from career_lab.datasets.v3.quality import QualityError, audit_records


def incomplete(tmp_path):
    snapshot, units, policies = make_case(tmp_path)
    raw = units[0].model_input.evidence.model_dump(mode="json", exclude={"input_hash"})
    raw["completeness"] = "missing"
    raw["input_hash"] = digest(raw)
    unit = replace(units[0], model_input=RelationInput(evidence=EvidencePackageV2(**raw)))
    return export_snapshot(snapshot, [unit]), policies


def test_incomplete_input_is_diagnostic_only(tmp_path):
    result, policies = incomplete(tmp_path)
    rid = result.records[0].record_id
    with pytest.raises(ProtocolError) as exc:
        publish_release(
            tmp_path / "train", result, source_root=tmp_path, policies=policies, fixture=True
        )
    assert exc.value.report["excluded"] == [{"record_id": rid, "reason": "input_missing"}]
    m = publish_release(
        tmp_path / "diagnostic",
        result,
        source_root=tmp_path,
        policies=policies,
        fixture=True,
        allow_pending=True,
    )
    assert not m["training_ready"] and m["readiness"]["status"] == "diagnostic"
    assert {"record_id": rid, "reason": "input_missing"} in m["readiness"]["blockers"]
    assert audit_release(tmp_path / "diagnostic")["readiness"] == m["readiness"]
    m["readiness"].update(status="ready", blockers=[])
    m["id"] = digest({k: v for k, v in m.items() if k != "id"})
    (tmp_path / "diagnostic/manifest.json").write_text(json.dumps(m))
    with pytest.raises(ProtocolError, match="readiness"):
        audit_release(tmp_path / "diagnostic")


def test_incomplete_lineage_cannot_hide_cross_partition_dependency(tmp_path):
    result, _ = incomplete(tmp_path)
    first = result.records[0]
    second = isolated_record(first)
    second = second.model_copy(
        update={
            "lineage": second.lineage.model_copy(update={"source_record_ids": (first.record_id,)})
        }
    )
    with pytest.raises(QualityError) as exc:
        audit_records([first, second])
    assert any(e["code"] == "connected_lineage_cross_split" for e in exc.value.report["errors"])


def test_accepted_but_incomplete_model_label_is_still_diagnostic(tmp_path):
    from test_w07_pipeline import create_fixture_batch, FakeModel
    from career_lab.contracts.v2.core import Executor

    result, policies = incomplete(tmp_path)
    batch = create_fixture_batch(
        tmp_path,
        tmp_path / "batch",
        result.records,
        annotation_version="incomplete-model-fixture",
        executor=Executor(id="fixture-test-double", kind="external_agent"),
    )
    labels = batch.run(FakeModel())["annotations"]
    assert labels[0].status == "accepted"
    with pytest.raises(ProtocolError) as exc:
        publish_release(
            tmp_path / "train",
            result,
            source_root=tmp_path,
            policies=policies,
            annotations=labels,
            annotation_artifacts=batch.artifacts(),
            fixture=True,
        )
    assert exc.value.report["excluded"][0]["reason"] == "input_missing"
    manifest = publish_release(
        tmp_path / "diagnostic",
        result,
        source_root=tmp_path,
        policies=policies,
        annotations=labels,
        annotation_artifacts=batch.artifacts(),
        fixture=True,
        allow_pending=True,
    )
    assert manifest["readiness"]["status"] == "diagnostic" and not manifest["training_ready"]
