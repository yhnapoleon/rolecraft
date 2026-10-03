import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from career_lab.contracts.evaluation import EvidencePackage, GoldAnnotation, JudgeDecision
from career_lab.scenarios.loader import ScenarioLoadError, load_scenario, validate_scenario

ROOT = Path(__file__).resolve().parents[2]
SCENARIO = ROOT / "scenarios/pm_pilot/v1/scenario.yaml"


def test_capacity_and_exception_are_explicit():
    spec = load_scenario(SCENARIO)
    assert validate_scenario(spec) == []
    assert spec.constraints.capacity == 30
    assert spec.constraints.dev_days == 3
    assert spec.constraints.realtime_sync_days == 5
    assert spec.constraints.index_delay_hours == 24
    expansion = next(e for e in spec.event_rules if e.id == "capacity_approved")
    assert expansion.trigger.kind == "approved_request"
    assert expansion.trigger.authorized_role == "supervisor"
    assert expansion.effects.capacity == 60
    assert len(spec.roles) == 3


def test_versions_and_hashes_are_repeatable():
    first = load_scenario(SCENARIO)
    second = load_scenario(SCENARIO)
    assert first.content_hash == second.content_hash
    assert len(first.content_hash) == 64
    assert all(m.content and len(m.content_hash) == 64 for m in first.materials)
    policy = [m for m in first.materials if m.id == "policy"]
    assert {m.version for m in policy} == {1, 2}
    assert next(m for m in policy if m.version == 2).available_after_event == "policy_updated"


def copy_bundle(tmp_path):
    target = tmp_path / "v1"
    shutil.copytree(SCENARIO.parent, target)
    return target


def test_changed_material_cannot_reuse_frozen_version(tmp_path):
    target = copy_bundle(tmp_path)
    material = target / "materials/brief.md"
    material.write_text(material.read_text(encoding="utf-8") + "\nchanged", encoding="utf-8")
    with pytest.raises(ScenarioLoadError, match="hash"):
        load_scenario(target / "scenario.yaml")


def test_missing_material_is_explicit(tmp_path):
    target = copy_bundle(tmp_path)
    (target / "materials/brief.md").unlink()
    with pytest.raises(ScenarioLoadError, match="brief.md"):
        load_scenario(target / "scenario.yaml")


@pytest.mark.parametrize("path", ["../outside.md", "C:/outside.md", "materials/../../outside.md"])
def test_material_paths_cannot_escape_bundle(tmp_path, path):
    target = copy_bundle(tmp_path)
    data = yaml.safe_load((target / "scenario.yaml").read_text(encoding="utf-8"))
    data["materials"][0]["path"] = path
    (target / "scenario.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ScenarioLoadError):
        load_scenario(target / "scenario.yaml")


def test_unknown_role_and_duplicate_material_are_rejected():
    spec = load_scenario(SCENARIO)
    bad = spec.model_copy(update={"materials": spec.materials + (spec.materials[0],)})
    assert "duplicate_material" in {i.code for i in validate_scenario(bad)}
    fact = spec.facts[0].model_copy(update={"visible_to": ("nobody",)})
    bad = spec.model_copy(update={"facts": (fact,) + spec.facts[1:]})
    assert "unknown_role" in {i.code for i in validate_scenario(bad)}


def test_fact_ledger_and_enforced_constraints_cannot_disagree():
    spec = load_scenario(SCENARIO)
    capacity = next(f for f in spec.facts if f.id == "capacity")
    wrong_fact = capacity.model_copy(update={"value": 60})
    bad = spec.model_copy(update={"facts": tuple(wrong_fact if f.id == "capacity" else f for f in spec.facts)})
    assert "inconsistent_fact" in {i.code for i in validate_scenario(bad)}


def test_minimum_participants_cannot_exceed_capacity():
    spec = load_scenario(SCENARIO)
    bad = spec.model_copy(update={"constraints": spec.constraints.model_copy(update={"minimum_participants": 31})})
    assert "impossible_participant_bounds" in {i.code for i in validate_scenario(bad)}


def test_one_event_cannot_activate_two_versions_of_one_material():
    spec = load_scenario(SCENARIO)
    update = next(e for e in spec.event_rules if e.id == "policy_updated")
    ref = update.effects.material_versions[0]
    ambiguous = update.model_copy(update={"effects": update.effects.model_copy(
        update={"material_versions": (ref, ref.model_copy(update={"version": 3}))})})
    future = next(m for m in spec.materials if m.id == "policy" and m.version == 2)
    bad = spec.model_copy(update={
        "event_rules": tuple(ambiguous if e.id == update.id else e for e in spec.event_rules),
        "materials": spec.materials + (future.model_copy(update={"version": 3, "path": "materials/policy-v3.md"}),),
    })
    assert "ambiguous_material_effect" in {i.code for i in validate_scenario(bad)}


def test_gold_sidecar_is_separate_from_input():
    bundle = json.loads((ROOT / "docs/examples/judge-case-bundle.json").read_text(encoding="utf-8"))
    item = EvidencePackage.model_validate(bundle["input"])
    gold = GoldAnnotation.model_validate(bundle["gold_sidecar"])
    assert gold.label == "CONTRADICTED"
    assert item.criterion == "R3.capacity_claim"
    for key in ("gold_ref", "label", "acceptable_evidence_sets"):
        with pytest.raises(ValidationError):
            EvidencePackage.model_validate({**bundle["input"], key: "leaked"})
    contaminated = json.loads(json.dumps(bundle["input"]))
    contaminated["candidate_evidence"][0]["label"] = "SUPPORTED"
    with pytest.raises(ValidationError):
        EvidencePackage.model_validate(contaminated)


def test_label_namespaces_and_duplicate_citations_are_validated():
    bundle = json.loads((ROOT / "docs/examples/judge-case-bundle.json").read_text(encoding="utf-8"))
    with pytest.raises(ValidationError):
        GoldAnnotation.model_validate({**bundle["gold_sidecar"], "task_type": "relation", "label": "MET"})
    with pytest.raises(ValidationError):
        JudgeDecision(label="SUPPORTED", evidence_ids=["e1", "e1"], reason_code="X", explanation="X", model_revision="test")


def test_cli_validates_bundle_and_reports_errors(tmp_path):
    result = subprocess.run([sys.executable, "-m", "career_lab.cli", "scenario", "validate", str(SCENARIO)], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["valid"] is True
    result = subprocess.run([sys.executable, "-m", "career_lab.cli", "scenario", "validate", str(tmp_path / "missing.yaml")], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 1
    assert json.loads(result.stdout)["valid"] is False

