"""Authenticated immutable configuration submissions using the frozen file protocol."""

from pathlib import Path
from typing import Any

from career_lab.contracts import v2 as C
from career_lab.contracts.v2.engineer import (
    EngineerSubmissionRecord,
    validate_submission_files,
)
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.scenarios.v2.policy import validate_config
from career_lab.storage.v2_store import V2Store

from .capture import capture
from .files import PackIndex, check_directory, encode, publish, retained_documentation


def verified_pack(
    store: V2Store, module: ScenarioModule, auth: C.AuthContext, root: Path
) -> tuple[PackIndex, dict[str, bytes]]:
    retained = retained_documentation(root)
    index, pack, _ = retained
    module.check_bindings(index.source.bindings)
    if pack.config.session_id != auth.session_id:
        raise C.ProtocolError("engineer_session_mismatch", status=403)
    tests = [C.TestResultV2.model_validate_json(C.read_file(root, ref)) for ref in index.tests]
    files = capture(
        store,
        module,
        auth,
        [test.id for test in tests],
        as_of=index.source.as_of,
        retained=retained,
    )
    check_directory(root, files)
    store.authorize(auth, "act", "tests.create")
    return index, files


def submission_files(
    module: ScenarioModule,
    auth: C.AuthContext,
    index: PackIndex,
    pack_files: dict[str, bytes],
    source: Path,
) -> tuple[EngineerSubmissionRecord, C.AssistantConfig, dict[str, bytes]]:
    record = EngineerSubmissionRecord.model_validate_json(source.read_bytes(), strict=True)
    if record.executor != auth.executor:
        raise C.ProtocolError("engineer_executor_mismatch", status=403)
    if record.work_language != index.work_language:
        raise C.ProtocolError("engineer_language_mismatch", status=409)
    original = C.AssistantConfig.model_validate_json(pack_files[index.config.path])
    if record.base_config_hash != index.config.sha256 or record.pack != index.pack:
        raise C.ProtocolError("engineer_base_or_pack_mismatch", status=409)
    # References are data files, never execution parameters. Keep this local
    # repository flat and reserve provenance/record names against collisions.
    refs = [record.pack, record.config]
    if record.regression_report is not None:
        refs.append(record.regression_report)
    names = [ref.path for ref in refs]
    if len(set(names)) != len(names) or any(
        Path(name).name != name or name in {"submission.json", "baseline.json"} for name in names
    ):
        raise C.ProtocolError("engineer_submission_filename_invalid")
    files = {ref.path: C.read_file(source.parent, ref) for ref in refs}
    if files[record.pack.path] != pack_files[index.pack.path]:
        raise C.ProtocolError("engineer_pack_mismatch", status=409)
    candidate = C.AssistantConfig.model_validate_json(files[record.config.path], strict=True)
    if candidate.id != original.id or candidate.session_id != original.session_id:
        raise C.ProtocolError("engineer_candidate_identity_mismatch", status=409)
    if candidate.min_score_calibration != original.min_score_calibration:
        raise C.ProtocolError("engineer_calibration_reference_forbidden", status=403)
    validate_config(module.package, candidate, auth.session_id)
    # Validate claims through the shared protocol without duplicating its model.
    # Baseline is read from the authenticated pack, not from the input directory.
    files["baseline.json"] = pack_files[index.config.path]
    files["submission.json"] = encode(record)
    return record, candidate, files


def validate_staged_submission(root: Path, record: EngineerSubmissionRecord) -> None:
    from .files import file_ref

    validate_submission_files(
        root,
        record,
        expected_pack=record.pack,
        baseline=file_ref("baseline.json", (root / "baseline.json").read_bytes()),
    )


def submit_configuration(
    store: V2Store,
    module: ScenarioModule,
    auth: C.AuthContext,
    pack_root: Path,
    source: Path,
    output: Path,
) -> dict[str, Any]:
    index, pack_files = verified_pack(store, module, auth, pack_root)
    record, _, files = submission_files(module, auth, index, pack_files, source)
    directory = "submission-" + C.digest(record.id)
    target = output / directory
    # Shared checks execute before publication, including a bad claim reference.
    from tempfile import TemporaryDirectory

    with TemporaryDirectory(prefix="engineer-submit-") as temp:
        stage = Path(temp)
        for name, raw in files.items():
            (stage / name).write_bytes(raw)
        validate_staged_submission(stage, record)
    try:
        publish(target, files)
    except C.ProtocolError as error:
        if error.code == "engineer_pack_changed":
            raise C.ProtocolError("engineer_submission_conflict", status=409) from None
        raise
    return {"status": "submitted", "submission_id": record.id, "directory": directory}
