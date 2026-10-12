"""One-time opening of a sealed held-out test split. Never an approval by itself.

The approval is the TestCampaign file the coordinator writes, with ``opened_at``, after the
user confirms one opening in conversation. This module checks that approval against an
existing freeze (``expansion-v3-w08-freeze-v1``, unchanged), records the opening by
exclusive creation inside the freeze folder itself (``held-out/<dataset>/test.json``, next to
the campaign; committed to git with them), and only then lets the test split be read. The
record's place follows from the freeze alone: no option or environment variable moves it, so
one approval opens the test at most once. A second opening is refused before any test byte
is read; nothing here can be bypassed or confirmed from the command line.
"""

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from career_lab.contracts import v2 as C
from career_lab.contracts.v2.data import CampaignCandidate, TestCampaign
from career_lab.datasets.v3.handoff_package import check_sealed_structure, require_regular
from career_lab.experiments.v3.training.freeze import (
    freeze_selection,
    validate_campaign,
    verify_freeze,
)

from .bundle import json_bytes, sha
from .core import LABELS
from .registry import describe_registration, load_registration
from .return_data import (
    FIXTURE_STATUS,
    SealedManifest,
    json_lines,
    split_file_names,
    strict_json,
    unique_records,
)
from .return_predictions import TOLERANCE

PROTOCOL = "rolecraft-held-out-test-opening-v1"
POLICY_PROTOCOL = "rolecraft-return-review-policy-v1"
MANIFEST_PATH = "dataset-manifest.json"
POLICY_PATH = "review-policy.json"
CHECKPOINT_PATH = "checkpoint-manifest.json"
FREEZE_PATH = "freeze.json"
# The responsible party's own declaration; it must be explicit, never defaulted.
SELECTION_DECLARATION = {
    "training_partitions": ["train"],
    "selection_partition": "dev",
    "test_used_for_selection": False,
}
OPERATOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
HASH = re.compile(r"^[0-9a-f]{64}$")


def review_policy(dataset_id: str, dataset_hash: str) -> dict[str, Any]:
    """What the test review computes; pinned in the freeze as the candidate's evaluation."""
    return {
        "protocol": POLICY_PROTOCOL,
        "dataset_id": dataset_id,
        "dataset_manifest_sha256": dataset_hash,
        "partition": "test",
        "task_type": "relation",
        "label_order": list(LABELS["relation"]),
        "metric_version": "w08-evidence-metrics-v2",
        "evaluation_setting": "given_evidence_only",
        "reload_comparison": {
            "probabilities": "absolute_difference",
            "tolerance": TOLERANCE,
            "labels": "exact",
            "evidence_sets": "exact",
        },
    }


def review_policy_bytes(dataset_id: str, dataset_hash: str) -> bytes:
    return json_bytes(review_policy(dataset_id, dataset_hash))


def verifier_source_digest() -> str:
    """Digest of every product source file the review ran with."""
    root = Path(__file__).resolve().parents[2]
    files = {
        p.relative_to(root).as_posix(): sha(p.read_bytes()) for p in sorted(root.rglob("*.py"))
    }
    return C.digest(files)


def read_sealed(dataset_root: Path, dataset_hash: str) -> SealedManifest:
    """The dataset manifest only; a test opening needs the sealed v3 layout with a test split."""
    raw = strict_json(C.read_file(dataset_root, C.FileRef(path=MANIFEST_PATH, sha256=dataset_hash)))
    try:
        manifest = SealedManifest.model_validate(raw)
    except ValidationError as error:
        raise C.ProtocolError("held_out_layout_required", status=403) from error
    check_sealed_structure(
        {split: entry.files for split, entry in manifest.splits.items()},
        manifest.files,
        manifest.test_sealed,
    )
    if "test" not in manifest.splits:
        raise C.ProtocolError("held_out_layout_required", status=403)
    return manifest


@dataclass(frozen=True)
class PreparedFreeze:
    root: Path
    freeze: C.FileRef
    candidate: CampaignCandidate


def prepare_test_freeze(
    output: Path,
    *,
    dataset_root: Path,
    dataset_hash: str,
    registry_root: Path,
    registration: C.FileRef,
    checkpoint_manifest: Path,
    source: C.SourceIdentity,
    source_files: dict[str, bytes],
    candidate_id: str,
    budget: C.Budget,
) -> PreparedFreeze:
    """Collect what a test opening pins into a new freeze directory. Preparation only.

    ``source`` describes the producer's frozen code; its overlay and dependency locks must be
    among ``source_files``. The freeze's ``fixture`` flag follows the dataset status.
    """
    output = Path(output)
    output.mkdir(parents=True)
    manifest = read_sealed(Path(dataset_root), dataset_hash)
    describe_registration(registry_root, registration)
    policy = review_policy_bytes(manifest.dataset_id, dataset_hash)
    members = {
        MANIFEST_PATH: C.read_file(
            Path(dataset_root), C.FileRef(path=MANIFEST_PATH, sha256=dataset_hash)
        ),
        registration.path: C.read_file(Path(registry_root), registration),
        POLICY_PATH: policy,
        CHECKPOINT_PATH: Path(checkpoint_manifest).read_bytes(),
        **source_files,
    }
    refs = []
    for name, data in members.items():
        ref = C.FileRef(path=name, sha256=sha(data))
        path = output / ref.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        refs.append(ref)
    candidate = CampaignCandidate(
        id=candidate_id,
        runtime=registration,
        evaluation=C.FileRef(path=POLICY_PATH, sha256=sha(policy)),
        source=source,
        budget=budget,
    )
    freeze_selection(
        output,
        FREEZE_PATH,
        files=refs,
        source=source,
        selection={
            "selection_split": "dev",
            "test_used_for_selection": False,
            "purpose": "held_out_test_opening",
        },
        split_manifest=C.FileRef(path=MANIFEST_PATH, sha256=dataset_hash),
        fixture=manifest.status == FIXTURE_STATUS,
        candidates=(candidate,),
    )
    frozen = C.FileRef(path=FREEZE_PATH, sha256=sha((output / FREEZE_PATH).read_bytes()))
    return PreparedFreeze(output, frozen, candidate)


@dataclass(frozen=True)
class HeldOutRequest:
    """The approval inputs of ``verify-return --partition test``."""

    freeze: Path | None = None
    freeze_hash: str | None = None
    campaign: Path | None = None
    campaign_hash: str | None = None
    operator: str | None = None


@dataclass(frozen=True)
class HeldOutOpening:
    """The recorded opening; the only thing the test reader accepts."""

    path: Path
    record: dict[str, Any]
    raw: bytes

    def require_open(self, dataset_hash: str) -> None:
        if (
            self.record["dataset_manifest_sha256"] != dataset_hash
            or not self.path.is_file()
            or self.path.read_bytes() != self.raw
        ):
            raise C.ProtocolError("held_out_test_not_opened", status=403)


RECORD_FOLDER = "held-out"


def opening_record_path(freeze_root: Path, dataset_hash: str) -> Path:
    """Where the one opening of this dataset under this freeze is recorded."""
    if not HASH.fullmatch(dataset_hash):
        raise C.ProtocolError("held_out_dataset_identity_invalid")
    return Path(freeze_root) / RECORD_FOLDER / dataset_hash / "test.json"


def check_declaration(path: Path, manifest: SealedManifest, dataset_hash: str) -> bytes:
    raw = Path(path).read_bytes()
    declared = strict_json(raw)
    if not isinstance(declared, dict):
        raise C.ProtocolError("held_out_selection_declaration_required", status=403)
    if any(key not in declared for key in SELECTION_DECLARATION):
        raise C.ProtocolError("held_out_selection_declaration_required", status=403)
    if any(declared[key] != value for key, value in SELECTION_DECLARATION.items()):
        raise C.ProtocolError("model_return_selection_contaminated", status=403)
    if (declared.get("dataset_id"), declared.get("dataset_manifest_sha256")) != (
        manifest.dataset_id,
        dataset_hash,
    ):
        raise C.ProtocolError("return_checkpoint_identity_mismatch")
    return raw


def check_returned_rows(
    returned: dict[str, dict[str, Any]],
    declared_revision: Any,
    registered_revision: str,
    dataset_root: Path,
    manifest: SealedManifest,
) -> None:
    """What can be found wrong before the opening: the rows' model and record identities.

    Reads only the sealed test metadata (record_id, input_hash, split), never test labels.
    """
    revisions = {row.get("model_revision") for row in returned.values()}
    if len(revisions) != 1:
        raise C.ProtocolError("return_prediction_revision_mismatch")
    revision = next(iter(revisions))
    if revision != declared_revision:
        raise C.ProtocolError("return_checkpoint_identity_mismatch")
    if revision != registered_revision:
        raise C.ProtocolError("held_out_prediction_registration_mismatch")
    name = split_file_names("test")["metadata"]
    require_regular(Path(dataset_root), name)
    ref = C.FileRef(path=name, sha256=manifest.splits["test"].files[name].sha256)
    metadata = unique_records(json_lines(C.read_file(Path(dataset_root), ref)))
    if any(row.get("split") != "test" for row in metadata.values()):
        raise C.ProtocolError("held_out_test_metadata_split_mismatch")
    expected = {(rid, row.get("input_hash")) for rid, row in metadata.items()}
    if {(rid, row.get("input_hash")) for rid, row in returned.items()} != expected:
        raise C.ProtocolError("return_prediction_record_set_mismatch")


def open_held_out_test(
    request: HeldOutRequest,
    *,
    dataset_root: Path,
    dataset_hash: str,
    registry_root: Path | None,
    registration: C.FileRef | None,
    checkpoint_manifest: Path | None,
    returned: dict[str, dict[str, Any]],
) -> HeldOutOpening:
    """Check the approval and the returned rows, then record the opening exclusively.

    Every check runs before the record exists; only the last one reads the sealed test
    metadata, and none reads test labels. Once created, the record stays even if the review
    fails afterwards; it is never retried.
    """
    supplied = {
        "--freeze": request.freeze,
        "--freeze-hash": request.freeze_hash,
        "--campaign": request.campaign,
        "--campaign-hash": request.campaign_hash,
        "--operator": request.operator,
        "--registry": registry_root,
        "--registration-path/--registration-hash": registration,
        "--checkpoint-manifest": checkpoint_manifest,
    }
    missing = [name for name, value in supplied.items() if value is None]
    if missing:
        raise C.ProtocolError(
            "held_out_test_authorization_required", "missing: " + ", ".join(missing), status=403
        )
    if not OPERATOR.fullmatch(request.operator):
        raise C.ProtocolError("held_out_operator_invalid")
    freeze_path = Path(request.freeze).resolve()
    freeze_root = freeze_path.parent
    freeze_ref = C.FileRef(path=freeze_path.name, sha256=request.freeze_hash)
    try:
        campaign_path = Path(request.campaign).resolve().relative_to(freeze_root)
    except ValueError:
        raise C.ProtocolError("held_out_campaign_outside_freeze_root", status=403) from None
    campaign_ref = C.FileRef(path=campaign_path.as_posix(), sha256=request.campaign_hash)
    record_path = opening_record_path(freeze_root, dataset_hash)
    if record_path.exists() or record_path.is_symlink():
        raise C.ProtocolError("held_out_test_already_opened", status=403)
    # The record must live in the freeze folder itself, never behind a link to elsewhere.
    if any(
        folder.is_symlink() or (folder.exists() and not folder.is_dir())
        for folder in (freeze_root / RECORD_FOLDER, record_path.parent)
    ):
        raise C.ProtocolError("held_out_record_location_invalid", status=403)
    manifest = read_sealed(Path(dataset_root), dataset_hash)
    if manifest.status == FIXTURE_STATUS:
        raise C.ProtocolError("fixture_cannot_authorize_confirmatory", status=403)
    declaration = check_declaration(checkpoint_manifest, manifest, dataset_hash)

    try:
        campaign = TestCampaign.model_validate_json(C.read_file(freeze_root, campaign_ref))
    except ValidationError as error:
        raise C.ProtocolError("held_out_campaign_invalid", status=403) from error
    candidates = [item for item in campaign.candidates if item.runtime == registration]
    if len(candidates) != 1:
        raise C.ProtocolError("held_out_campaign_candidate_mismatch", status=403)
    candidate = candidates[0]
    authorized = validate_campaign(
        freeze_root,
        freeze_ref=freeze_ref,
        campaign_ref=campaign_ref,
        candidate=candidate,
        split_manifest=C.FileRef(path=MANIFEST_PATH, sha256=dataset_hash),
    )
    frozen = verify_freeze(freeze_root, freeze_ref)
    pins = {item["path"]: item["sha256"] for item in frozen["files"]}
    if pins.get(CHECKPOINT_PATH) != sha(declaration):
        raise C.ProtocolError("held_out_checkpoint_manifest_not_frozen", status=403)
    policy = review_policy_bytes(manifest.dataset_id, dataset_hash)
    if C.read_file(freeze_root, candidate.evaluation) != policy:
        raise C.ProtocolError("held_out_review_policy_mismatch", status=403)
    summary = describe_registration(registry_root, registration)
    # The model must load here (files, runtime pins, optional extra) before the opening.
    load_registration(registry_root, registration)
    check_returned_rows(
        returned,
        strict_json(declaration).get("model_revision"),
        summary.model_revision,
        Path(dataset_root),
        manifest,
    )

    record = {
        "protocol": PROTOCOL,
        "dataset_id": manifest.dataset_id,
        "dataset_manifest_sha256": dataset_hash,
        "campaign": {"id": campaign.id, "path": campaign_ref.path, "sha256": campaign_ref.sha256},
        "campaign_sha256": campaign_ref.sha256,
        "candidate_id": authorized["candidate_id"],
        "freeze": {
            "id": authorized["freeze_id"],
            "path": freeze_ref.path,
            "sha256": freeze_ref.sha256,
        },
        "freeze_sha256": freeze_ref.sha256,
        "registration": {
            "id": summary.id,
            "path": registration.path,
            "sha256": registration.sha256,
        },
        "review_policy_sha256": sha(policy),
        "verifier_source_digest": verifier_source_digest(),
        "operator": request.operator,
        "opened_at": datetime.now(UTC).isoformat(),
    }
    raw = json_bytes(record)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(record_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        raise C.ProtocolError("held_out_test_already_opened", status=403) from None
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return HeldOutOpening(record_path, record, raw)
