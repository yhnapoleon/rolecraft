"""Frozen suite orchestration; no code loading, model discovery or secret discovery."""
import json
import os
from pathlib import Path
from typing import Literal
from pydantic import Field, model_validator

from career_lab.contracts.base import Contract
from career_lab.contracts.v2 import (
    FileRef, RunManifest, RuntimeBundle, EvaluationBundle, SplitManifest,
    TestCampaign, CampaignCandidate, ActionProposal, read_file, require_confirmatory, digest, canonical,
)
from career_lab.contracts.v2.files import load_bundle
from .ports import PortError
from .journal import RunJournal


class SuiteRun(Contract):
    manifest: FileRef
    policy: Literal["checklist", "tool_loop", "active_acquisition"]
    goal: str
    policy_config: FileRef


class SuiteSpec(Contract):
    schema_version: Literal[1] = 1
    id: str
    purpose: Literal["module_test", "development", "confirmatory", "regression"]
    split_manifest: FileRef
    campaign: FileRef | None = None
    runs: tuple[SuiteRun, ...] = Field(min_length=1)
    comparison_budget_equal: bool = True

    @model_validator(mode="after")
    def confirmatory(self):
        if self.purpose == "confirmatory" and self.campaign is None:
            raise ValueError("confirmatory suite needs campaign")
        return self


def validate_suite(spec: SuiteSpec, root: Path):
    split = SplitManifest.model_validate_json(read_file(root, spec.split_manifest))
    campaign = TestCampaign.model_validate_json(read_file(root, spec.campaign)) if spec.campaign else None
    rows = []
    llm_model_files = []
    for item in spec.runs:
        manifest = RunManifest.model_validate_json(read_file(root, item.manifest))
        runtime = load_bundle(root, manifest.runtime, RuntimeBundle)
        evaluation = load_bundle(root, manifest.evaluation, EvaluationBundle)
        if runtime.source != manifest.source:
            raise PortError("runtime_source_mismatch")
        # Verify only the selected record identity here; do not open test scenario contents.
        members = [x for x in split.entries if x.structure_id == manifest.lineage.structure_id
                   and x.component_id == manifest.lineage.component_id and x.split == manifest.split
                   and x.file == manifest.scenario]
        if not members or manifest.lineage.session_id != manifest.session_id or manifest.lineage.run_id != manifest.id:
            raise PortError("run_lineage_mismatch")
        if manifest.split == "test":
            if spec.purpose != "confirmatory" or manifest.campaign != spec.campaign:
                raise PortError("test_access_not_authorized")
            candidate = CampaignCandidate(id=manifest.runtime.sha256, runtime=manifest.runtime,
                evaluation=manifest.evaluation, source=manifest.source, budget=manifest.budget)
            # Match by complete identity, allowing coordinator-chosen candidate IDs.
            candidate = next((c for c in campaign.candidates if c.runtime == candidate.runtime
                              and c.evaluation == candidate.evaluation and c.source == candidate.source
                              and c.budget == candidate.budget), candidate)
            require_confirmatory(campaign, candidate, spec.split_manifest)
        elif spec.purpose == "confirmatory":
            raise PortError("confirmatory_requires_test")
        if spec.purpose in {"development", "module_test"} and manifest.split not in {"train", "dev"}:
            raise PortError("development_split_forbidden")
        if spec.purpose == "regression" and manifest.split != "regression":
            raise PortError("regression_split_required")
        config = json.loads(read_file(root, item.policy_config))
        pinned = {ref.sha256 for ref in (*runtime.prompts, runtime.acquisition, runtime.retrieval,
                                        runtime.decision, runtime.tools, runtime.model)}
        if item.policy_config.sha256 not in pinned:
            raise PortError("policy_config_not_frozen_in_runtime")
        if item.policy != "checklist":
            llm_model_files.append((manifest.provider, manifest.model_revision, runtime.model.sha256))
        rows.append((item, manifest, config))
    if len({m.id for _, m, _ in rows}) != len(rows):
        raise PortError("duplicate_run_id")
    if spec.comparison_budget_equal and len({digest(m.budget) for _, m, _ in rows}) != 1:
        raise PortError("comparison_budget_mismatch")
    if len({digest(m.evaluation) for _, m, _ in rows}) != 1:
        raise PortError("comparison_evaluation_mismatch")
    if len(set(llm_model_files)) > 1:
        raise PortError("comparison_model_mismatch")
    return rows


def run_suite(spec: SuiteSpec, root: Path, output: Path, factory, *, resume=False):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with RunJournal(output).locked():
        return _run_suite_locked(spec, root, output, factory, resume=resume)


def _run_suite_locked(spec: SuiteSpec, root: Path, output: Path, factory, *, resume=False):
    """Factory consumes frozen identity/config and returns a ReferenceRunner.

    The integration factory binds W06 transport, actual provider and evaluation.
    Nothing in this module imports an arbitrary entrypoint from a manifest.
    """
    rows = validate_suite(spec, root)
    output.mkdir(parents=True, exist_ok=True)
    identity = digest(spec)
    receipt_path = output / "suite.json"
    if receipt_path.exists():
        saved = json.loads(receipt_path.read_text())
        if saved["suite_hash"] != identity:
            raise PortError("suite_output_identity_mismatch")
        if not resume:
            raise PortError("suite_exists_use_resume")
    results = []
    for item, manifest, config in rows:
        try:
            runner = factory(item.policy, config, manifest)
            if runner.policy.name != item.policy:
                raise PortError("factory_policy_mismatch")
            exists = (output / manifest.id / "checkpoint.json").exists()
            state = runner.run(manifest, goal=item.goal, output=output, resume=resume and exists)
            results.append({"run_id": manifest.id, "policy": item.policy,
                "structure_id": manifest.lineage.structure_id, "seed": manifest.seed,
                "status": state["status"], "reason_code": state["reason_code"],
                "model_calls": state["model_calls"], "action_attempts": state["action_attempts"],
                "verified_success": state["status"] == "completed"})
        except Exception as exc:
            results.append({"run_id": manifest.id, "policy": item.policy,
                "structure_id": manifest.lineage.structure_id, "seed": manifest.seed,
                "status": "failed", "reason_code": exc.code if isinstance(exc, PortError) else type(exc).__name__,
                "verified_success": False})
        result = {"suite_hash": identity, "purpose": spec.purpose, "runs": results,
                  "planned_runs": len(rows), "attempted_runs": len(results),
                  "verified_successes": sum(x["verified_success"] for x in results),
                  "complete": len(results) == len(rows) and all(x["status"] not in {"waiting", "unresolved"} for x in results),
                  "research_acceptance": "not_assessed"}
        temporary = receipt_path.with_suffix(".tmp")
        with temporary.open("w") as handle:
            handle.write(canonical(result) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, receipt_path)
    return result
