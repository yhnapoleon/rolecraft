"""File-based orchestration tests; fixtures are not generated research data."""
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest
from career_lab.contracts.v2 import (
    Budget, CampaignCandidate, EvaluationBundle, Executor, FileRef, Lineage, RunManifest,
    RuntimeBundle, SourceIdentity, SplitEntry, SplitManifest, TestCampaign as Campaign, canonical, digest,
)
from career_lab.reference_agent.suite import SuiteRun, SuiteSpec, validate_suite, run_suite
from career_lab.reference_agent.ports import PortError
from career_lab.reference_agent.cli import main

H = "b"*64


def write(root, name, value):
    raw = (canonical(value) + "\n").encode()
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return FileRef(path=name, sha256=hashlib.sha256(raw).hexdigest())


def build(root, *, split="dev", purpose="module_test", opened=True, count=2):
    source = SourceIdentity(base_commit="8"*40, source_digest=H)
    filler = write(root, "fixture.json", {"identity": "synthetic module fixture"})
    config = write(root, "policy.json", {"prompt": "synthetic fixture"})
    runtime = RuntimeBundle(id="runtime", revision="test-only", model=filler, prompts=(config,),
        acquisition=filler, retrieval=filler, decision=filler, tools=filler, source=source)
    rref = write(root, "runtime.json", runtime)
    eref = write(root, "evaluation.json", EvaluationBundle(id="eval", revision="test-only",
        rubric=filler, rules=filler, graders=(filler,), protocol=filler))
    budget = Budget(model_calls=5, tokens=10000, actions=5, wall_seconds=100)
    entries = tuple(SplitEntry(record_id=f"record-{i}", structure_id=f"fixture-{i}",
        component_id=f"component-{i}", split=split, file=filler) for i in range(count))
    sref = write(root, "split.json", SplitManifest(id="split", entries=entries,
        independent_structure_count=count))
    cref = None
    if purpose == "confirmatory":
        now = datetime.now(timezone.utc)
        campaign = Campaign(id="campaign", candidates=(CampaignCandidate(
            id="candidate", runtime=rref, evaluation=eref, source=source, budget=budget),),
            split_manifest=sref, frozen_at=now, opened_at=now if opened else None,
            output_audience=("isolated-reviewer",))
        cref = write(root, "campaign.json", campaign)
    runs = []
    manifests = []
    for i in range(count):
        m = RunManifest(id=f"run-{i}", session_id=f"session-{i}",
            executor=Executor(id="research", kind="reference_agent"), scenario=filler,
            runtime=rref, evaluation=eref, seed=7, split=split, budget=budget,
            provider="fixture-provider", model_revision="fixture-model", source=source,
            lineage=Lineage(structure_id=f"fixture-{i}", component_id=f"component-{i}",
                            run_id=f"run-{i}", session_id=f"session-{i}"), campaign=cref)
        mref = write(root, f"manifests/{i}.json", m)
        runs.append(SuiteRun(manifest=mref, policy="checklist", goal="fixture", policy_config=config))
        manifests.append(m)
    return SuiteSpec(id="suite", purpose=purpose, split_manifest=sref,
                     campaign=cref, runs=tuple(runs)), manifests


def replace_manifest(root, spec, index, manifest):
    ref = write(root, f"changed-{index}.json", manifest)
    runs = list(spec.runs)
    runs[index] = runs[index].model_copy(update={"manifest": ref})
    return spec.model_copy(update={"runs": tuple(runs)})


def test_suite_verifies_files_and_drift(tmp_path):
    spec, _ = build(tmp_path)
    assert len(validate_suite(spec, tmp_path)) == 2
    (tmp_path / "policy.json").write_text("changed")
    with pytest.raises(Exception, match="hash"):
        validate_suite(spec, tmp_path)


@pytest.mark.parametrize("split", ["test", "regression"])
def test_development_cannot_consume_test_or_regression(tmp_path, split):
    spec, _ = build(tmp_path, split=split)
    with pytest.raises(PortError):
        validate_suite(spec, tmp_path)


def test_confirmatory_campaign_requires_explicit_open_and_frozen_candidate(tmp_path):
    spec, _ = build(tmp_path, split="test", purpose="confirmatory", opened=False)
    with pytest.raises(Exception, match="campaign"):
        validate_suite(spec, tmp_path)


def test_confirmatory_validated_without_reading_scenario_payload_as_strategy_input(tmp_path):
    spec, _ = build(tmp_path, split="test", purpose="confirmatory")
    assert len(validate_suite(spec, tmp_path)) == 2


def test_budget_mismatch_rejected(tmp_path):
    spec, manifests = build(tmp_path)
    m = manifests[1].model_copy(update={"budget": manifests[1].budget.model_copy(update={"actions": 9})})
    spec = replace_manifest(tmp_path, spec, 1, m)
    with pytest.raises(PortError, match="budget"):
        validate_suite(spec, tmp_path)


def test_source_drift_rejected(tmp_path):
    spec, manifests = build(tmp_path)
    m = manifests[0].model_copy(update={"source": manifests[0].source.model_copy(update={"source_digest": "c"*64})})
    with pytest.raises(PortError, match="runtime_source"):
        validate_suite(replace_manifest(tmp_path, spec, 0, m), tmp_path)


def test_same_structure_wrong_component_rejected(tmp_path):
    spec, manifests = build(tmp_path)
    m = manifests[0].model_copy(update={"lineage": manifests[0].lineage.model_copy(update={"component_id": "wrong"})})
    with pytest.raises(PortError, match="lineage"):
        validate_suite(replace_manifest(tmp_path, spec, 0, m), tmp_path)


def test_unfrozen_policy_config_rejected(tmp_path):
    spec, _ = build(tmp_path)
    raw = write(tmp_path, "changed-policy.json", {"prompt": "not frozen"})
    runs = (spec.runs[0].model_copy(update={"policy_config": raw}), *spec.runs[1:])
    with pytest.raises(PortError, match="policy_config"):
        validate_suite(spec.model_copy(update={"runs": runs}), tmp_path)


def test_suite_failure_stays_in_denominator_and_continues(tmp_path):
    spec, _ = build(tmp_path)
    calls = []
    def factory(policy, config, manifest):
        calls.append(manifest.id)
        raise PortError("test_provider_unavailable")
    result = run_suite(spec, tmp_path, tmp_path / "out", factory)
    assert calls == ["run-0", "run-1"]
    assert result["planned_runs"] == result["attempted_runs"] == 2
    assert result["verified_successes"] == 0
    assert all(r["reason_code"] == "test_provider_unavailable" for r in result["runs"])
    assert result["research_acceptance"] == "not_assessed"


def test_cli_validates_and_missing_wiring_is_nonzero_json(tmp_path, capsys):
    spec, _ = build(tmp_path)
    path = tmp_path / "suite-input.json"; path.write_text(spec.model_dump_json())
    args = ["agent-suite", "--suite", str(path), "--root", str(tmp_path)]
    assert main(args + ["--validate-only"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "valid"
    assert main(args + ["--output", str(tmp_path / "out")]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "w09_integration_factory_not_installed"


def test_file_reference_cannot_escape_output_root(tmp_path):
    from career_lab.contracts.v2 import read_file
    other = tmp_path / "outside"; other.write_text("content")
    root = tmp_path / "root"; root.mkdir(); (root / "link").symlink_to(other)
    ref = FileRef(path="link", sha256=hashlib.sha256(b"content").hexdigest())
    with pytest.raises(Exception, match="outside"):
        read_file(root, ref)


def test_suite_has_exclusive_writer_lock(tmp_path):
    from career_lab.reference_agent.journal import RunJournal
    spec, _ = build(tmp_path)
    out = tmp_path / 'out'
    with RunJournal(out).locked():
        with pytest.raises(PortError, match='already_active'):
            run_suite(spec, tmp_path, out, lambda *args: None)
