from pathlib import Path
from datetime import datetime, timezone
import json, shutil, hashlib
import pytest
from pydantic import ValidationError
from career_lab.contracts.v2 import *
from career_lab.contracts.v2.files import load_bundle
from career_lab.contracts.v2.data import model_input, require_training_split, require_confirmatory

DRAFT = (
    Path(__file__).resolve().parents[3]
    / "docs/contracts/expansion-v3/drafts/draft-20261006-2020/examples"
)


@pytest.mark.parametrize("family", ["relation", "criterion", "trajectory", "acquisition"])
def test_four_families_use_separate_typed_inputs(family):
    raw = json.loads((DRAFT / f"DatasetRecordV2-{family}.json").read_text())
    record = DatasetRecordV2.model_validate(raw)
    assert model_input(record)["task_type"] == FAMILY_TASK[family]
    assert "label_ref" not in model_input(record) and "label_tier" not in model_input(record)
    bad = raw | {"family": "criterion" if family != "criterion" else "relation"}
    with pytest.raises(ValidationError):
        DatasetRecordV2.model_validate(bad)
    with pytest.raises(ValidationError):
        DatasetRecordV2.model_validate(raw | {"input_hash": "0" * 64})
    bad = json.loads(json.dumps(raw))
    bad["model_input"]["gold"] = "MET"
    with pytest.raises(ValidationError):
        DatasetRecordV2.model_validate(bad)


def test_c0_missing_null_and_rule_bounds_do_not_fake_known_scores():
    ref = EvidenceRefV2(
        session_id="s", kind="config", object_id="c", version=1, config_version=0, observed_at_seq=0
    )
    assert ref.config_version == 0 and ref.version == 1
    with pytest.raises(ValidationError):
        EvidenceRefV2.model_validate(ref.model_dump() | {"version": 0})
    with pytest.raises(ValidationError):
        RuleBound(lower="NOT_APPLICABLE", upper="MET")
    raw = json.loads((DRAFT / "CriterionInput.json").read_text())["evidence"]
    raw.update(completeness="text_overflow", rule_context={"capacity": 30}, candidate_evidence=[])
    raw["input_hash"] = digest({k: v for k, v in raw.items() if k != "input_hash"})
    parsed = EvidencePackageV2.model_validate(raw)
    assert parsed.rule_context["capacity"] == 30 and parsed.completeness == "text_overflow"
    bad = parsed.model_dump(mode="json") | {
        "rule_bound": {"schema_version": 2, "lower": "NOT_MET", "upper": "MET"}
    }
    bad["input_hash"] = digest({k: v for k, v in bad.items() if k != "input_hash"})
    with pytest.raises(ValidationError):
        EvidencePackageV2.model_validate(bad)


def test_annotation_failed_empty_and_old_g1_cannot_be_consensus():
    actor = Executor(id="model", kind="system")
    h = "0" * 64
    decision = AnnotationDecision(
        task_type="relation", label="SUPPORTED", evidence_ids=("e1",), evidence_evaluable=True
    )
    a = AnnotationPass(
        id="a",
        invocation_id="call-a",
        context_id="context-a",
        independence_method="fresh_context",
        executor=actor,
        status="success",
        input_hash=h,
        prompt_revision="p1",
        model_revision="model-r1",
        evidence_order=("e1", "e2"),
        raw_output="real output from pass a",
        decision=decision,
    )
    b = AnnotationPass.model_validate(
        a.model_dump()
        | {
            "id": "b",
            "invocation_id": "call-b",
            "context_id": "context-b",
            "prompt_revision": "p2",
            "evidence_order": ("e2", "e1"),
            "raw_output": "real output from pass b",
        }
    )
    ok = AnnotationV2(
        record_id="r",
        annotation_version="v2",
        input_hash=h,
        label_tier="G2v",
        status="accepted",
        passes=(a, b),
        final=decision,
    )
    assert ok.label_tier == "G2v"
    empty = AnnotationPass(id="empty", executor=actor, status="empty", input_hash=h)
    with pytest.raises(ValidationError):
        AnnotationV2.model_validate(ok.model_dump() | {"passes": (a, empty)})
    disagree = AnnotationPass.model_validate(
        b.model_dump() | {"decision": decision.model_dump() | {"label": "CONTRADICTED"}}
    )
    with pytest.raises(ValidationError):
        AnnotationV2.model_validate(ok.model_dump() | {"passes": (a, disagree)})
    with pytest.raises(ValidationError):
        AnnotationV2.model_validate(ok.model_dump() | {"label_tier": "G1"})


def test_connected_splits_campaign_and_training_access():
    f = FileRef(path="data/a.json", sha256="0" * 64)
    a = SplitEntry(record_id="a", structure_id="s", component_id="c", split="train", file=f)
    b = SplitEntry(
        record_id="b", structure_id="s", component_id="c", ancestors=("a",), split="train", file=f
    )
    assert SplitManifest(id="split", entries=(a, b), independent_structure_count=1)
    with pytest.raises(ValidationError):
        SplitManifest(
            id="split",
            entries=(a, b.model_copy(update={"split": "test"})),
            independent_structure_count=1,
        )
    with pytest.raises(ValidationError):
        SplitEntry.model_validate(a.model_dump() | {"seen_test": True, "split": "test"})
    with pytest.raises(ProtocolError):
        require_training_split("test")
    with pytest.raises(ProtocolError):
        require_training_split("regression")
    source = SourceIdentity(base_commit="0" * 40, source_digest="0" * 64)
    budget = Budget(model_calls=1, actions=2, wall_seconds=3)
    candidate = CampaignCandidate(id="a", runtime=f, evaluation=f, source=source, budget=budget)
    now = datetime.now(timezone.utc)
    campaign = TestCampaign(
        id="c",
        candidates=(candidate,),
        split_manifest=f,
        frozen_at=now,
        output_audience=("reviewer",),
    )
    with pytest.raises(ProtocolError):
        require_confirmatory(campaign, candidate, f)
    opened = campaign.model_copy(update={"opened_at": now})
    require_confirmatory(opened, candidate, f)
    with pytest.raises(ProtocolError):
        require_confirmatory(opened, candidate.model_copy(update={"id": "late-candidate"}), f)


def test_bundles_survive_relocation_and_reject_escape_or_drift(tmp_path):
    root = tmp_path / "original"
    root.mkdir()
    (root / "payload.json").write_text("{}")
    ref = FileRef(path="payload.json", sha256=hashlib.sha256(b"{}").hexdigest())
    source = SourceIdentity(base_commit="0" * 40, source_digest="0" * 64, dependency_locks=(ref,))
    bundle = RuntimeBundle(
        id="r",
        revision="r1",
        model=ref,
        prompts=(ref,),
        acquisition=ref,
        retrieval=ref,
        decision=ref,
        tools=ref,
        source=source,
    )
    raw = bundle.model_dump_json().encode()
    (root / "runtime.json").write_bytes(raw)
    bundle_ref = FileRef(path="runtime.json", sha256=hashlib.sha256(raw).hexdigest())
    relocated = tmp_path / "moved"
    shutil.copytree(root, relocated)
    assert load_bundle(relocated, bundle_ref, RuntimeBundle) == load_bundle(
        root, bundle_ref, RuntimeBundle
    )
    (relocated / "payload.json").write_text("changed")
    with pytest.raises(ProtocolError, match="file hash mismatch"):
        load_bundle(relocated, bundle_ref, RuntimeBundle)
    with pytest.raises(ValidationError):
        FileRef(path="../outside", sha256="0" * 64)
    (relocated / "outside").symlink_to(root / "payload.json")
    with pytest.raises(ProtocolError, match="file outside root"):
        read_file(relocated, FileRef(path="outside", sha256=ref.sha256))


# Imported protocol models are not pytest test classes.
globals().pop("TestRequestV2", None)
globals().pop("TestResultV2", None)
globals().pop("TestCase", None)
globals().pop("TestPlanPayload", None)
TestCampaign.__test__ = False


def test_model_prediction_cannot_mix_label_namespaces():
    from career_lab.contracts.v2 import ModelPrediction

    valid = dict(
        task_type="relation",
        input_hash="0" * 64,
        model_revision="linear-r1",
        status="success",
        labels=("SUPPORTED", "CONTRADICTED", "INSUFFICIENT"),
        probabilities=(0.2, 0.3, 0.5),
    )
    assert ModelPrediction(**valid).probabilities == (0.2, 0.3, 0.5)
    with pytest.raises(ValidationError):
        ModelPrediction(**(valid | {"task_type": "criterion"}))
    with pytest.raises(ValidationError):
        ModelPrediction(**(valid | {"probabilities": (0.1, 0.1, 0.1)}))
    with pytest.raises(ValidationError):
        ModelPrediction(**(valid | {"status": "unavailable"}))


globals().pop("TestExecutionMetadata", None)
