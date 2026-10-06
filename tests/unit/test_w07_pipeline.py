"""Synthetic module fixtures; none of these tests is a live W02/model/human run."""
from dataclasses import replace
from pathlib import Path
import json
import sys
import subprocess
import threading

import httpx
import pytest
from pydantic import ValidationError

from career_lab.contracts.v2.core import (
    ObjectRef, EvidenceRefV2, VersionPoint, SourceIdentity, Executor, FileRef, digest, ProtocolError,
)
from career_lab.contracts.v2.evaluation import CandidateEvidenceV2, EvidencePackageV2
from career_lab.contracts.v2.data import (
    RelationInput, CriterionInput, TrajectoryInput, DecisionPointInput, ObservedStep, ActionProposal,
    Lineage, Provenance, AnnotationDecision, AnnotationV2, DatasetRecordV2,
)
from career_lab.datasets.v3.export import FrozenSnapshot, SourceObject, ExportUnit, export_snapshot
from career_lab.datasets.v3.common import json_bytes, sha, immutable_directory, check_payload
from career_lab.datasets.v3.quality import audit_records, QualityError
from career_lab.datasets.v3.labeling import AnnotationBatch, LabelResult, OpenAICompatibleExecutor
from career_lab.datasets.v3.release import save_export, load_export, publish_release, audit_release
from career_lab.datasets.v3.g0 import verify_numeric

BASE = "80cf1f6189cd25610d609f44283ff9668582d759"


def package(task_type, *, claim="capacity <= 30", refs=None, point=None, **changes):
    point = point or VersionPoint(business_seq=4, workspace_revision=2, storage_revision=7)
    refs = refs or [EvidenceRefV2(session_id="session1", kind="document", object_id=x, version=1,
                               observed_at_seq=1) for x in ("capacity-positive-authoring", "second-source")]
    body = dict(schema_version=2, item_id="author-item", task_type=task_type,
        criterion="R1" if task_type == "criterion" else None, claim=claim,
        subjects=[refs[0].model_dump(mode="json")], purpose="exploration", as_of=point.model_dump(mode="json"),
        applicability="undetermined", candidate_evidence=[
            CandidateEvidenceV2(id="answer-supported", text='{"capacity": 30}', ref=refs[0]).model_dump(mode="json"),
            CandidateEvidenceV2(id="candidate2", text="stable FAQ evidence", ref=refs[1]).model_dump(mode="json")],
        rule_context={}, rule_bound=None, completeness="complete", dropped_refs=[], missing_refs=[])
    body.update(changes)
    return EvidencePackageV2(**body, input_hash=digest(body))


def make_case(tmp_path, *, origin="fixture"):
    point = VersionPoint(business_seq=4, workspace_revision=2, storage_revision=7)
    evidence = package("relation", point=point)
    sources = tuple(SourceObject(ObjectRef.model_validate({k: c.ref.model_dump(mode="json")[k] for k in ObjectRef.model_fields}),
        c.text, VersionPoint(business_seq=1, workspace_revision=0, storage_revision=1), ("learner",),validity_known=True) for c in evidence.candidate_evidence)
    (tmp_path / "source.json").write_bytes(json_bytes({"origin": "unit-fixture" if origin=="fixture" else origin, "session": "session1", "test_double":True}))
    source_ref = FileRef(path="source.json", sha256=sha((tmp_path / "source.json").read_bytes()))
    identity = SourceIdentity(base_commit=BASE, source_digest=digest("fixture-source"))
    provenance = Provenance(command="unit fixture; not a business execution", source=identity,
        executor=Executor(id="fixture-system", kind="system"), actual_sources=(source_ref,),
        captured_at="2026-10-06T12:20:00Z")
    lineage = Lineage(structure_id="fixture-structure", component_id="fixture-component", session_id="session1",
                      run_id="fixture-run", fact_root_ids=("fixture-root",))
    observation_ref = EvidenceRefV2(session_id="session1", kind="event", object_id="observed-test-result", version=1, observed_at_seq=4)
    sources += (SourceObject(ObjectRef(session_id="session1", kind="event", object_id="observed-test-result", version=1),
                            "actual fixture observation", point, ("learner",),validity_known=True),)
    step = ObservedStep(request_id="fixture-step-request",id="step-source", action="test", as_of=point, observations=("actual fixture observation",),
                        evidence_refs=(*tuple(c.ref for c in evidence.candidate_evidence), observation_ref), outcome="success")
    models = [RelationInput(evidence=evidence), CriterionInput(evidence=package("criterion", claim="可以有依据暂缓或no_go", purpose="draft")),
        TrajectoryInput(task="inspect sequence", steps=(step,), question="what is observed?", logs_complete=True),
        DecisionPointInput(task="choose information", as_of=point, observed_steps=(step,), candidates=(
            ActionProposal(id="a1", tool="read_material", arguments={"material_id": "brief"}, purpose="clarify"),
            ActionProposal(id="a2", tool="test", arguments={}, purpose="verify")), question="what changes?")]
    units = [ExportUnit(family, model, lineage, provenance,evaluation_time_known=True) for family, model in zip(("relation", "criterion", "trajectory", "acquisition"), models, strict=True)]
    snapshot = FrozenSnapshot("session1", "learner", point, sources, identity.source_digest, origin)
    policies = {"source.json": {"sha256": source_ref.sha256, "review_status": "approved"}}
    return snapshot, units, policies


def decision(request, label="SUPPORTED"):
    task = request["model_input"]["task_type"]
    labels = {"relation": label, "criterion": "NOT_APPLICABLE", "acquisition": "undetermined", "trajectory_diagnosis": "insufficient"}
    return AnnotationDecision(task_type=task, label=labels[task], applicability="not_applicable" if task == "criterion" else "undetermined",
        evidence_ids=("e1",) if task == "relation" else (), acceptable_evidence_sets=(("e1",),) if task == "relation" else (),
        evidence_evaluable=task == "relation", missing_reason="not observed" if task in {"acquisition", "trajectory_diagnosis"} else None)



def label_result(request,raw,revision="test-double-model-v1",provider="unit-test-double",usage=None):
    return LabelResult(raw,revision,provider,{} if usage is None else usage,
        invocation_id="test-invocation:"+request["request_id"],context_id=request["requested_context_id"],independence_method="fresh_context")


class FakeModel:
    """Test double, explicitly named in all receipt model/provider identities."""
    def __init__(self, labels=None):
        self.calls = []
        self.labels = labels or {}

    def __call__(self, request):
        self.calls.append(request)
        d = decision(request, self.labels.get(request["phase"], "SUPPORTED"))
        return label_result(request,d.model_dump_json(),usage={"cost":0.0})



def create_fixture_batch(source_root, path, records, **kwargs):
    policies = {"source.json": {"sha256": sha((source_root / "source.json").read_bytes()), "review_status": "approved"}}
    return AnnotationBatch.create(path, records, source_root=source_root, policies=policies, **kwargs)


def batch_for(tmp_path, family="relation"):
    snapshot, units, policies = make_case(tmp_path)
    result = export_snapshot(snapshot, [u for u in units if u.family == family])
    batch = create_fixture_batch(tmp_path, tmp_path / "batch", result.records, annotation_version="test-annotation-v1",
        executor=Executor(id="fake-agent", kind="external_agent"))
    return batch, result, policies


def signed(request, raw=None):
    from career_lab.datasets.v3.attestation import RECEIPT_FIELDS
    result = {k: request[k] for k in (*RECEIPT_FIELDS, "request_hash")}
    return result | {"raw_output": raw if raw is not None else decision(request).model_dump_json(),
        "model_revision": "offline-test-double-v1", "provider": "offline-unit-test", "usage": {},
        "invocation_id":"offline-test:"+request["request_id"],"context_id":request["requested_context_id"],"independence_method":"fresh_context"}


def test_four_family_export_is_stable_and_does_not_modify_snapshot(tmp_path):
    snapshot, units, _ = make_case(tmp_path)
    first = export_snapshot(snapshot, units)
    second = export_snapshot(snapshot, units)
    assert not first.quarantined
    assert len(first.records) == 4
    assert first == second
    assert {r.model_input.task_type for r in first.records} == {"relation", "criterion", "trajectory_diagnosis", "acquisition"}
    assert first.records[1].model_input.evidence.purpose == "draft"
    assert "no_go" in first.records[1].model_input.evidence.claim
    record = first.records[0]
    assert "capacity-positive-authoring" not in json_bytes(record.model_input).decode()
    assert record.model_input.evidence.candidate_evidence[0].id == "e1"
    assert set(first.source_maps[record.record_id]["candidate_ids"].values()) == {"answer-supported","candidate2"}
    assert snapshot.objects[0].ref.object_id == "capacity-positive-authoring"


@pytest.mark.parametrize("mutation,reason", [
    ("private", "unauthorized_source_reference"), ("future_object", "future_source_reference"),
    ("cross_session", "cross_session_reference"), ("missing", "unresolved_source_reference"),
    ("wrong_text", "candidate_text_source_mismatch"), ("leak", "model_input_metadata_leak"),
    ("mixed_point", "future_evaluation_frame"), ("future_subject", "invalid_source_or_schema"),
])
def test_export_quarantines_bad_source(tmp_path, mutation, reason):
    snapshot, units, _ = make_case(tmp_path)
    unit = units[0]
    data = unit.model_input.model_dump(mode="json")
    if mutation == "private":
        snapshot = replace(snapshot, objects=(replace(snapshot.objects[0], readers=()), *snapshot.objects[1:]))
        # Source text leakage check can reject even earlier.
        reason = "private_content_in_input"
    elif mutation == "future_object":
        snapshot = replace(snapshot, objects=(replace(snapshot.objects[0], available_at=VersionPoint(business_seq=5, workspace_revision=2, storage_revision=8)), *snapshot.objects[1:]))
    elif mutation == "missing":
        snapshot = replace(snapshot, objects=snapshot.objects[1:])
    elif mutation == "cross_session":
        data["evidence"]["subjects"][0]["session_id"] = "other"
    elif mutation == "wrong_text":
        data["evidence"]["candidate_evidence"][0]["text"] = "model invented success"
    elif mutation == "leak":
        data["evidence"]["rule_context"] = {"nested": {"gold_label": "SUPPORTED"}}
    elif mutation == "mixed_point":
        data["evidence"]["as_of"]["workspace_revision"] = 3
    elif mutation == "future_subject":
        data["evidence"]["subjects"][0]["observed_at_seq"] = 5
    data["evidence"]["input_hash"] = digest({k: v for k, v in data["evidence"].items() if k != "input_hash"})
    result = export_snapshot(snapshot, [replace(unit, model_input=data)])
    assert not result.records
    assert result.quarantined[0]["reason"] == reason


def test_config_c0_and_stale_reference_retained(tmp_path):
    snapshot, units, _ = make_case(tmp_path)
    ref = EvidenceRefV2(session_id="session1", kind="config", object_id="cfg", version=1, config_version=0,
                         observed_at_seq=1, valid_until_seq=3)
    source = SourceObject(ObjectRef(session_id="session1", kind="config", object_id="cfg", version=1, config_version=0),
                          '{"capacity": 30}', snapshot.objects[0].available_at, ("learner",),validity_known=True,valid_until_seq=3)
    refs = [ref, units[0].model_input.evidence.candidate_evidence[1].ref]
    unit = replace(units[0], model_input=RelationInput(evidence=package("relation", refs=refs)))
    result = export_snapshot(replace(snapshot, objects=(source, snapshot.objects[1])), [unit])
    assert not result.quarantined
    output = next(c.ref for c in result.records[0].model_input.evidence.candidate_evidence if c.ref.kind=="config")
    assert output.config_version == 0 and output.version == 1 and output.valid_until_seq == 3
    annotation = verify_numeric(result.records[0])
    assert annotation.final.label == "INSUFFICIENT"  # stale is retained, not current proof


def test_quote_check_and_hidden_probe(tmp_path):
    snapshot, units, _ = make_case(tmp_path)
    data = units[0].model_input.model_dump(mode="json")
    data["evidence"]["subjects"][0].update(span_start=0, span_end=3, quote="bad")
    data["evidence"]["input_hash"] = digest({k: v for k, v in data["evidence"].items() if k != "input_hash"})
    result = export_snapshot(snapshot, [replace(units[0], model_input=data)])
    assert result.quarantined[0]["reason"] == "source_quote_mismatch"
    for value in ({"gold": "x"}, {"arguments": {"hidden_probes": "x"}}):
        with pytest.raises(ProtocolError):
            check_payload(value)


def isolated_record(record, **changes):
    line = record.lineage.model_dump(mode="json") | {"structure_id": "separate", "component_id": "separate", "fact_root_ids": [], "session_id": "other", "run_id": "other"}
    raw = record.model_dump(mode="json") | {"record_id": "other", "lineage": line, "split": "dev"}
    raw.update(changes)
    return DatasetRecordV2.model_validate(raw)


@pytest.mark.parametrize("link", ["structure_id", "component_id", "fact_root_ids", "session_id", "run_id", "source_record_ids", "derivation_ids"])
def test_transitive_lineage_cannot_cross_splits(tmp_path, link):
    snapshot, units, _ = make_case(tmp_path)
    first = export_snapshot(snapshot, units[:1]).records[0]
    second = isolated_record(first)
    line = second.lineage.model_dump(mode="json")
    if link == "source_record_ids":
        line[link] = [first.record_id]
    elif link == "derivation_ids":
        first = first.model_copy(update={"lineage": first.lineage.model_copy(update={link: ("shared-translation",)})})
        line[link] = ["shared-translation"]
    else:
        line[link] = getattr(first.lineage, link)
    second = second.model_copy(update={"lineage": Lineage.model_validate(line)})
    with pytest.raises(QualityError) as exc:
        audit_records([first, second])
    assert any(e["code"] == "connected_lineage_cross_split" for e in exc.value.report["errors"])


def test_unknown_ancestor_cycle_and_duplicate_screening(tmp_path):
    snapshot, units, _ = make_case(tmp_path)
    first = export_snapshot(snapshot, units[:1]).records[0]
    bad = first.model_copy(update={"lineage": first.lineage.model_copy(update={"source_record_ids": ("absent",)})})
    with pytest.raises(QualityError, match="quality"):
        audit_records([bad])
    bad = first.model_copy(update={"lineage": first.lineage.model_copy(update={"source_record_ids": (first.record_id,)})})
    with pytest.raises(QualityError) as exc:
        audit_records([bad])
    assert exc.value.report["errors"][0]["code"] == "lineage_cycle"
    with pytest.raises(QualityError) as exc:
        audit_records([first, isolated_record(first)])
    assert any(e["code"] == "duplicate_input_cross_split" for e in exc.value.report["errors"])


def test_g0_is_narrow_and_does_not_claim_judgment(tmp_path):
    snapshot, units, _ = make_case(tmp_path)
    record = export_snapshot(snapshot, units[:1]).records[0]
    verified = verify_numeric(record)
    assert verified.label_tier == "G0" and verified.final.label == "SUPPORTED"
    with pytest.raises(ProtocolError, match="scope"):
        verify_numeric(export_snapshot(snapshot, units[1:2]).records[0])


def test_two_pass_model_batch_resumes_and_keeps_originals(tmp_path):
    batch, result, _ = batch_for(tmp_path)
    model = FakeModel()
    output = batch.run(model)
    assert len(model.calls) == 2
    a = output["annotations"][0]
    assert a.status == "accepted" and a.label_tier == "G2v"
    assert a.passes[0].evidence_order != a.passes[1].evidence_order
    assert model.calls[0]["payload_hash"] != model.calls[1]["payload_hash"]
    assert all(p.raw_output and p.model_revision.startswith("test-double") for p in a.passes)
    reloaded = AnnotationBatch(batch.path)
    reloaded.run(model)
    assert len(model.calls) == 2
    assert reloaded.annotation(result.records[0].record_id) == a
    for request in model.calls:
        text = json_bytes(request["model_input"]).decode()
        assert "label_ref" not in text and "acceptable_evidence_sets" not in text and "label_tier" not in text


def test_disagreement_calls_third_independent_pass(tmp_path):
    batch, _, _ = batch_for(tmp_path)
    model = FakeModel({2: "CONTRADICTED"})
    a = batch.run(model)["annotations"][0]
    assert len(model.calls) == 3
    assert a.final.label == "SUPPORTED" and a.adjudication_ref
    assert len(a.passes) == 3
    assert a.passes[0].decision != a.passes[1].decision
    assert a.adjudication_ref.path in batch.artifacts()


@pytest.mark.parametrize("bad", ["", "not JSON", '{"label":"SUPPORTED"}', "invalid-reference", "timeout"])
def test_bad_outputs_pending_and_retry_does_not_repeat_success(tmp_path, bad):
    batch, _, _ = batch_for(tmp_path)
    called = []
    def model(request):
        called.append(request["phase"])
        if request["phase"] == 1:
            if bad == "timeout":
                raise TimeoutError("test")
            raw = bad
            if bad == "invalid-reference":
                raw = decision(request).model_copy(update={"evidence_ids": ("nonexistent",)}).model_dump_json()
            return LabelResult(raw, "test-double-v1", "unit-test", {})
        return FakeModel()(request)
    output = batch.run(model)
    assert output["annotations"][0].status == "pending"
    assert output["annotations"][0].final is None
    fixed = FakeModel()
    batch.run(fixed, retry_failed=True)
    assert [r["phase"] for r in fixed.calls] == [1]
    assert batch.usage()["attempts"] == 3


def test_uncertain_dispatch_never_automatically_repeats(tmp_path):
    batch, result, _ = batch_for(tmp_path)
    rid = result.records[0].record_id
    batch.claim(rid, 1)
    model = FakeModel()
    result = AnnotationBatch(batch.path).run(model)
    assert not model.calls
    assert result["blocked"][0]["code"] == "dispatch_outcome_unknown"
    assert result["usage"]["uncertain"] == 1


def test_signed_offline_receipt_idempotency_and_drift(tmp_path):
    batch, result, _ = batch_for(tmp_path)
    request = batch.claim(result.records[0].record_id, 1)
    receipt = signed(request)
    with pytest.raises(ProtocolError, match="mismatch"):
        batch.receive(receipt | {"input_hash": "0" * 64})
    first = batch.receive(receipt)
    assert batch.receive(receipt) == first
    with pytest.raises(ProtocolError, match="conflict"):
        batch.receive(receipt | {"raw_output": "{}"})


def test_concurrent_claim_does_not_duplicate_dispatch(tmp_path):
    batch, result, _ = batch_for(tmp_path)
    results = []
    def claim():
        try:
            results.append(batch.claim(result.records[0].record_id, 1))
        except ProtocolError as exc:
            results.append(exc.code)
    threads = [threading.Thread(target=claim) for _ in range(2)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert sum(isinstance(x, dict) for x in results) == 1
    assert "dispatch_outcome_unknown" in results


def test_c4_trajectory_preserves_order_with_independent_contexts(tmp_path):
    batch, _, _ = batch_for(tmp_path, "trajectory")
    output = batch.run(FakeModel())
    assert output["annotations"][0].status == "accepted"
    assert not output["blocked"]
    passes=output["annotations"][0].passes
    assert passes[0].evidence_order==passes[1].evidence_order and passes[0].context_id!=passes[1].context_id


def test_batch_does_not_open_test_or_impersonate_human(tmp_path):
    batch, result, _ = batch_for(tmp_path)
    record = result.records[0].model_copy(update={"split": "test"})
    with pytest.raises(ProtocolError, match="sealed"):
        create_fixture_batch(tmp_path, tmp_path / "sealed", [record], annotation_version="v1", executor=Executor(id="a", kind="external_agent"))
    with pytest.raises(ProtocolError, match="executor"):
        create_fixture_batch(tmp_path, tmp_path / "human", result.records, annotation_version="v1", executor=Executor(id="human", kind="human"))


def test_api_adapter_uses_only_model_payload_and_actual_identity(tmp_path):
    batch, result, _ = batch_for(tmp_path)
    request = batch.claim(result.records[0].record_id, 1)
    observed = []
    def transport(req):
        body = json.loads(req.content)
        observed.append(body)
        assert json.loads(body["messages"][1]["content"]) == request["model_input"]
        assert "label_ref" not in body["messages"][1]["content"]
        return httpx.Response(200, json={"model": "reported-test-model-revision", "choices": [{"message": {"content": decision(request).model_dump_json()}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}})
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        out = OpenAICompatibleExecutor(client, "https://test.invalid/chat/completions", "requested-model", "fixture-key")(request)
    assert out.model_revision == "reported-test-model-revision" and len(observed) == 1


def test_export_save_load_and_fixture_publication_are_immutable(tmp_path):
    snapshot, units, policies = make_case(tmp_path)
    result = export_snapshot(snapshot, units)
    save_export(tmp_path / "export", result)
    assert load_export(tmp_path / "export") == result
    with pytest.raises(ProtocolError, match="immutable"):
        save_export(tmp_path / "export", result)
    with pytest.raises(ProtocolError, match="fixture"):
        publish_release(tmp_path / "invalid", result, source_root=tmp_path, policies=policies, allow_pending=True)
    manifest = publish_release(tmp_path / "release", result, source_root=tmp_path, policies=policies, fixture=True, allow_pending=True)
    assert not manifest["training_ready"] and not manifest["confirmatory"]
    assert audit_release(tmp_path / "release")["records"] == 4
    for path in (tmp_path / "release/inputs").glob("*.json"):
        payload = json.loads(path.read_text())
        check_payload(payload)
    with pytest.raises(ProtocolError, match="immutable"):
        publish_release(tmp_path / "release", result, source_root=tmp_path, policies=policies, fixture=True, allow_pending=True)


def test_accepted_adjudicated_release_and_file_drift(tmp_path):
    batch, result, policies = batch_for(tmp_path)
    annotations = batch.run(FakeModel({2: "CONTRADICTED"}))["annotations"]
    publish_release(tmp_path / "release", result, source_root=tmp_path, policies=policies, annotations=annotations,
                    annotation_artifacts=batch.artifacts(), fixture=True)
    assert audit_release(tmp_path / "release")["annotation_status"] == {"accepted": 1}
    path = next((tmp_path / "release/inputs").glob("*.json"))
    path.write_text('{}')
    with pytest.raises(ProtocolError, match="hash"):
        audit_release(tmp_path / "release")


@pytest.mark.parametrize("bucket,reason", [("public_aux", "public_source_license_or_review_missing"), ("business_synth", "department_authorization_missing"), ("human_session", "human_consent_missing")])
def test_unapproved_sources_excluded_while_valid_records_continue(tmp_path, bucket, reason):
    # Schema unit doubles exercise source authorization; never research data.
    snapshot, units, policies = make_case(tmp_path, origin=bucket)
    units=[replace(u,provenance=u.provenance.model_copy(update={"license":"MIT"})) for u in units]
    result = export_snapshot(snapshot, units[:2])
    approved={"source.json":policies["source.json"] | {"url":"https://unit.invalid", "accessed_at":"2026-10-07", "license":"MIT", "original_hash":policies["source.json"]["sha256"], "authorization_ref":"unit-double", "consent_ref":"unit-double"}}
    contexts={r.record_id:{"root":tmp_path,"policies":policies if i==0 else approved} for i,r in enumerate(result.records)}
    publish_release(tmp_path / "release", result, source_root=tmp_path, policies=policies, source_contexts=contexts, allow_pending=True, source_authority=lambda r,s,refs: __import__("career_lab.datasets.v3.origin",fromlist=["binding"]).binding(r,s))
    report = json.loads((tmp_path / "release/quality-report.json").read_text())
    assert report["records"] == 1 and report["excluded"][0]["reason"] == reason


def test_source_drift_prevents_release(tmp_path):
    snapshot, units, policies = make_case(tmp_path)
    result = export_snapshot(snapshot, units)
    (tmp_path / "source.json").write_text("changed")
    with pytest.raises(ProtocolError, match="hash"):
        publish_release(tmp_path / "release", result, source_root=tmp_path, policies=policies, fixture=True, allow_pending=True)
    assert not (tmp_path / "release").exists()


def test_atomic_publication_failure_and_duplicate_lock(tmp_path):
    target = tmp_path / "release"
    with pytest.raises(RuntimeError):
        with immutable_directory(target) as stage:
            (stage / "file").write_text("partial")
            raise RuntimeError("fault injection")
    assert not target.exists() and not list(tmp_path.glob(".release-*"))
    with immutable_directory(target) as stage:
        with pytest.raises(ProtocolError, match="busy"):
            with immutable_directory(target):
                pass
        (stage / "file").write_text("complete")
    assert (target / "file").read_text() == "complete"


def test_snapshot_port_called_once_and_wrong_point_rejected(tmp_path):
    from career_lab.datasets.v3.export import export_from_port
    snapshot, units, _ = make_case(tmp_path)
    class Port:
        calls = 0
        def read_snapshot(self, session_id, point):
            self.calls += 1
            return snapshot
    port = Port()
    assert len(export_from_port(port, snapshot.session_id, snapshot.point, lambda s: units).records) == 4
    assert port.calls == 1
    with pytest.raises(ProtocolError, match="identity"):
        export_from_port(port, "other", snapshot.point, lambda s: units)


def test_trajectory_cannot_see_fact_from_later_step(tmp_path):
    snapshot, units, _ = make_case(tmp_path)
    step = units[2].model_input.steps[0]
    older = step.model_copy(update={"as_of": VersionPoint(business_seq=1, workspace_revision=0, storage_revision=0)})
    unit = replace(units[2], model_input=units[2].model_input.model_copy(update={"steps": (older,)}))
    result = export_snapshot(snapshot, [unit])
    assert result.quarantined[0]["reason"] == "future_step_evidence"


def test_source_map_preserves_multiple_spans_for_same_object(tmp_path):
    snapshot, units, _ = make_case(tmp_path)
    data = units[0].model_input.model_dump(mode="json")
    data["evidence"]["subjects"][0].update(span_start=2, span_end=10, quote="capacity")
    data["evidence"]["input_hash"] = digest({k: v for k, v in data["evidence"].items() if k != "input_hash"})
    result = export_snapshot(snapshot, [replace(units[0], model_input=data)])
    assert not result.quarantined
    objects = result.source_maps[result.records[0].record_id]["objects"]
    assert any(len(refs) == 2 for refs in objects.values())


def test_non_text_model_output_is_failed_not_consensus(tmp_path):
    batch, result, _ = batch_for(tmp_path)
    request = batch.claim(result.records[0].record_id, 1)
    output = batch.receive(signed(request) | {"raw_output": {"label": "SUPPORTED"}})
    assert output["pass"]["status"] == "failed"
    assert output["error_code"] == "annotation_output_not_text"
    assert output["raw_return_type"] == "dict"
    assert batch.annotation(result.records[0].record_id).final is None


def test_batch_and_result_tampering_are_rejected(tmp_path):
    batch, result, _ = batch_for(tmp_path)
    batch.run(FakeModel())
    first = next((batch.path / "labels/passes").glob("*.json"))
    changed = json.loads(first.read_text())
    changed["provider"] = "changed"
    first.write_bytes(json_bytes(changed))
    with pytest.raises(ProtocolError, match="hash"):
        batch.annotation(result.records[0].record_id)
    manifest = json.loads((batch.path / "batch.json").read_text())
    manifest["prompts"][0] = "changed"
    (batch.path / "batch.json").write_bytes(json_bytes(manifest))
    with pytest.raises(ProtocolError, match="drift"):
        AnnotationBatch(batch.path)


def test_crash_between_result_file_and_db_commit_replays_same_receipt(tmp_path):
    batch, result, _ = batch_for(tmp_path)
    request = batch.claim(result.records[0].record_id, 1)
    receipt = signed(request)
    original = batch.receive(receipt)
    # Fault injection reverts only the SQLite commit; immutable attempt file stays.
    with batch._db() as db:
        db.execute("UPDATE attempts SET status='dispatched',result_path=NULL,result_sha256=NULL")
    assert batch.receive(receipt) == original
    assert batch.usage()["successful"] == 1


def test_excluded_label_artifacts_do_not_leak_into_release(tmp_path):
    snapshot, units, policies = make_case(tmp_path)
    result = export_snapshot(snapshot, units[:2])
    batch = create_fixture_batch(tmp_path, tmp_path / "batch", result.records, annotation_version="v1", executor=Executor(id="fake", kind="external_agent"))
    annotations = batch.run(FakeModel())["annotations"]
    contexts={r.record_id:{"root":tmp_path,"policies":{} if i==0 else policies} for i,r in enumerate(result.records)}
    publish_release(tmp_path / "release", result, source_root=tmp_path, policies=policies,
                    annotations=annotations, annotation_artifacts=batch.artifacts(), fixture=True, source_contexts=contexts)
    passes = list((tmp_path / "release/labels/passes").glob("*.json"))
    assert len(passes) == 2
    for path in passes:
        assert json.loads(path.read_text())["request"]["record_id"] == result.records[1].record_id


def test_no_unproven_g0_label_can_be_published(tmp_path):
    snapshot, units, policies = make_case(tmp_path)
    result = export_snapshot(snapshot, units[:1])
    good = verify_numeric(result.records[0])
    bad = good.model_copy(update={"final": good.final.model_copy(update={"label": "CONTRADICTED"})})
    with pytest.raises(ProtocolError, match="consensus"):
        publish_release(tmp_path / "release", result, source_root=tmp_path, policies=policies,
                        annotations=[bad], fixture=True)
    assert not (tmp_path / "release").exists()


def test_single_evidence_model_review_uses_fresh_contexts_without_fake_order(tmp_path):
    snapshot, units, _ = make_case(tmp_path)
    data = units[0].model_input.model_dump(mode="json")
    data["evidence"]["candidate_evidence"] = data["evidence"]["candidate_evidence"][:1]
    data["evidence"]["input_hash"] = digest({k: v for k, v in data["evidence"].items() if k != "input_hash"})
    result = export_snapshot(snapshot, [replace(units[0], model_input=data)])
    batch = create_fixture_batch(tmp_path, tmp_path / "batch", result.records, annotation_version="v1", executor=Executor(id="fake", kind="external_agent"))
    out = batch.run(FakeModel())
    assert not out["blocked"] and out["annotations"][0].status=="accepted"
    assert all(p.evidence_order_mode=="singleton_or_empty" for p in out["annotations"][0].passes)


def test_publication_never_opens_sealed_test(tmp_path):
    snapshot, units, policies = make_case(tmp_path)
    result = export_snapshot(snapshot, [replace(units[0], split="test")])
    with pytest.raises(ProtocolError, match="sealed"):
        publish_release(tmp_path / "sealed", result, source_root=tmp_path, policies=policies, fixture=True, allow_pending=True)
    assert not (tmp_path / "sealed").exists()


def test_near_duplicate_different_claim_does_not_evade_split_guard(tmp_path):
    snapshot, units, _ = make_case(tmp_path)
    first = export_snapshot(snapshot, units[:1]).records[0]
    second = isolated_record(first)
    data = second.model_input.model_dump(mode="json")
    data["evidence"]["claim"] = "capacity <= 31"
    data["evidence"]["input_hash"] = digest({k: v for k, v in data["evidence"].items() if k != "input_hash"})
    raw = second.model_dump(mode="json") | {"model_input": data, "input_hash": digest(data)}
    second = DatasetRecordV2.model_validate(raw)
    with pytest.raises(QualityError) as exc:
        audit_records([first, second])
    assert any(e["code"] == "near_duplicate_cross_split" for e in exc.value.report["errors"])
