"""Resolve authenticated input once, before reserving a private review attempt."""

from dataclasses import dataclass
from pathlib import Path

from career_lab.contracts import v2 as C
from career_lab.contracts.v2.engineer import EngineerReviewInput, EngineerSubmissionRecord
from career_lab.scenarios.v2.engine import ScenarioSnapshot
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.scenarios.v2.policy import effective_config
from career_lab.storage.v2_store import V2Store

from .execution import Probe, suite_probes
from .files import PackIndex, check_directory, encode, file_ref
from .identity import source_version
from .submission import submission_files, validate_staged_submission, verified_pack


@dataclass(frozen=True)
class ReviewContext:
    input: EngineerReviewInput
    files: dict[str, bytes]
    submission: EngineerSubmissionRecord
    snapshot: ScenarioSnapshot
    probes: tuple[Probe, ...]
    targets: tuple[str, ...]


def fixed_files(
    module: ScenarioModule,
    auth: C.AuthContext,
    index: PackIndex,
    snapshot: ScenarioSnapshot,
) -> dict[str, bytes]:
    return {
        "scenario.json": C.read_file(module.package.root, index.source.bindings.scenario),
        "probe-suite.json": C.read_file(module.package.root, module.files["probes.json"]),
        "reviewer.json": encode({"implementation": source_version(), "mode": "local-extractive"}),
        "resources.json": encode(
            {
                "resources": snapshot.world.resources,
                "source_versions": snapshot.source_versions,
                "indexed_versions": snapshot.indexed_versions,
                "executor": auth.executor,
                "allowed_objects": auth.allowed_objects,
                "allowed_actions": auth.allowed_actions,
                "capabilities": auth.capabilities,
            }
        ),
    }


def freeze_input(
    record: EngineerSubmissionRecord,
    index: PackIndex,
    files: dict[str, bytes],
    probes: tuple[Probe, ...],
    resolved: C.EffectiveConfig,
) -> EngineerReviewInput:
    return EngineerReviewInput(
        contract_version="engineer-review-v1",
        pack=record.pack,
        baseline_config=file_ref("baseline.json", files["baseline.json"]),
        config=record.config,
        scenario=file_ref("scenario.json", files["scenario.json"]),
        probe_suite=file_ref("probe-suite.json", files["probe-suite.json"]),
        reviewer_version=file_ref("reviewer.json", files["reviewer.json"]),
        resource_snapshot=file_ref("resources.json", files["resources.json"]),
        submission=file_ref("submission.json", files["submission.json"]),
        probe_ids=tuple(p.id for p in probes),
        source_as_of=index.source.as_of,
        resolved_config=resolved,
        work_language=index.work_language,
        model=None,
    )


def prepare_review(
    store: V2Store,
    module: ScenarioModule,
    auth: C.AuthContext,
    pack_root: Path,
    submission_root: Path,
) -> ReviewContext:
    index, pack_files = verified_pack(store, module, auth, pack_root)
    record, candidate, files = submission_files(
        module, auth, index, pack_files, submission_root / "submission.json"
    )
    check_directory(submission_root, files)
    validate_staged_submission(submission_root, record)
    snapshot = store.query_at(auth, index.source.as_of, module.snapshot, operation="tests.create")
    files.update(fixed_files(module, auth, index, snapshot))
    probes = suite_probes(files["probe-suite.json"])
    inputs = freeze_input(
        record,
        index,
        files,
        probes,
        effective_config(module.package, candidate, snapshot.world.resources),
    )
    files["input.json"] = encode(inputs)
    targets = tuple(
        C.TestResultV2.model_validate_json(pack_files[ref.path]).query for ref in index.tests
    )
    return ReviewContext(inputs, files, record, snapshot, probes, targets)
