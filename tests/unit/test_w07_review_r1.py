"""Regression reproductions for 031 review r1; all inputs/models are test fixtures."""
from dataclasses import replace
import json

import pytest

from test_w07_pipeline import make_case, batch_for, FakeModel, decision, signed
from career_lab.contracts.v2.core import ObjectRef, EvidenceRefV2, VersionPoint, Executor, digest, ProtocolError
from career_lab.contracts.v2.data import Lineage
from career_lab.datasets.v3.export import SourceObject, export_snapshot
from career_lab.datasets.v3.labeling import AnnotationBatch, LabelResult
from career_lab.datasets.v3.quality import audit_records, QualityError, source_policy_error
from career_lab.datasets.v3.release import publish_release, audit_release
from career_lab.datasets.v3.common import json_bytes, sha


def changed_step(unit, step):
    key = "steps" if unit.family == "trajectory" else "observed_steps"
    return replace(unit, model_input=unit.model_input.model_copy(update={key: (step,)}))


@pytest.mark.parametrize("family_index", [2, 3])
@pytest.mark.parametrize("source_kind", ["future", "gold_fragment", "uncited_visible"])
def test_r1_unbound_observation_never_enters_model_input(tmp_path, family_index, source_kind):
    snapshot, units, _ = make_case(tmp_path)
    usage, readers = ("gold", ()) if source_kind == "gold_fragment" else ("visible", ("learner",))
    text = "Secret answer: choose option B.\nPrivate rationale: legal risk."
    source = SourceObject(ObjectRef(session_id="session1", kind="document", object_id="new-source", version=1),
                          text, snapshot.point, readers, usage)
    unit = units[family_index]
    step = (unit.model_input.steps if family_index == 2 else unit.model_input.observed_steps)[0]
    step = step.model_copy(update={"as_of": VersionPoint(business_seq=1, workspace_revision=0, storage_revision=1),
                                  "observations": (text.splitlines()[0],), "evidence_refs": ()})
    out = export_snapshot(replace(snapshot, objects=(*snapshot.objects, source)), [changed_step(unit, step)])
    assert not out.records and out.quarantined[0]["reason"] == "observation_source_required"


@pytest.mark.parametrize("family_index", [2, 3])
def test_r1_bound_historical_span_is_allowed_but_future_span_is_not(tmp_path, family_index):
    snapshot, units, _ = make_case(tmp_path)
    text = "A visible fact. Additional public detail."
    at = VersionPoint(business_seq=1, workspace_revision=0, storage_revision=1)
    obj = ObjectRef(session_id="session1", kind="document", object_id="observed-text", version=1)
    source = SourceObject(obj, text, at, ("learner",))
    ref = EvidenceRefV2(**{k: v for k, v in obj.model_dump(mode="json").items() if k != "schema_version"},
                        observed_at_seq=1, span_start=0, span_end=15, quote=text[:15])
    unit = units[family_index]
    old = (unit.model_input.steps if family_index == 2 else unit.model_input.observed_steps)[0]
    step = old.model_copy(update={"as_of": at, "observations": (text[:15],), "evidence_refs": (ref,)})
    snapshot = replace(snapshot, objects=(*snapshot.objects, source))
    out = export_snapshot(snapshot, [changed_step(unit, step)])
    assert len(out.records) == 1 and not out.quarantined
    bindings = out.source_maps[out.records[0].record_id]["observation_bindings"]
    assert list(bindings.values())[0]["sources"][0]["object_id"] == "observed-text"
    future = replace(snapshot, objects=(*snapshot.objects[:-1], replace(source, available_at=snapshot.point)))
    assert export_snapshot(future, [changed_step(unit, step)]).quarantined[0]["reason"] == "future_source_reference"


def release_fixture(tmp_path):
    batch, result, policies = batch_for(tmp_path)
    annotations = batch.run(FakeModel())["annotations"]
    return batch, result, policies, annotations


def test_r2_empty_named_pass_artifacts_are_rejected(tmp_path):
    batch, result, policies, annotations = release_fixture(tmp_path)
    with pytest.raises(ProtocolError, match="artifact"):
        publish_release(tmp_path / "release", result, source_root=tmp_path, policies=policies,
            annotations=annotations, annotation_artifacts={p: b'{}\n' for p in batch.artifacts()}, fixture=True)
    assert not (tmp_path / "release").exists()


def test_r2_invalid_citations_cannot_replace_declared_decisions(tmp_path):
    batch, result, policies, annotations = release_fixture(tmp_path)
    original = annotations[0]
    bad = original.final.model_copy(update={"evidence_ids": ("missing-evidence",), "acceptable_evidence_sets": (("missing-evidence",),)})
    annotation = original.model_copy(update={"final": bad, "passes": tuple(p.model_copy(update={"decision": bad}) for p in original.passes)})
    with pytest.raises(ProtocolError):
        publish_release(tmp_path / "release", result, source_root=tmp_path, policies=policies,
                        annotations=[annotation], annotation_artifacts=batch.artifacts(), fixture=True)
    assert not (tmp_path / "release").exists()


@pytest.mark.parametrize("field", ["record_id", "input_hash", "payload_hash", "model_input", "model_revision", "provider", "executor", "decision", "raw_output", "source_policy"])
def test_r2_attempt_identity_tampering_rejected_before_publish(tmp_path, field):
    batch, result, policies, annotations = release_fixture(tmp_path)
    artifacts = batch.artifacts()
    name = next(iter(artifacts)); data = json.loads(artifacts[name])
    if field in {"record_id", "input_hash", "payload_hash"}:
        data["request"][field] = "changed"
        data["request_hash"] = digest(data["request"])
    elif field == "model_input":
        data["request"]["model_input"]["evidence"]["claim"] = "different input"
        data["request"]["payload_hash"] = digest(data["request"]["model_input"])
        data["request_hash"] = digest(data["request"])
    elif field in {"model_revision", "provider", "raw_output"}:
        data["receipt"][field] = "changed"
        data["receipt_hash"] = digest(data["receipt"])
    elif field == "executor":
        data["pass"]["executor"]["id"] = "different-agent"
    elif field == "decision":
        data["pass"]["decision"]["label"] = "CONTRADICTED"
    else:
        data["source_policy"]["sources"][0]["review"]["review_status"] = "rejected"
    artifacts[name] = json_bytes(data)
    with pytest.raises(ProtocolError):
        publish_release(tmp_path / "release", result, source_root=tmp_path, policies=policies,
                        annotations=annotations, annotation_artifacts=artifacts, fixture=True)


def rehash_release(root):
    """Attack recomputes every outer checksum; semantic audit must still refuse."""
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["files"] = {name: sha((root / name).read_bytes()) for name in manifest["files"]}
    manifest["id"] = digest({k: v for k, v in manifest.items() if k != "id"})
    (root / "manifest.json").write_bytes(json_bytes(manifest))


@pytest.mark.parametrize("change", ["empty_pass", "invalid_reference", "missing_identity", "rejected_policy"])
def test_r2_audit_rechecks_semantics_after_outer_hashes_are_rebuilt(tmp_path, change):
    batch, result, policies, annotations = release_fixture(tmp_path)
    root = tmp_path / "release"
    publish_release(root, result, source_root=tmp_path, policies=policies, annotations=annotations,
                    annotation_artifacts=batch.artifacts(), fixture=True)
    path = next((root / "labels/passes").glob("*.json"))
    data = json.loads(path.read_text())
    if change == "empty_pass":
        path.write_text('{}\n')
    elif change == "rejected_policy":
        reviews = json.loads((root / "source-reviews.json").read_text())
        reviews[result.records[0].record_id]["source.json"]["review_status"] = "rejected"
        (root / "source-reviews.json").write_bytes(json_bytes(reviews))
    else:
        if change == "missing_identity":
            data["receipt"]["model_revision"] = ""
        else:
            raw = json.loads(data["receipt"]["raw_output"])
            raw["evidence_ids"] = ["missing-evidence"]
            data["receipt"]["raw_output"] = json.dumps(raw)
        data["receipt_hash"] = digest(data["receipt"])
        path.write_bytes(json_bytes(data))
    rehash_release(root)
    with pytest.raises(ProtocolError):
        audit_release(root)


@pytest.mark.parametrize("link", ["decision_id", "candidate_id", "both"])
def test_r3_cross_family_causal_identity_connects_forked_sessions(tmp_path, link):
    snapshot, units, _ = make_case(tmp_path)
    records = export_snapshot(snapshot, units).records
    same = {"decision_id": "causal-root/decision-17", "candidate_id": "causal-root/counterfactual-2"}
    if link != "both": same = {link: same[link]}
    a = records[0].model_copy(update={"lineage": records[0].lineage.model_copy(update=same)})
    b = records[3].model_copy(update={"split": "dev", "lineage": Lineage(structure_id="fork-structure", component_id="fork-component", session_id="fork", run_id="fork", **same)})
    with pytest.raises(QualityError) as exc:
        audit_records([a, b])
    assert any(e["code"] == "connected_lineage_cross_split" for e in exc.value.report["errors"])


@pytest.mark.parametrize("origin,edit,reason", [
    ("business_synth", {}, "department_authorization_missing"),
    ("human_session", {}, "human_consent_missing"),
    ("public_aux", {}, "public_source_license_or_review_missing"),
    ("business_synth", {"review_status": "rejected", "authorization_ref": "previous-approval"}, "source_review_not_approved"),
    ("env_run", {"revoked": True}, "source_authorization_revoked"),
])
def test_r4_unapproved_record_is_quarantined_before_any_send(tmp_path, origin, edit, reason):
    snapshot, units, policies = make_case(tmp_path, origin=origin)
    policies["source.json"].update(edit)
    result = export_snapshot(snapshot, units[:1])
    batch = AnnotationBatch.create(tmp_path / "batch", result.records, annotation_version="v1",
        executor=Executor(id="test-double", kind="external_agent"), source_root=tmp_path, policies=policies)
    model = FakeModel(); out = batch.run(model)
    assert not model.calls and out["usage"]["attempts"] == 0
    assert out["quarantined"][0]["reason"] == reason
    assert (batch.path / "records.json").read_text().strip() == "[]"
    with pytest.raises(ProtocolError, match="approved"):
        batch.claim(result.records[0].record_id, 1)


def test_r4_missing_policy_is_rejected_and_frozen_policy_drift_blocks_issue(tmp_path):
    snapshot, units, policies = make_case(tmp_path)
    result = export_snapshot(snapshot, units[:1])
    kwargs = dict(annotation_version="v1", executor=Executor(id="test-double", kind="external_agent"))
    with pytest.raises(ProtocolError, match="source policy required"):
        AnnotationBatch.create(tmp_path / "missing", result.records, **kwargs)
    assert not (tmp_path / "missing").exists()
    batch = AnnotationBatch.create(tmp_path / "batch", result.records, source_root=tmp_path, policies=policies, **kwargs)
    (batch.path / "source-policy.json").write_text('{}')
    model = FakeModel()
    with pytest.raises(ProtocolError, match="hash"):
        batch.run(model)
    assert not model.calls


@pytest.mark.parametrize("missing", ["model", "provider", "both"])
def test_r5_received_missing_identity_is_failed_preserved_and_retryable(tmp_path, missing):
    batch, result, _ = batch_for(tmp_path)
    def bad(request):
        return LabelResult(decision(request).model_dump_json(), "" if missing in {"model", "both"} else "test-model",
                           "" if missing in {"provider", "both"} else "test-provider", {"cost": 0.125})
    out = batch.run(bad)
    assert out["usage"]["failed"] == 2 and out["usage"]["uncertain"] == 0
    assert out["usage"]["known_cost"] == 0.25
    for raw in batch.artifacts().values():
        stored = json.loads(raw)
        assert stored["pass"]["raw_output"] and stored["receipt"]["usage"]["cost"] == 0.125
        assert stored["error_code"] == "actual_model_identity_required"
    fixed = FakeModel(); out = batch.run(fixed, retry_failed=True)
    assert len(fixed.calls) == 2 and out["annotations"][0].status == "accepted"
    assert out["usage"]["failed"] == 2 and out["usage"]["uncertain"] == 0


def test_r4_mixed_batch_freezes_only_authorized_record_bodies(tmp_path):
    snapshot, units, policies = make_case(tmp_path, origin="env_run")
    result = export_snapshot(snapshot, units[:2])
    unauthorized = result.records[0].model_copy(update={"bucket": "human_session"})
    batch = AnnotationBatch.create(tmp_path / "batch", [unauthorized, result.records[1]], annotation_version="v1",
        executor=Executor(id="test-double", kind="external_agent"), source_root=tmp_path, policies=policies)
    model = FakeModel(); out = batch.run(model)
    assert {r["record_id"] for r in model.calls} == {result.records[1].record_id}
    rows = json.loads((batch.path / "records.json").read_text())
    assert [r["record_id"] for r in rows] == [result.records[1].record_id]
    assert out["quarantined"] == [{"record_id": unauthorized.record_id, "reason": "human_consent_missing"}]


def test_dispatch_rechecks_frozen_prompt_manifest(tmp_path):
    batch, result, policies = batch_for(tmp_path)
    manifest = json.loads((batch.path / "batch.json").read_text())
    manifest["prompts"][0] = "unapproved-prompt"
    manifest["id"] = digest({k: v for k, v in manifest.items() if k != "id"})
    (batch.path / "batch.json").write_bytes(json_bytes(manifest))
    model = FakeModel()
    with pytest.raises(ProtocolError, match="manifest"):
        batch.run(model)
    assert not model.calls


@pytest.mark.parametrize("model_field", ["missing", "null"])
def test_r5_http_200_missing_model_preserves_raw_and_usage_before_retry(tmp_path, model_field):
    import httpx
    from career_lab.datasets.v3.labeling import OpenAICompatibleExecutor
    batch, result, _ = batch_for(tmp_path)
    seen = []
    def transport(request):
        body = json.loads(request.content)
        payload = json.loads(body["messages"][1]["content"])
        raw = decision({"model_input": payload}).model_dump_json()
        seen.append(raw)
        response = {"choices": [{"message": {"content": raw}}],
                    "usage": {"cost": 0.125, "prompt_tokens": 7, "completion_tokens": 11}}
        if model_field == "null": response["model"] = None
        return httpx.Response(200, json=response)
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        out = batch.run(OpenAICompatibleExecutor(client, "https://test.invalid/chat/completions", "requested-only", "fixture-key"))
    assert len(seen) == 2 and out["annotations"][0].status == "pending"
    assert out["usage"]["failed"] == 2 and out["usage"]["uncertain"] == 0
    assert out["usage"]["known_cost"] == 0.25 and out["usage"]["cost_complete"]
    for raw in batch.artifacts().values():
        saved = json.loads(raw)
        assert saved["pass"]["raw_output"] in seen
        assert saved["error_code"] == "actual_model_identity_required"
        assert saved["receipt"]["usage"] == {"cost": 0.125, "prompt_tokens": 7, "completion_tokens": 11}
        assert saved["receipt"]["model_revision"] is None
    model = FakeModel(); retried = batch.run(model, retry_failed=True)
    assert len(model.calls) == 2 and retried["annotations"][0].status == "accepted"
    assert retried["usage"]["known_cost"] == 0.25 and retried["usage"]["failed"] == 2
